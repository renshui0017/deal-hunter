#!/usr/bin/env python3
"""GLOBAL DEAL HUNTER collector v1.

Runs on GitHub Actions every 2 hours (see collect.yml).
No LLM, no secrets, no paid APIs. It fetches curated RSS/Atom sources,
filters by category keywords, dedupes against seen.json, extracts dates,
expires old deals, watches a list of official pricing pages for changes,
and writes deals.json + last_run.json.

Honesty rules (do not weaken these):
- Everything this script collects is marked status="unverified" (待核实)
  until a human marks it active. The script never claims verification.
- value_score is a rough keyword heuristic, labelled as an estimate.
- Any source that fails is recorded in last_run.json, never silently dropped.
- Dates are extracted by regex; when none is found, end stays null.
"""
import hashlib
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import feedparser
import requests

ROOT = Path(__file__).resolve().parent
UA = {"User-Agent": "DealHunterCollector/1.0 (+https://github.com/renshui0017/deal-hunter)"}
NOW = datetime.now(timezone.utc)
TODAY = NOW.date()

CATEGORIES = {
    "ai": ["chatgpt", "claude", "gemini", "midjourney", "suno", "openai", "anthropic",
           "grok", "deepseek", "qwen", "kimi", "copilot", "大模型", "人工智能", "token"],
    "crypto": ["airdrop", "空投", "testnet", "测试网", "binance", "币安", "okx", "coinbase",
               "crypto", "加密", "交易所", "积分计划"],
    "ucard": ["虚拟卡", "virtual card", "u卡", "u 卡", "返现", "cashback", "开卡奖励"],
    "bank": ["开户奖励", "存款优惠", "推荐奖励", "referral bonus", "免手续费", "银行开户"],
    "vps": ["vps", "云服务器", "免费服务器", "cloud credits", "云额度", "域名优惠", "免费主机"],
    "software": ["免费试用", "free trial", "终身会员", "lifetime", "学生优惠",
                 "student discount", "开发者福利", "developer program"],
}
# English signals match as whole words (so "promoting" does not trip "promo");
# CJK signals match as substrings (no word boundaries in Chinese).
DEAL_PATTERNS = [re.compile(p, re.I) for p in
                 [r"\bfree\b", r"\bdiscounts?\b", r"\bairdrop\b", r"\bbonus(es)?\b",
                  r"\btrials?\b", r"\boffers?\b", r"\bpromos?\b", r"\blifetime\b",
                  r"\bcashback\b", r"\$0\b"]]
DEAL_CJK = ["免费", "折扣", "赠送", "空投", "奖励", "试用", "优惠",
            "终身", "返现", "免单", "0元"]

# Titles matching these are meta/spam posts, never deals.
TITLE_DENY = ["reopening", "re-opening", "rules", "weekly thread",
              "daily discussion", "megathread", "read the rules",
              "referral code", "referall", "ref code", "invite code",
              "use my code", "my referral", "邀请码",
              "sign up with my link", "weekly sticky", "monthly sticky"]
MAX_NEW_PER_SOURCE = 15

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"])}


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def link_hash(link):
    return hashlib.sha1(link.encode("utf-8")).hexdigest()[:12]


def extract_end_date(text):
    """Best-effort end-date extraction. Returns YYYY-MM-DD or None."""
    if not text:
        return None
    candidates = []
    for y, m, d in re.findall(r"(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})", text):
        try:
            candidates.append(datetime(int(y), int(m), int(d)).date())
        except ValueError:
            pass
    for mon, d, y in re.findall(
            r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{1,2}),?\s+(20\d{2})",
            text, re.I):
        try:
            candidates.append(datetime(int(y), MONTHS[mon.lower()[:3]], int(d)).date())
        except ValueError:
            pass
    for m, d in re.findall(r"(\d{1,2})月(\d{1,2})日", text):
        try:
            dt = datetime(TODAY.year, int(m), int(d)).date()
            candidates.append(dt)
        except ValueError:
            pass
    future = [c for c in candidates if TODAY <= c <= TODAY + timedelta(days=400)]
    if not future:
        return None
    # Prefer a date mentioned near an expiry keyword; else take the latest.
    return max(future).isoformat()


def kw_in(text, kw):
    """Whole-word match for ASCII keywords, substring for CJK."""
    if kw.isascii():
        return re.search(r"\b" + re.escape(kw) + r"\b", text, re.I) is not None
    return kw in text


def has_deal_signal(text):
    if any(p.search(text) for p in DEAL_PATTERNS):
        return True
    return any(s in text for s in DEAL_CJK)


def categorize(text):
    for cat, keywords in CATEGORIES.items():
        if any(kw_in(text, k) for k in keywords):
            return cat
    return None


def looks_like_deal(title, summary=""):
    """A deal signal must appear in the title, or (signal in summary AND a
    category keyword in the title). This drops meta posts whose body happens
    to mention 'free' (e.g. 'Reopening our sub!')."""
    if has_deal_signal(title):
        return True
    if has_deal_signal(summary):
        all_keywords = [k for kws in CATEGORIES.values() for k in kws]
        return any(kw_in(title, k) for k in all_keywords)
    return False


def title_denied(title):
    t_low = title.lower()
    return any(d in t_low for d in TITLE_DENY)


def guess_cost_type(text):
    low = text.lower()
    if "试用" in text or "trial" in low:
        return "免费试用"
    if "充值" in text or "recharge" in low or "deposit" in low:
        return "需要充值"
    if "交易量" in text or "trading volume" in low:
        return "需要交易量"
    if "邀请" in text or "invite" in low or "referral" in low:
        return "需要邀请"
    if "免费" in text or "free" in low:
        return "真正免费"
    return "待核实"


def score_deal(text):
    low = text.lower()
    score = 30
    if "终身" in text or "lifetime" in low:
        score += 30
    if "免费" in text or "free" in low:
        score += 15
    m = re.search(r"\$(\d+)", text)
    if m:
        score += 20 if int(m.group(1)) >= 100 else 10
    if "空投" in text or "airdrop" in low:
        score += 10
    if "学生" in text or "student" in low:
        score += 5
    return min(score, 95)  # heuristic never reaches 100


def fetch_rss(source):
    parsed = feedparser.parse(source["url"], request_headers=UA)
    if getattr(parsed, "status", 200) >= 400:
        raise RuntimeError(f"HTTP {parsed.status}")
    if parsed.bozo and not parsed.entries:
        raise RuntimeError(f"parse error: {parsed.bozo_exception}")
    return parsed.entries


def main():
    sources = load_json(ROOT / "sources.json", {"rss": [], "watchlist": []})
    data = load_json(ROOT / "deals.json", {"updated_at": None, "deals": []})
    seen = load_json(ROOT / "seen.json", {"links": []})
    archive = load_json(ROOT / "archive.json", {"archived": []})
    watch_state = load_json(ROOT / "watchlist_state.json", {})

    deals = data.get("deals", [])
    seen_links = set(seen.get("links", []))
    report_sources = []
    new_items = 0

    # 1. Collect from RSS/Atom sources.
    for src in sources.get("rss", []):
        name = src.get("name", src.get("url", "?"))
        try:
            entries = fetch_rss(src)
            kept = 0
            for e in entries:
                if kept >= MAX_NEW_PER_SOURCE:
                    break
                link = (getattr(e, "link", "") or "").strip()
                title = (getattr(e, "title", "") or "").strip()
                summary = (getattr(e, "summary", "") or getattr(e, "description", "") or "").strip()
                if not link or not title or link in seen_links:
                    continue
                if title_denied(title):
                    continue
                text = f"{title} {summary}"
                if not looks_like_deal(title, summary):
                    continue
                # Categorize on the TITLE only (body keywords misfiled a
                # BeerMoney sticky as crypto); the source hint is the fallback.
                cat = categorize(title) or src.get("category_hint")
                if not cat:
                    continue
                deal = {
                    "id": "auto-" + link_hash(link),
                    "name": title[:120],
                    "category": cat,
                    "summary": re.sub(r"<[^>]+>", "", summary)[:300] or title,
                    "value": "待核实",
                    "value_score": score_deal(text),
                    "conditions": "待核实（自动采集，需人工确认）",
                    "regions": ["待核实"],
                    "start": None,
                    "end": extract_end_date(text),
                    "steps": ["打开官方链接查看活动规则"],
                    "official_link": link,
                    "source": name,
                    "source_link": link,
                    "verified_at": None,
                    "status": "unverified",
                    "risk": "自动采集，未经人工验证；参与前请核对官方页面",
                    "cost_type": guess_cost_type(text),
                }
                deals.append(deal)
                seen_links.add(link)
                kept += 1
            new_items += kept
            report_sources.append({"name": name, "ok": True,
                                   "entries": len(entries), "new": kept})
        except Exception as exc:  # noqa: BLE001 - one bad source must not kill the run
            report_sources.append({"name": name, "ok": False, "error": str(exc)[:200]})

    # 2. Expire deals whose end date has passed.
    still_active, expired_now = [], 0
    for d in deals:
        end = d.get("end")
        if end:
            try:
                if datetime.strptime(end, "%Y-%m-%d").date() < TODAY:
                    d["status"] = "expired"
                    archive.setdefault("archived", []).append(d)
                    expired_now += 1
                    continue
            except ValueError:
                pass
        still_active.append(d)
    deals = still_active

    # 3. Watch official pages for changes (hash + status transitions only,
    # so a permanently-403 page is reported once, not every run).
    changes = []
    for page in sources.get("watchlist", []):
        url = page.get("url", "")
        name = page.get("name", url)
        prev = watch_state.get(url) or {}
        try:
            r = requests.get(url, headers=UA, timeout=20)
            status = r.status_code
            digest = (hashlib.sha1(r.content).hexdigest()[:16]
                      if status == 200 else None)
        except Exception as exc:  # noqa: BLE001
            status, digest = "error", None
            note = f"抓取失败：{exc}"[:120]
            # Only report when we have a baseline (prev non-empty).
            if prev and prev.get("status") != "error":
                changes.append({"name": name, "url": url, "note": note})
            watch_state[url] = {"status": status, "hash": None}
            continue
        if prev and prev.get("status") != status:
            changes.append({"name": name, "url": url,
                            "note": f"HTTP 状态变化：{prev.get('status')} → {status}"})
        elif status == 200 and prev.get("hash") and prev["hash"] != digest:
            changes.append({"name": name, "url": url,
                            "note": "页面内容有变动，请人工查看是否有新优惠或规则变化"})
        watch_state[url] = {"status": status, "hash": digest}

    # 4. Light link re-check: rotate through active deals, 10 per run.
    checked = []
    actives = [d for d in deals if d.get("status") == "active"]
    actives.sort(key=lambda d: d.get("last_checked") or "")
    for d in actives[:10]:
        try:
            r = requests.head(d["official_link"], headers=UA, timeout=10,
                              allow_redirects=True)
            d["last_checked"] = NOW.strftime("%Y-%m-%d %H:%M UTC")
            checked.append({"id": d["id"], "http": r.status_code})
        except Exception as exc:  # noqa: BLE001
            checked.append({"id": d["id"], "http": f"error: {exc}"[:80]})

    # 5. Sort: active first by value_score desc, then unverified by score.
    deals.sort(key=lambda d: (0 if d.get("status") == "active" else 1,
                              -(d.get("value_score") or 0)))

    save_json(ROOT / "deals.json", {
        "updated_at": NOW.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "deals": deals,
    })
    save_json(ROOT / "seen.json", {
        "links": sorted(seen_links),
        "updated_at": NOW.strftime("%Y-%m-%dT%H:%M:%SZ"),
    })
    save_json(ROOT / "archive.json", archive)
    save_json(ROOT / "watchlist_state.json", watch_state)
    save_json(ROOT / "last_run.json", {
        "run_at": NOW.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sources": report_sources,
        "new_items": new_items,
        "expired_items": expired_now,
        "page_changes": changes,
        "link_checks": checked,
        "total_deals": len(deals),
    })
    print(f"done: +{new_items} new, {expired_now} expired, "
          f"{len(deals)} deals total, {len(report_sources)} sources")


if __name__ == "__main__":
    sys.exit(main())

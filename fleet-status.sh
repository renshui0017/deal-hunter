#!/bin/bash
# Fleet status collector for InstaBox (deal-hunter repo).
# Checks the fleet every run, writes fleet-status.json, pushes to GitHub
# and mirrors to LXI. Runs every 15 min via fleet-loop.sh.
# The dashboard page fetches this file live on every open.
set -u
cd ~/deal-hunter || exit 1
UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"

code() { # $1=url -> http code or 000
  curl -s -A "$UA" -o /dev/null -w "%{http_code}" --max-time 15 "$1" 2>/dev/null || echo 000
}

# --- InstaBox self ---
UPTIME=$(uptime -p 2>/dev/null || echo "?")
if pgrep -x xray >/dev/null 2>&1; then XRAY="running"; else XRAY="none"; fi
if ss -tln 2>/dev/null | grep -qE "8080|8081"; then PORTS="listening"; else PORTS="none"; fi
if pgrep -f "deal-hunter/loop.sh" >/dev/null 2>&1; then COLLECTOR="running"; else COLLECTOR="stopped"; fi
if [ "$XRAY" = "none" ] && [ "$PORTS" = "none" ]; then IB_STATUS="running"; else IB_STATUS="attention"; fi

# --- Websites (browser UA required: iFastNet kills UA-less connections) ---
USW=$(code https://usw-node-phtg3epy-usw1-free-8.cloady.io/)
LXI_HOME=$(code https://daddy1369.lxi.be/)
LXI_JSON=$(code https://daddy1369.lxi.be/hg-48919cccd3.json)
TH_HTTP=$(code http://daddy1369.thsite.top/)
TH_HTTPS=$(code https://daddy1369.thsite.top/)
AF_ZYA=$(code https://dealhunter.zya.me/)
AF_HSTN=$(code https://dealhunter.hstn.me/)
AF_ICEI=$(code https://dealhunter.iceiy.com/)

# --- Status mapping ---
# Cloady: any HTTP response (incl. 404) = platform reachable
if [ "$USW" != "000" ]; then CL_STATUS="online"; else CL_STATUS="offline"; fi
if [ "$LXI_HOME" = "200" ]; then LXI_STATUS="online"; else LXI_STATUS="offline"; fi
if [ "$TH_HTTPS" = "200" ] || [ "$TH_HTTP" = "200" ]; then TH_STATUS="online"; else TH_STATUS="offline"; fi
AF_OK=0
for c in "$AF_ZYA" "$AF_HSTN" "$AF_ICEI"; do [ "$c" = "200" ] && AF_OK=$((AF_OK+1)); done
if [ "$AF_OK" = "3" ]; then AF_STATUS="online"; elif [ "$AF_OK" = "0" ]; then AF_STATUS="offline"; else AF_STATUS="partial"; fi

NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ)
cat > fleet-status.json <<EOF
{
  "updated_at": "$NOW",
  "items": {
    "instabox": {"status": "$IB_STATUS", "detail": "$UPTIME；xray $XRAY；代理端口 $PORTS；采集循环 $COLLECTOR"},
    "cloady": {"status": "$CL_STATUS", "detail": "usw-node HTTP $USW"},
    "lxi": {"status": "$LXI_STATUS", "detail": "首页 HTTP $LXI_HOME，配置 HTTP $LXI_JSON"},
    "tinkerhost": {"status": "$TH_STATUS", "detail": "HTTP $TH_HTTP，HTTPS $TH_HTTPS"},
    "aeonfree": {"status": "$AF_STATUS", "detail": "$AF_OK/3 在线（zya $AF_ZYA，hstn $AF_HSTN，iceiy $AF_ICEI）"}
  }
}
EOF

# --- Push to GitHub (tolerant: retry once on lock/conflict) ---
git pull --ff-only -q origin main || true
git add fleet-status.json
if git diff --cached --quiet; then
  echo "no status change"
else
  git commit -qm "chore: fleet status $NOW"
  git push -q origin main || { sleep 20; git pull --rebase -q origin main; git push -q origin main; } || echo "git push failed"
fi
curl -fsS -o /dev/null "https://purge.jsdelivr.net/gh/renshui0017/deal-hunter@main/fleet-status.json" || true

# --- Mirror to LXI (base64: LXI WAF blocks raw JSON bodies) ---
if [ -f .mirror-token ]; then
  . ./.mirror-token
  base64 -w0 fleet-status.json | curl -fsS -o /dev/null -X POST -H "X-Upload-Token: $MIRROR_TOKEN" --data-binary @- "https://daddy1369.lxi.be/deal-hunter/upload.php?file=fleet-status.json" || echo "mirror upload failed: fleet-status.json"
fi
echo "fleet status updated $NOW"

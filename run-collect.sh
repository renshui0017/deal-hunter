#!/bin/bash
# Deal Hunter collector runner for InstaBox.
# Pulls latest repo state, runs collect.py, commits + pushes changes,
# purges the jsDelivr cache so the dashboard (Space + Stronki mirror)
# serves fresh data. Safe to run repeatedly; exits 0 when nothing changed.
set -u
cd ~/deal-hunter || exit 1
git pull --ff-only -q origin main || true
.venv/bin/python collect.py || exit 1
git add -A
if git diff --cached --quiet; then
  echo "no changes to push"
  exit 0
fi
git commit -qm "chore: collect $(date -u +%Y-%m-%dT%H:%M:%SZ)"
git push -q origin main || exit 1
for f in deals.json last_run.json archive.json; do
  curl -fsS -o /dev/null "https://purge.jsdelivr.net/gh/renshui0017/deal-hunter@main/$f" || true
done

# Mirror to LXI (mainland-reachable fallback for the dashboard).
# LXI's WAF blocks raw deal JSON, so the body is base64-encoded.
if [ -f .mirror-token ]; then
  . ./.mirror-token
  for f in deals.json last_run.json archive.json; do
    base64 -w0 "$f" | curl -fsS -o /dev/null -X POST -H "X-Upload-Token: $MIRROR_TOKEN" --data-binary @- "https://daddy1369.lxi.be/deal-hunter/upload.php?file=$f" || echo "mirror upload failed: $f"
  done
  echo "mirrored to LXI"
fi
echo "pushed + jsDelivr purged"

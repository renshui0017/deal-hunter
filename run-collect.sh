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
echo "pushed + jsDelivr purged"

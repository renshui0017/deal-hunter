#!/bin/bash
# Deal Hunter periodic collector loop for InstaBox.
# Runs run-collect.sh immediately, then every 30 minutes, until the box
# pauses (max 2h per run). Started by the deal-hunter orchestrator on wake.
# Round 10 (2026-11-15): also kicks off the Jable (fs1.app) sync in the
# background each cycle — non-blocking, failures never affect the collector.
echo $$ > ~/deal-hunter/loop.pid
while true; do
  ~/deal-hunter/run-collect.sh >> ~/deal-hunter/loop.log 2>&1
  (python3 ~/av4-jable/jable-sync.py >> ~/av4-jable/sync.log 2>&1 || true) &
  sleep 1800
done

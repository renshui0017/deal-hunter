#!/bin/bash
# Deal Hunter periodic collector loop for InstaBox.
# Runs run-collect.sh immediately, then every 30 minutes, until the box
# pauses (max 2h per run). Started by the deal-hunter orchestrator on wake.
echo $$ > ~/deal-hunter/loop.pid
while true; do
  ~/deal-hunter/run-collect.sh >> ~/deal-hunter/loop.log 2>&1
  sleep 1800
done

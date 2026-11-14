#!/bin/bash
# Fleet status collector loop for InstaBox.
# Runs fleet-status.sh every 15 minutes. Started once via SSH;
# the fleet-status-watch patrol checks fleet-status.json freshness.
echo $$ > ~/deal-hunter/fleet-loop.pid
while true; do
  ~/deal-hunter/fleet-status.sh >> ~/deal-hunter/fleet-status.log 2>&1
  sleep 900
done

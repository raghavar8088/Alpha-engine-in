#!/bin/sh
# Weekday refresh of the NSE stock-option contract list, in a throwaway container OUTSIDE the backend (the parse peaks
# at ~300 MB; the backend runs near its 800 MB cap). See refresh_stock_options.py for why it exists.
# To schedule it on the box (NOT installed yet - needs the owner's OK), as /etc/cron.d/stockopt-refresh:
#   35 2 * * 1-5 root sh /home/ubuntu/alpha-engine/backend/scripts/refresh_stock_options_cron.sh
# 02:35 UTC = 08:05 IST, before the 09:15 open. The last run's output: /home/ubuntu/logs/stockopt_refresh.log
set -u
B=/home/ubuntu/alpha-engine
LOG=/home/ubuntu/logs/stockopt_refresh.log
mkdir -p "$(dirname "$LOG")"
exec 9>/tmp/stockopt_refresh.lock
flock -n 9 || { echo "$(date -u +%FT%TZ) another refresh is running" >> "$LOG"; exit 0; }
{
  echo "=== $(date -u +%FT%TZ) refresh of the stock-option contracts"
  docker run --rm --memory 600m --memory-swap 1200m --name stockopt_refresh_cron \
    --env-file "$B/.env" \
    -v "$B/backend/app:/app/backend/app:ro" -v "$B/shared:/app/shared:ro" \
    -v "$B/backend/scripts:/app/backend/scripts:ro" \
    -w /app/backend --entrypoint python alpha-engine-backend scripts/refresh_stock_options.py
  echo "exit $?"
} > "$LOG" 2>&1

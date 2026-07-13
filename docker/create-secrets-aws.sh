#!/usr/bin/env bash
# One-time setup: create AWS Secrets Manager secrets for the backend. Run each
# line individually and paste the real value when prompted — never put real
# secrets in this file or in shell history. Requires: aws configure already run.
set -euo pipefail

REGION="ap-south-1"  # Mumbai — lowest latency to NSE/Dhan, matches the GCP config

# Example pattern (repeat per secret):
#   aws secretsmanager create-secret --name tradingai/mongo-url --region "$REGION" \
#     --secret-string "$(read -rsp 'value: ' v; echo "$v")"
# If the secret already exists and you're rotating it:
#   aws secretsmanager put-secret-value --secret-id tradingai/mongo-url --region "$REGION" \
#     --secret-string "$(read -rsp 'value: ' v; echo "$v")"

echo 'tradingai/mongo-url               # MongoDB Atlas mongodb+srv:// connection string (not localhost)'
echo 'tradingai/broker-encryption-key    # value of BROKER_ENCRYPTION_KEY from backend/.env'
echo 'tradingai/groq-key                # GROQ_API_KEY'
echo 'tradingai/dhan-client-id          # DHAN_CLIENT_ID (for TOTP auto-refresh)'
echo 'tradingai/dhan-pin                # DHAN_PIN (for TOTP auto-refresh)'
echo 'tradingai/dhan-totp-secret        # DHAN_TOTP_SECRET (for TOTP auto-refresh)'

# Redis is intentionally omitted — app/ws/manager.py connects lazily on first
# WebSocket client, so it's not needed until live/WebSocket features are wired
# up against a managed Redis (ElastiCache). Add tradingai/redis-url then.

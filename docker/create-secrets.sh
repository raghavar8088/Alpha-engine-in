#!/usr/bin/env bash
# One-time setup: create Secret Manager secrets for the backend. Run each line
# individually and paste the real value when prompted — never put real secrets
# in this file or in shell history.
set -euo pipefail

# Example pattern (repeat per secret):
#   printf '%s' 'PASTE_REAL_VALUE_HERE' | gcloud secrets create tradingai-mongo-url --data-file=-
# If the secret already exists and you're rotating it:
#   printf '%s' 'NEW_VALUE' | gcloud secrets versions add tradingai-mongo-url --data-file=-

echo 'tradingai-mongo-url'              # MongoDB Atlas free-tier connection string (not localhost)
echo 'tradingai-redis-url'              # Memorystore or a managed Redis URL (not localhost)
echo 'tradingai-broker-encryption-key'  # value of BROKER_ENCRYPTION_KEY from backend/.env
echo 'tradingai-groq-key'               # GROQ_API_KEY
echo 'tradingai-anthropic-key'          # ANTHROPIC_API_KEY (not yet set locally per your roadmap notes)

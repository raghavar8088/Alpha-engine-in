#!/usr/bin/env bash
# Run from the TradingAI/ repo root. Requires: gcloud CLI installed + `gcloud auth login` done.
set -euo pipefail

PROJECT_ID="project-8b09d15a-375b-4bb5-80e"
REGION="asia-south1"                 # Mumbai — lowest latency to NSE/Dhan
REPO="tradingai"
IMAGE="asia-south1-docker.pkg.dev/${PROJECT_ID}/${REPO}/backend"
SERVICE="tradingai-backend"

gcloud config set project "$PROJECT_ID"

# 1. One-time: enable required APIs
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com

# 2. One-time: create the Artifact Registry repo
gcloud artifacts repositories create "$REPO" \
  --repository-format=docker \
  --location="$REGION" \
  --description="TradingAI container images" || echo "repo already exists, skipping"

gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet

# 3. Build (from repo root, so the -e ../<service> editable installs resolve) and push
docker build -f docker/Dockerfile.backend -t "$IMAGE:latest" .
docker push "$IMAGE:latest"

# 4. Deploy to Cloud Run, wiring secrets in as env vars (see create-secrets.sh first)
gcloud run deploy "$SERVICE" \
  --image "$IMAGE:latest" \
  --region "$REGION" \
  --platform managed \
  --allow-unauthenticated=false \
  --min-instances=0 \
  --max-instances=2 \
  --set-env-vars="ENABLE_LIVE_TRADING=false,DHAN_BASE_URL=https://api.dhan.co/v2" \
  --set-secrets="MONGO_URL=tradingai-mongo-url:latest,BROKER_ENCRYPTION_KEY=tradingai-broker-encryption-key:latest,GROQ_API_KEY=tradingai-groq-key:latest"
# Redis is intentionally omitted — app/ws/manager.py connects lazily on first
# WebSocket client, so it's not needed until you wire up real-time features.
# Add REDIS_URL=tradingai-redis-url:latest back to --set-secrets once you have
# a managed Redis (Memorystore) and need the WebSocket/live-engine features.
# ANTHROPIC_API_KEY is also omitted — not yet configured (ai_service returns an
# honest not_configured status without it). Add ANTHROPIC_API_KEY=tradingai-anthropic-key:latest
# once you create that secret with a real key.

echo "Deployed. Fetch the URL with: gcloud run services describe $SERVICE --region $REGION --format='value(status.url)'"

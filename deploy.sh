#!/usr/bin/env bash
# Minimal Railway deploy — all secrets via env vars.
# Usage: export TELEGRAM_BOT_TOKEN=... && bash deploy.sh
set -e

: "${TELEGRAM_BOT_TOKEN:?}"
: "${TELEGRAM_WEBHOOK_SECRET:?}"
: "${ALLOWED_USERS:?}"
: "${APIFY_API_TOKEN:?}"
: "${BRIGHTDATA_API_KEY:?}"
: "${ANTHROPIC_API_KEY:?}"
: "${REDIS_URL:?}"

railway init --name bstock-analyzer-bot 2>/dev/null || true

railway variables set \
  TELEGRAM_BOT_TOKEN="$TELEGRAM_BOT_TOKEN" \
  TELEGRAM_WEBHOOK_SECRET="$TELEGRAM_WEBHOOK_SECRET" \
  ALLOWED_USERS="$ALLOWED_USERS" \
  APIFY_API_TOKEN="$APIFY_API_TOKEN" \
  BRIGHTDATA_API_KEY="$BRIGHTDATA_API_KEY" \
  BRIGHTDATA_ZONE="${BRIGHTDATA_ZONE:-web_unlocker1}" \
  ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" \
  REDIS_URL="$REDIS_URL" \
  ENVIRONMENT="production" \
  PORT="8000"

railway up --detach

sleep 15
RAILWAY_URL=$(railway domain 2>/dev/null || echo "")
if [ -n "$RAILWAY_URL" ]; then
  curl -s "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/setWebhook" \
    -d "url=https://${RAILWAY_URL}/webhook" \
    -d "secret_token=${TELEGRAM_WEBHOOK_SECRET}" \
    -d 'allowed_updates=["message","callback_query"]'
  echo "Deployed: https://${RAILWAY_URL}"
fi

#!/usr/bin/env bash
# B-Stock Analyzer Bot — Railway Setup & Deploy
# Usage: bash setup_and_deploy.sh
# Reads all API keys from ~/OneDrive/Masaüstü/API/API KEYS/
set -e

KEYS_DIR="$HOME/OneDrive/Masaüstü/API/API KEYS"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "========================================"
echo "  B-Stock Analyzer Bot — Deploy Script"
echo "========================================"

# ── Read local API keys ──
BD_KEY=$(cat "$KEYS_DIR/Brıght data API key.txt" 2>/dev/null | tr -d '\n\r' || echo "")
ANTHROPIC_KEY=$(cat "$KEYS_DIR/ANTHROPIC (CLAUDE)/API_KEY.txt" 2>/dev/null | tr -d '\n\r' || echo "")
APIFY_KEY=$(cat "$KEYS_DIR/APIFY API TOKEN.txt" 2>/dev/null | tr -d '\n\r' || echo "")
TG_TOKEN=$(cat "$KEYS_DIR/TELEGRAM_BOT_TOKEN.txt" 2>/dev/null | tr -d '\n\r' || echo "")
TG_SECRET=$(cat "$KEYS_DIR/TELEGRAM_WEBHOOK_SECRET.txt" 2>/dev/null | tr -d '\n\r' || echo "")
ALLOWED=$(cat "$KEYS_DIR/ALLOWED_USERS.txt" 2>/dev/null | tr -d '\n\r' || echo "8720167082")

# Upstash: file contains URL+token concatenated
UPSTASH_HOST="caring-feline-74322.upstash.io"
UPSTASH_RAW=$(cat "$KEYS_DIR/UPTASH/"* 2>/dev/null | tr -d '\n\r' || echo "")
UPSTASH_TOKEN="${UPSTASH_RAW#https://$UPSTASH_HOST}"
REDIS_URL="rediss://default:${UPSTASH_TOKEN}@${UPSTASH_HOST}:6380"

# Validate required keys
MISSING=0
[ -z "$TG_TOKEN" ]      && echo "  ❌ TELEGRAM_BOT_TOKEN missing (create $KEYS_DIR/TELEGRAM_BOT_TOKEN.txt)" && MISSING=1
[ -z "$TG_SECRET" ]     && echo "  ⚠️  TELEGRAM_WEBHOOK_SECRET missing — generating..." \
  && TG_SECRET=$(node -e "require('crypto').randomBytes(32).toString('hex')" 2>/dev/null || openssl rand -hex 32) \
  && echo "$TG_SECRET" > "$KEYS_DIR/TELEGRAM_WEBHOOK_SECRET.txt"
[ -z "$BD_KEY" ]        && echo "  ❌ BRIGHTDATA_API_KEY missing" && MISSING=1
[ -z "$ANTHROPIC_KEY" ] && echo "  ❌ ANTHROPIC_API_KEY missing"  && MISSING=1
[ -z "$APIFY_KEY" ]     && echo "  ❌ APIFY_API_TOKEN missing"     && MISSING=1

[ "$MISSING" -eq 1 ] && echo "" && echo "Fix missing keys above, then re-run." && exit 1

echo ""
echo "Keys:"
echo "  ✅ Telegram, Bright Data, Anthropic, Apify, Redis"

# ── Railway login ──
echo ""
echo "==> Railway login (browser will open if needed)..."
railway whoami 2>/dev/null || railway login

# ── Create/link project ──
cd "$SCRIPT_DIR"
echo "==> Creating Railway project..."
railway init --name bstock-analyzer-bot 2>/dev/null || \
  railway link --project bstock-analyzer-bot 2>/dev/null || true

# ── Set env vars ──
echo "==> Setting environment variables..."
railway variables set \
  TELEGRAM_BOT_TOKEN="$TG_TOKEN" \
  TELEGRAM_WEBHOOK_SECRET="$TG_SECRET" \
  ALLOWED_USERS="$ALLOWED" \
  APIFY_API_TOKEN="$APIFY_KEY" \
  BRIGHTDATA_API_KEY="$BD_KEY" \
  BRIGHTDATA_ZONE="web_unlocker1" \
  ANTHROPIC_API_KEY="$ANTHROPIC_KEY" \
  REDIS_URL="$REDIS_URL" \
  ENVIRONMENT="production" \
  PORT="8000"

# ── Deploy ──
echo "==> Deploying..."
railway up --detach

echo "==> Waiting 20s for deploy..."
sleep 20

# ── Set Telegram webhook ──
RAILWAY_URL=$(railway domain 2>/dev/null || echo "")
if [ -n "$RAILWAY_URL" ]; then
  echo "==> Setting Telegram webhook -> https://${RAILWAY_URL}/webhook"
  curl -s "https://api.telegram.org/bot${TG_TOKEN}/setWebhook" \
    -d "url=https://${RAILWAY_URL}/webhook" \
    -d "secret_token=${TG_SECRET}" \
    -d 'allowed_updates=["message","callback_query"]'
  echo ""
  echo "========================================"
  echo "  ✅  DEPLOY TAMAMLANDI!"
  echo "========================================"
  echo "  Bot:    @bstockanalyzerbot"
  echo "  Health: https://${RAILWAY_URL}/health"
  echo "========================================"
else
  echo "  ⚠️  URL alınamadı. 'railway domain' ile kontrol et."
fi

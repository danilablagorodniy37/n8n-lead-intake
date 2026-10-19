#!/bin/sh
# Runs once inside the n8n image before the n8n service starts: creates the two credentials from
# environment variables and imports the three workflows. Safe to run again (import overwrites by id).
set -eu

TEMPLATE=/n8n/credentials.template.json
OUT=/tmp/credentials.json

escape() { printf '%s' "$1" | sed -e 's/[\/&|]/\\&/g' -e 's/"/\\"/g'; }

sed \
  -e "s|__TELEGRAM_BOT_TOKEN__|$(escape "${TELEGRAM_BOT_TOKEN:-replace-me-in-.env}")|" \
  -e "s|__SMTP_HOST__|$(escape "${SMTP_HOST:-mailpit}")|" \
  -e "s|__SMTP_PORT__|$(escape "${SMTP_PORT:-1025}")|" \
  -e "s|__SMTP_USER__|$(escape "${SMTP_USER:-}")|" \
  -e "s|__SMTP_PASSWORD__|$(escape "${SMTP_PASSWORD:-}")|" \
  -e "s|__SMTP_SECURE__|$(escape "${SMTP_SECURE:-false}")|" \
  "$TEMPLATE" > "$OUT"

echo "n8n-import: credentials"
n8n import:credentials --input="$OUT"
rm -f "$OUT"

echo "n8n-import: workflows"
n8n import:workflow --separate --input=/workflows

if [ "${N8N_ACTIVATE_WORKFLOWS:-false}" = "true" ]; then
  echo "n8n-import: activating workflows (needs a reachable WEBHOOK_URL for Telegram)"
  for id in LeadIntakeMain01 LeadIntakeApprv1 LeadIntakeError1; do
    n8n update:workflow --id="$id" --active=true
  done
fi
echo "n8n-import: done"

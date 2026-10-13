#!/usr/bin/env bash
# Idempotent Cloudflare wiring for the inbound edge:
#   1. deploy the edge-inbound Worker
#   2. attach an HTTP pull consumer (with DLQ) to mail-inbound
#   3. point the Email Routing catch-all at the Worker (the dmarc@ rule is left alone)
#   4. set the R2 lifecycle rules (inbox, quarantine and backup retention)
# Reads deploy/.env; prints statuses only, never secret values.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
set -a; source "$ROOT/deploy/.env"; set +a
export CLOUDFLARE_API_TOKEN="$CF_API_TOKEN" CLOUDFLARE_ACCOUNT_ID="$CF_ACCOUNT_ID"
CF=https://api.cloudflare.com/client/v4
AUTH=(-H "Authorization: Bearer $CF_API_TOKEN" -H "Content-Type: application/json")

cfapi() { curl -sS -m 30 "${AUTH[@]}" "$@"; }
check() { python3 -c 'import sys,json; j=json.load(sys.stdin); print("  ok" if j.get("success") else "  FAIL", [e.get("message") for e in j.get("errors",[])][:2]); sys.exit(0 if j.get("success") else 1)'; }

echo "== 1. deploy edge-inbound"
(cd "$ROOT/edge" && npx wrangler deploy 2>&1 | grep -E 'Uploaded|Deployed|Current Version|error|Error' || true)

echo "== 2. HTTP pull consumer on mail-inbound"
consumers=$(cfapi "$CF/accounts/$CF_ACCOUNT_ID/queues/$CF_QUEUE_ID_INBOUND/consumers" \
  | python3 -c 'import sys,json; print(",".join(c.get("type","") for c in json.load(sys.stdin).get("result") or []))')
if [[ "$consumers" == *http_pull* ]]; then
  echo "  already present"
else
  (cd "$ROOT/edge" && npx wrangler queues consumer http add mail-inbound \
    --batch-size 10 --message-retries 5 --visibility-timeout-secs 120 \
    --dead-letter-queue mail-inbound-dlq 2>&1 | tail -2)
fi

echo "== 3. Email Routing catch-all -> edge-inbound"
cfapi -X PUT "$CF/zones/$CF_ZONE_ID/email/routing/rules/catch_all" \
  --data '{"enabled":true,"name":"catch-all to edge-inbound","matchers":[{"type":"all"}],"actions":[{"type":"worker","value":["edge-inbound"]}]}' | check

echo "== 4. R2 lifecycle rules on mail-inbox (in/ 3d, quarantine/ 8d, backups/ 30d)"
cfapi -X PUT "$CF/accounts/$CF_ACCOUNT_ID/r2/buckets/mail-inbox/lifecycle" --data @- <<'JSON' | check
{"rules": [
  {"id": "Default Multipart Abort Rule", "enabled": true, "conditions": {},
   "abortMultipartUploadsTransition": {"condition": {"type": "Age", "maxAge": 604800}}},
  {"id": "inbox-3d", "enabled": true, "conditions": {"prefix": "in/"},
   "deleteObjectsTransition": {"condition": {"type": "Age", "maxAge": 259200}}},
  {"id": "quarantine-8d", "enabled": true, "conditions": {"prefix": "quarantine/"},
   "deleteObjectsTransition": {"condition": {"type": "Age", "maxAge": 691200}}},
  {"id": "backups-30d", "enabled": true, "conditions": {"prefix": "backups/"},
   "deleteObjectsTransition": {"condition": {"type": "Age", "maxAge": 2592000}}}
]}
JSON

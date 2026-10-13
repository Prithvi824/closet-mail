#!/usr/bin/env bash
# Read-only infrastructure check of the Cloudflare, R2 and Resend setup. Prints PASS/FAIL lines and
# never prints secret values. Exit code = number of failed checks.
set -uo pipefail
# Run the last command of a pipeline in this shell, so check() can count failures.
shopt -s lastpipe

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
set -a; source "$ROOT/deploy/.env"; set +a
CF=https://api.cloudflare.com/client/v4
DOMAIN=closetcompute.online
APP=https://app.$DOMAIN
FAILED=0

cf() { curl -sS -m 30 -H "Authorization: Bearer $CF_API_TOKEN" "$CF$1"; }
# check NAME PYTHON_EXPR: evaluates EXPR with `j` = parsed JSON from stdin.
check() {
  local name="$1" expr="$2"
  if python3 -c "import sys,json; j=json.load(sys.stdin); sys.exit(0 if ($expr) else 1)" 2>/dev/null; then
    echo "PASS  $name"
  else
    echo "FAIL  $name"; FAILED=$((FAILED + 1))
  fi
}
status() { curl -s -o /dev/null -m 20 -w '%{http_code}' "$@"; }
expect_status() {
  local name="$1" want="$2"; shift 2
  local got; got=$(status "$@")
  if [[ "$got" =~ ^($want)$ ]]; then echo "PASS  $name ($got)"; else echo "FAIL  $name (got $got, want $want)"; FAILED=$((FAILED + 1)); fi
}

echo "== Cloudflare"
cf /user/tokens/verify | check "API token active" 'j["result"]["status"] == "active"'
cf "/zones/$CF_ZONE_ID" | check "zone $DOMAIN active" 'j["result"]["name"] == "'$DOMAIN'" and j["result"]["status"] == "active"'
cf "/zones/$CF_ZONE_ID/dns_records?type=MX&per_page=50" | check "MX records on apex and rp." \
  '{r["name"] for r in j["result"]} >= {"'$DOMAIN'", "rp.'$DOMAIN'"}'
# The token can read routing rules but not routing settings, so routing is checked via its rules.
cf "/zones/$CF_ZONE_ID/email/routing/rules" | check "Email Routing rules (dmarc@ kept)" \
  'any(m.get("value", "").startswith("dmarc@") for r in j["result"] for m in r.get("matchers", []))'
cf "/zones/$CF_ZONE_ID/email/routing/rules/catch_all" | check "catch-all -> edge-inbound worker" \
  'j["result"]["enabled"] and j["result"]["actions"][0]["type"] == "worker" and "edge-inbound" in j["result"]["actions"][0]["value"]'
cf "/accounts/$CF_ACCOUNT_ID/storage/kv/namespaces/$CF_KV_NAMESPACE_ID" | check "KV namespace reachable" 'j["success"]'
cf "/accounts/$CF_ACCOUNT_ID/r2/buckets/mail-inbox/lifecycle" | check "R2 lifecycle: in/ quarantine/ backups/" \
  '{r.get("conditions", {}).get("prefix") for r in j["result"]["rules"]} >= {"in/", "quarantine/", "backups/"}'
cf "/accounts/$CF_ACCOUNT_ID/queues/$CF_QUEUE_ID_INBOUND/consumers" | check "mail-inbound has an HTTP pull consumer" \
  'any(c.get("type") == "http_pull" for c in j["result"])'
cf "/accounts/$CF_ACCOUNT_ID/queues/$CF_QUEUE_ID_DLQ/metrics" | check "dead-letter queue empty" 'j["result"]["backlog_count"] == 0'

echo "== Resend"
# A sending-only key is refused by the domains API (401/403); 200 means a full-access key.
expect_status "Resend API reachable with the configured key" "200|401|403" \
  -H "Authorization: Bearer $RESEND_API_KEY" https://api.resend.com/domains

echo "== Public"
curl -s -m 20 -H 'accept: application/dns-json' "https://cloudflare-dns.com/dns-query?name=$DOMAIN&type=MX" \
  | check "public MX points at Cloudflare" 'any("mx.cloudflare.net" in a["data"] for a in j.get("Answer", []))'
expect_status "app root requires Access login" "302|303" "$APP/"
expect_status "/api/v1 bypasses Access (API answers 401)" "401" "$APP/api/v1/me"
expect_status "/a/ bypasses Access (bad link page)" "404" "$APP/a/not-a-token"
expect_status "/hooks bypasses Access (webhook rejects unsigned)" "400|503" -X POST "$APP/hooks/email-events"

echo "== $FAILED failed"
exit "$FAILED"

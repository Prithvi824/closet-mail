#!/usr/bin/env bash
# Create deploy/.env.prod with fresh production secrets. Runs once; never overwrites.
# Prints no secret values. BACK THE FILE UP (password manager) before the first deploy:
# losing DATA_ENCRYPTION_KEY / HASH_KEY makes stored data unreadable, and BACKUP_PASSPHRASE
# is the only way to open the database backups.
set -euo pipefail

TARGET="$(cd "$(dirname "$0")/.." && pwd)/.env.prod"
if [[ -e "$TARGET" ]]; then
  echo "refusing: $TARGET already exists (rotating keys would orphan encrypted data)" >&2
  exit 1
fi

umask 077
python3 - "$TARGET" <<'PY'
import base64, secrets, sys

values = {
    "APP_ENV": "prod",
    "APP_BASE_URL": "https://app.closetcompute.online",
    "DATA_ENCRYPTION_KEY": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
    "HASH_KEY": secrets.token_hex(32),
    "SIGNING_KEY": secrets.token_urlsafe(48),
    "BACKUP_PASSPHRASE": secrets.token_urlsafe(32),
}
with open(sys.argv[1], "w") as handle:
    handle.write("# Production-only settings. Generated once by gen-prod-secrets.sh. Back this file up.\n")
    for key, value in values.items():
        handle.write(f"{key}={value}\n")
PY
echo "created $TARGET (mode 600) with: APP_ENV APP_BASE_URL DATA_ENCRYPTION_KEY HASH_KEY SIGNING_KEY BACKUP_PASSPHRASE"
echo "Store a copy in your password manager now."

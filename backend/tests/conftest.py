"""Shared pytest setup: isolated test settings with throwaway keys, no real cloud credentials."""

# 1st party imports
import os
import secrets

# 3rd party imports
from cryptography.fernet import Fernet

# Process env beats .env files, so these overrides apply before any settings are built.
_TEST_ENV = {
    "APP_ENV": "test",
    "APP_BASE_URL": "http://testserver",
    "LOG_DIR": "./logs/test",
    "DATABASE_URL": "postgresql+asyncpg://mailalias:mailalias@localhost:5433/mailalias_test",
    "REDIS_URL": "redis://localhost:6380/15",
    "DATA_ENCRYPTION_KEY": Fernet.generate_key().decode(),
    "HASH_KEY": secrets.token_hex(32),
    "SIGNING_KEY": secrets.token_urlsafe(32),
    # Blank every real credential so no test can reach Cloudflare, R2 or Resend.
    "CF_API_TOKEN": "",
    "CF_ACCOUNT_ID": "test-account",
    "CF_KV_NAMESPACE_ID": "test-kv",
    "CF_QUEUE_ID_INBOUND": "test-queue",
    "CF_QUEUE_ID_DLQ": "test-dlq",
    "R2_ACCESS_KEY_ID": "",
    "R2_SECRET_ACCESS_KEY": "",
    "R2_ENDPOINT": "http://r2.invalid",
    "RESEND_API_KEY": "",
    "RESEND_WEBHOOK_SECRET": "",
    "SPIKE_TO": "",
}
os.environ.update(_TEST_ENV)

"""Application settings loaded from environment variables and `.env` files."""

# 1st party imports
from functools import lru_cache
from pathlib import Path
from typing import Literal

# 3rd party imports
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    """All runtime configuration. Later env files override earlier ones; process env wins."""

    model_config = SettingsConfigDict(
        env_file=(REPO_DIR / "deploy" / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- app
    app_env: Literal["dev", "prod", "test"] = "dev"
    app_base_url: str = "https://app.closetcompute.online"
    log_dir: Path = Path("./logs")
    alias_domain: str = "closetcompute.online"
    reply_domain: str = "rp.closetcompute.online"
    system_from: str = "noreply@closetcompute.online"

    # --- datastores
    database_url: str = "postgresql+asyncpg://mailalias:mailalias@localhost:5433/mailalias"
    prod_database_url: SecretStr | None = None
    redis_url: str = "redis://localhost:6380/3"

    # --- keys
    data_encryption_key: SecretStr
    hash_key: SecretStr
    signing_key: SecretStr
    backup_passphrase: SecretStr | None = None
    pg_dump_bin: str = "pg_dump"  # dev can point this at a wrapper that runs the postgres:17 image

    # --- Cloudflare
    cf_account_id: str = ""
    cf_zone_id: str = ""
    cf_api_token: SecretStr = SecretStr("")
    cf_kv_namespace_id: str = ""
    cf_queue_id_inbound: str = ""
    cf_queue_id_dlq: str = ""
    r2_access_key_id: SecretStr = SecretStr("")
    r2_secret_access_key: SecretStr = SecretStr("")
    r2_endpoint: str = ""
    r2_bucket: str = "mail-inbox"

    # --- Resend
    resend_api_key: SecretStr = SecretStr("")
    resend_smtp_host: str = "smtp.resend.com"
    resend_smtp_port: int = 465
    resend_webhook_secret: SecretStr = SecretStr("")

    # --- spam
    rspamd_url: str = "http://rspamd:11333"
    spam_quarantine_score: float = 6.0
    spam_discard_score: float = 15.0
    spam_check_timeout_seconds: float = 20.0
    quarantine_days: int = 7

    # --- limits
    outbound_daily_cap: int = 95
    user_replies_per_day: int = 50
    user_forwards_per_hour: int = 500
    user_alias_creates_per_hour: int = 20

    # --- processor
    processor_batch: int = 10
    processor_concurrency: int = 4
    processor_visibility_ms: int = 120_000

    # --- manual tests only
    spike_to: str | None = None

    @property
    def is_prod(self) -> bool:
        """Whether the app runs in production mode.

        Returns:
            True when APP_ENV is "prod".
        """
        return self.app_env == "prod"


@lru_cache
def get_settings() -> Settings:
    """Build the settings once per process and cache them.

    Returns:
        The process-wide Settings instance.
    """
    return Settings()

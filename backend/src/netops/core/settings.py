"""Application settings, loaded from environment variables (and an optional .env file)."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class Settings(BaseSettings):
    """All runtime configuration. Field names map to upper-case environment variables."""

    # hide_input_in_errors: a mistyped secret must not end up in a startup error log.
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", hide_input_in_errors=True
    )

    app_env: Literal["development", "test", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_format: Literal["json", "console"] = "json"

    # The same POSTGRES_* variables configure the database container, so they are
    # defined once in deploy/.env. The password has no default on purpose.
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "netops"
    postgres_password: SecretStr
    postgres_db: str = "netops"
    db_pool_size: int = Field(default=5, ge=1)
    db_max_overflow: int = Field(default=10, ge=0)

    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    # Upper bound for each dependency probe in GET /api/health.
    health_check_timeout_seconds: float = Field(default=2.0, gt=0)

    # Fernet key(s) that encrypt stored device credentials (ADR-0004). No default on
    # purpose: the application refuses to start without a valid key.
    credentials_key: SecretStr

    # Device access over SSH (netops.netaccess).
    ssh_port: int = Field(default=22, ge=1, le=65535)
    ssh_connect_timeout_seconds: float = Field(default=10.0, gt=0)
    ssh_command_timeout_seconds: float = Field(default=60.0, gt=0)
    ssh_retries: int = Field(default=1, ge=0, le=5, description="Extra attempts on timeouts.")
    ssh_max_concurrency: int = Field(default=20, ge=1, description="Parallel SSH sessions.")
    # Off until host keys are stored per device (ADR-0004); a warning is logged meanwhile.
    ssh_strict_host_key_checking: bool = False
    ssh_known_hosts_file: Path | None = None
    # Directory for Netmiko session logs (debugging only); passwords are redacted.
    ssh_session_log_dir: Path | None = None

    # Configuration management (M4, ADR-0007). The repository holds complete configurations,
    # secrets included: a local Git repository in its own volume, never pushed anywhere.
    config_repo_path: Path = Path("/var/lib/netops/configs")
    # When the scheduled backup runs: a cron expression (minute hour day month weekday, UTC).
    config_backup_schedule: str = "30 2 * * *"
    # A change window stays open while CONFIG_I / CFGLOG messages keep arriving: it closes
    # this long after the last one (and at the latest after the maximum), then the device's
    # configuration is collected.
    config_change_debounce_seconds: float = Field(default=30.0, gt=0)
    config_change_max_window_seconds: float = Field(default=300.0, gt=0)
    # The account M5 will push changes with; changes made by it count as origin "platform".
    platform_write_username: str | None = None

    # Syslog receiver (the events service). Port 514 inside its container; the host port
    # is set in deploy/.env (SYSLOG_HOST_PORT).
    syslog_bind: str = "0.0.0.0"  # noqa: S104 - inside its container
    syslog_port: int = Field(default=514, ge=1, le=65535)
    syslog_max_datagram_bytes: int = Field(default=2048, ge=480, le=65507)
    # Per source address: sustained messages per second and burst (token bucket).
    syslog_rate_per_source: float = Field(default=50.0, gt=0)
    syslog_burst_per_source: int = Field(default=200, ge=1)

    # Authentication (M7, ADR-0008). Signs the access tokens (HS256): one or more
    # comma-separated random keys of at least 32 characters; the first signs, every one
    # verifies (rotation). No default on purpose: the API refuses to start without it.
    auth_signing_key: SecretStr
    auth_access_token_minutes: int = Field(default=15, ge=1, le=60)
    # A refresh token lives this long unless used (each use rotates it); a session (token
    # family) ends at the latest after auth_session_max_days.
    auth_refresh_token_hours: int = Field(default=12, ge=1, le=24 * 30)
    auth_session_max_days: int = Field(default=7, ge=1, le=90)
    # Roles that must use TOTP. Comma-separated; empty: MFA is optional for everyone.
    auth_mfa_required_roles: str = "admin,operator"
    auth_mfa_issuer: str = "NetOps"
    # Lockout after this many consecutive failures (password or MFA code): first for
    # base seconds, doubling with every further failure up to the maximum.
    auth_lockout_threshold: int = Field(default=5, ge=1)
    auth_lockout_base_seconds: int = Field(default=60, ge=1)
    auth_lockout_max_seconds: int = Field(default=3600, ge=1)
    # Login and MFA requests per client address and window (Redis).
    auth_rate_limit_per_ip: int = Field(default=30, ge=1)
    auth_rate_limit_window_seconds: int = Field(default=300, ge=1)
    # The refresh cookie's Secure flag: "auto" sets it when the request came over HTTPS.
    auth_cookie_secure: Literal["auto", "true", "false"] = "auto"

    @field_validator("auth_signing_key")
    @classmethod
    def _signing_keys(cls, value: SecretStr) -> SecretStr:
        keys = [key.strip() for key in value.get_secret_value().split(",") if key.strip()]
        if not keys or any(len(key) < 32 for key in keys):
            raise ValueError(
                "AUTH_SIGNING_KEY must hold one or more comma-separated random keys of at "
                "least 32 characters; `make env` generates one into deploy/.env"
            )
        return value

    @property
    def mfa_required_roles(self) -> frozenset[str]:
        return frozenset(r.strip() for r in self.auth_mfa_required_roles.split(",") if r.strip())

    @field_validator("config_backup_schedule")
    @classmethod
    def _cron(cls, value: str) -> str:
        from celery.schedules import crontab

        if len(value.split()) != 5:
            raise ValueError("expected five cron fields: minute hour day month weekday")
        crontab.from_string(value)  # raises ValueError on an invalid field
        return value

    @field_validator("credentials_key")
    @classmethod
    def _valid_fernet_keys(cls, value: SecretStr) -> SecretStr:
        from netops.core.crypto import parse_keys

        parse_keys(value.get_secret_value())
        return value

    @property
    def database_url(self) -> URL:
        """Async SQLAlchemy URL; URL.create escapes special characters in the password."""
        return URL.create(
            drivername="postgresql+asyncpg",
            username=self.postgres_user,
            password=self.postgres_password.get_secret_value(),
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        )


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings, read once on first use."""
    return Settings()

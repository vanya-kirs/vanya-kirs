import logging
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
    )

    # Telethon (optional for local testing without parser)
    API_ID: int = 0
    API_HASH: str = ""
    SESSION_STRING: str = ""

    # Telegram Bot
    BOT_TOKEN: str

    # Database
    DATABASE_URL: str  # postgresql+asyncpg://user:pass@host:5432/dbname

    # Redis
    REDIS_URL: str  # redis://localhost:6379/0

    # Anthropic
    ANTHROPIC_API_KEY: str
    CLAUDE_RATE_LIMIT_WAIT_SECONDS: int = 60
    CLAUDE_BATCH_ITEM_DELAY_SECONDS: float = 0.5

    # Bot
    OWNER_TELEGRAM_ID: int = 0
    API_BASE_URL: str = "http://localhost:8000"
    OWNER_API_EMAIL: str = ""
    OWNER_API_PASSWORD: str = ""

    # Admins (comma-separated telegram IDs, e.g. "123456,789012")
    ADMIN_IDS: str = ""

    @property
    def admin_ids(self) -> list[int]:
        return [int(x.strip()) for x in self.ADMIN_IDS.split(",") if x.strip().isdigit()]

    # JWT
    SECRET_KEY: str = "change-me-in-production-use-openssl-rand-hex-32"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # Scheduler
    PARSE_ALL_SOURCES_EVERY_MINUTES: int = 30  # kept for .env compatibility; no longer used in beat
    PROCESS_JOIN_QUEUE_EVERY_MINUTES: int = 5
    DEFAULT_USER_ID: int = 1  # DB users.id used for beat-scheduled scoring

    # Proxy — optional, format: socks5://user:pass@host:port or socks5://host:port
    PROXY_URL: str = ""

    # Source expansion schedules (cron: "minute hour day_of_month month_of_year day_of_week")
    EXPAND_MIN_MEMBERS: int = 50
    EXPAND_RECOMMENDATIONS_CRON: str = "0 3 * * 1"   # Weekly on Monday at 03:00
    EXPAND_FORWARDS_CRON: str = "0 4 * * *"           # Daily at 04:00
    EXPAND_MENTIONS_CRON: str = "0 5 * * *"           # Daily at 05:00
    EXPAND_SEARCH_CRON: str = "0 15 */3 * *"          # Every 3 days at 15:00
    EXPAND_TGSTAT_CRON: str = "0 6 1 * *"             # Monthly on 1st at 06:00

    @property
    def telethon_proxy(self) -> tuple | None:
        """Parse PROXY_URL into a tuple Telethon understands."""
        if not self.PROXY_URL:
            return None
        try:
            from urllib.parse import urlparse
            p = urlparse(self.PROXY_URL)
            scheme = p.scheme.lower()
            # PySocks/python-socks integer constants: SOCKS4=1, SOCKS5=2, HTTP=3
            if "socks5" in scheme:
                proxy_type = 2
            elif "socks4" in scheme:
                proxy_type = 1
            else:
                proxy_type = 3
            host = p.hostname
            port = p.port or (1080 if proxy_type != 3 else 8080)
            if p.username and p.password:
                return (proxy_type, host, port, True, p.username, p.password)
            return (proxy_type, host, port)
        except Exception as exc:
            logger.warning("Failed to parse PROXY_URL: %s", exc)
            return None


@lru_cache()
def get_settings() -> Settings:
    settings = Settings()
    logger.info("Settings loaded successfully")
    return settings

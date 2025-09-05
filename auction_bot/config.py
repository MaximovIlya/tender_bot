from __future__ import annotations
import os
from dataclasses import dataclass, field
from dotenv import load_dotenv


load_dotenv()


@dataclass
class Settings:
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    ADMIN_IDS: list[int] = field(default_factory=lambda: [
        int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()
    ])
    ORGANIZER_ID: int = int(os.getenv("ORGANIZER_ID", "0"))  # <-- добавил организатора
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./auction.db")
    FILES_DIR: str = os.getenv("FILES_DIR", "./files")


settings = Settings()

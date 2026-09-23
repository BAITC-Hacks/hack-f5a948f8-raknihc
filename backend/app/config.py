import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    db_path: Path = ROOT / "data/private/career-quest.sqlite3"
    as_of_date: date = date(2026, 10, 1)
    cors_origins: tuple[str, ...] = ("http://localhost:5173", "http://127.0.0.1:5173")

    @classmethod
    def from_env(cls):
        return cls(
            db_path=Path(os.getenv("CQ_DB_PATH", str(cls.db_path))).expanduser(),
            as_of_date=date.fromisoformat(os.getenv("CQ_AS_OF_DATE", "2026-10-01")),
            cors_origins=tuple(x.strip() for x in os.getenv(
                "CQ_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
            ).split(",") if x.strip()),
        )

import os
from dataclasses import dataclass


def req(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


@dataclass(frozen=True)
class Settings:
    bot_token: str
    owner_id: int
    required_channel: str
    database_url: str
    webapp_url: str
    port: int
    b2_endpoint: str
    b2_bucket: str
    b2_key_id: str
    b2_application_key: str
    b2_region: str
    max_film_bytes: int = 5 * 1024**3


def load() -> Settings:
    db = req("DATABASE_URL")
    if db.startswith("postgres://"):
        db = "postgresql+asyncpg://" + db[11:]
    elif db.startswith("postgresql://"):
        db = "postgresql+asyncpg://" + db[13:]
    else:
        raise RuntimeError("DATABASE_URL must be PostgreSQL.")
    return Settings(
        bot_token=req("BOT_TOKEN"),
        owner_id=int(req("OWNER_ID")),
        required_channel=req("REQUIRED_CHANNEL"),
        database_url=db,
        webapp_url=req("WEBAPP_URL").rstrip("/"),
        port=int(os.getenv("PORT", "8080")),
        b2_endpoint=req("B2_ENDPOINT").rstrip("/"),
        b2_bucket=req("B2_BUCKET"),
        b2_key_id=req("B2_KEY_ID"),
        b2_application_key=req("B2_APPLICATION_KEY"),
        b2_region=os.getenv("B2_REGION", "us-east-005"),
    )


settings = load()

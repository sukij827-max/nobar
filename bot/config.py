import os
from dataclasses import dataclass
from dotenv import load_dotenv
load_dotenv()

@dataclass(frozen=True)
class Settings:
    bot_token: str
    database_url: str
    owner_id: int
    required_channel: str
    webapp_url: str
    r2_endpoint: str
    r2_bucket: str
    r2_access_key: str
    r2_secret_key: str
    r2_region: str
    port: int

def settings():
    required = [
        'BOT_TOKEN','DATABASE_URL','OWNER_ID','REQUIRED_CHANNEL','WEBAPP_URL',
        'R2_ENDPOINT','R2_BUCKET','R2_ACCESS_KEY_ID','R2_SECRET_ACCESS_KEY'
    ]
    missing = [x for x in required if not os.getenv(x)]
    if missing:
        raise RuntimeError('Missing variables: ' + ', '.join(missing))
    return Settings(
        bot_token=os.environ['BOT_TOKEN'],
        database_url=os.environ['DATABASE_URL'],
        owner_id=int(os.environ['OWNER_ID']),
        required_channel=os.environ['REQUIRED_CHANNEL'],
        webapp_url=os.environ['WEBAPP_URL'].rstrip('/'),
        r2_endpoint=os.environ['R2_ENDPOINT'].rstrip('/'),
        r2_bucket=os.environ['R2_BUCKET'],
        r2_access_key=os.environ['R2_ACCESS_KEY_ID'],
        r2_secret_key=os.environ['R2_SECRET_ACCESS_KEY'],
        r2_region=os.getenv('R2_REGION','auto'),
        port=int(os.getenv('PORT','8000')),
    )

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
    b2_endpoint: str
    b2_bucket: str
    b2_key_id: str
    b2_application_key: str
    b2_region: str
    port: int

def settings():
    required = [
        'BOT_TOKEN','DATABASE_URL','OWNER_ID','REQUIRED_CHANNEL','WEBAPP_URL',
        'B2_ENDPOINT','B2_BUCKET','B2_KEY_ID','B2_APPLICATION_KEY'
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
        b2_endpoint=os.environ['B2_ENDPOINT'].rstrip('/'),
        b2_bucket=os.environ['B2_BUCKET'],
        b2_key_id=os.environ['B2_KEY_ID'],
        b2_application_key=os.environ['B2_APPLICATION_KEY'],
        b2_region=os.getenv('B2_REGION','us-east-005'),
        port=int(os.getenv('PORT','8000')),
    )

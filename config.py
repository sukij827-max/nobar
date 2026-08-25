import os
from dataclasses import dataclass

def req(name):
    value=os.getenv(name,'').strip()
    if not value: raise RuntimeError(f'Missing required environment variable: {name}')
    return value
@dataclass(frozen=True)
class Settings:
    bot_token:str; owner_id:int; required_channel:str; database_url:str; webapp_url:str; port:int
    b2_endpoint:str; b2_bucket:str; b2_key_id:str; b2_application_key:str; b2_region:str

def load():
    db=req('DATABASE_URL')
    if db.startswith('postgres://'): db='postgresql+asyncpg://'+db[11:]
    elif db.startswith('postgresql://'): db='postgresql+asyncpg://'+db[13:]
    else: raise RuntimeError('DATABASE_URL must be PostgreSQL.')
    return Settings(req('BOT_TOKEN'),int(req('OWNER_ID')),req('REQUIRED_CHANNEL'),db,req('WEBAPP_URL').rstrip('/'),int(os.getenv('PORT','8080')),req('B2_ENDPOINT').rstrip('/'),req('B2_BUCKET'),req('B2_KEY_ID'),req('B2_APPLICATION_KEY'),os.getenv('B2_REGION','us-east-005'))
settings=load()

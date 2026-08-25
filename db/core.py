from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import BigInteger, Boolean, DateTime, Float, Integer, String, UniqueConstraint
from config import settings
class Base(DeclarativeBase): pass
class User(Base):
    __tablename__='users'; user_id:Mapped[int]=mapped_column(BigInteger,primary_key=True); username:Mapped[str|None]=mapped_column(String(255)); first_name:Mapped[str|None]=mapped_column(String(255)); created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=lambda:datetime.now(timezone.utc))
class Room(Base):
    __tablename__='rooms'; id:Mapped[int]=mapped_column(Integer,primary_key=True); code:Mapped[str]=mapped_column(String(12),unique=True,index=True); group_chat_id:Mapped[int]=mapped_column(BigInteger,index=True); host_user_id:Mapped[int]=mapped_column(BigInteger); title:Mapped[str]=mapped_column(String(200)); is_active:Mapped[bool]=mapped_column(Boolean,default=True); is_playing:Mapped[bool]=mapped_column(Boolean,default=False); position:Mapped[float]=mapped_column(Float,default=0); updated_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=lambda:datetime.now(timezone.utc)); created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=lambda:datetime.now(timezone.utc))
class Member(Base):
    __tablename__='room_members'; __table_args__=(UniqueConstraint('room_id','user_id'),); id:Mapped[int]=mapped_column(Integer,primary_key=True); room_id:Mapped[int]=mapped_column(Integer,index=True); user_id:Mapped[int]=mapped_column(BigInteger,index=True); joined_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=lambda:datetime.now(timezone.utc))
class Film(Base):
    __tablename__='films'; id:Mapped[int]=mapped_column(Integer,primary_key=True); room_id:Mapped[int]=mapped_column(Integer,index=True); owner_user_id:Mapped[int]=mapped_column(BigInteger); title:Mapped[str]=mapped_column(String(255)); object_key:Mapped[str]=mapped_column(String(500),unique=True); size_bytes:Mapped[int]=mapped_column(BigInteger); mime_type:Mapped[str]=mapped_column(String(120),default='video/mp4'); status:Mapped[str]=mapped_column(String(20),default='ready'); created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=lambda:datetime.now(timezone.utc))
engine=create_async_engine(settings.database_url,pool_pre_ping=True); Session=async_sessionmaker(engine,expire_on_commit=False)
async def init_db():
    async with engine.begin() as c: await c.run_sync(Base.metadata.create_all)
async def close_db(): await engine.dispose()

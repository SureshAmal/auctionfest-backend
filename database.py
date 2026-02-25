from typing import AsyncGenerator
from sqlmodel import SQLModel, create_engine
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    # Fallback for local development if not set, though user should set it
    # Use sqlite for absolute fallback if postgres not available, but user asked for postgres
    DATABASE_URL = "postgresql+asyncpg://postgres:1475@localhost:5432/auctionfest"

# Handle Supabase/Postgres connection string differences if needed (e.g. sslmode)
# asyncpg needs postgresql+asyncpg:// scheme
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

# Handle SSL for cloud providers like Railway/Render
connect_args = {}
if "ssl" in DATABASE_URL or "sslmode" in DATABASE_URL:
    # asyncpg uses 'ssl' argument for SSLContext or bool
    connect_args["ssl"] = True

engine = create_async_engine(
    DATABASE_URL, 
    echo=False, 
    future=True,
    pool_size=50,
    max_overflow=20,
    connect_args=connect_args
)

async def init_db():
    async with engine.begin() as conn:
        # await conn.run_sync(SQLModel.metadata.drop_all) # careful with this
        await conn.run_sync(SQLModel.metadata.create_all)

async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async_session = sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session() as session:
        yield session

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
    DATABASE_URL = "postgresql+asyncpg://postgres:1475@localhost:5432/auctionfest"

# Handle various schemes provided by cloud hosts like Railway/Render
# asyncpg REQUIRES postgresql+asyncpg://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

# Handle SSL context for cloud providers
connect_args = {}
# Check for common SSL indicators in the URL
if any(x in DATABASE_URL.lower() for x in ["ssl", "sslmode", "ssh"]): # Handling 'ssh' typo too
    # Simple boolean True works for most cloud providers like Railway/Supabase
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

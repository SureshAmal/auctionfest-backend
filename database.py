import os
from typing import AsyncGenerator

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel, create_engine
from sqlmodel.ext.asyncio.session import AsyncSession

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    DATABASE_URL = "postgresql+asyncpg://postgres:1475@localhost:5432/auctionfest"

# Handle schemes provided by cloud hosts like Railway/Render
# asyncpg REQUIRES postgresql+asyncpg://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

# Handle SSL context for cloud providers
connect_args = {}
# Most cloud DBs need SSL. We'll enable it if indicators are present in the URL.
if any(x in DATABASE_URL.lower() for x in ["ssl", "sslmode", "ssh"]):
    import ssl

    # Create a context that doesn't verify the certificate (common requirement for self-signed cloud DBs)
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    connect_args["ssl"] = ctx
    print("SSL Context configured (verification disabled).")

    # Strip query parameters from URL to prevent driver from overriding our manual connect_args
    if "?" in DATABASE_URL:
        DATABASE_URL = DATABASE_URL.split("?")[0]

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    future=True,
    pool_size=50,
    max_overflow=20,
    connect_args=connect_args,
)


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
        await _ensure_enum_values(conn)


async def _ensure_enum_values(conn):
    """Ensure all enum values exist in PostgreSQL. Add missing ones."""
    from sqlalchemy import text
    
    enums_to_check = [
        ("plotstatus", ["pending", "active", "sold", "unsold"]),
        ("auctionstatus", ["not_started", "running", "selling", "paused", "completed", "waiting_for_next"]),
    ]
    
    for enum_name, values in enums_to_check:
        for value in values:
            try:
                await conn.execute(
                    text(f"ALTER TYPE {enum_name} ADD VALUE '{value}'")
                )
            except Exception:
                pass


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session

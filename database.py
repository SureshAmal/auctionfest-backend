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
    print("SSL connection enabled (self-signed allowed) for database.")


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

#!/bin/bash
# ==============================================================
# AuctionFest Backend — Docker Entrypoint
# Seeds the database if empty, then starts uvicorn.
# ==============================================================

set -e

echo "=== AuctionFest Backend Starting ==="

# Check if database has data; seed if empty
echo "Checking if database needs seeding..."
python -c "
import asyncio
from database import engine
from sqlmodel import SQLModel, select, text
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy.orm import sessionmaker
from models import Team

async def check_and_seed():
    \"\"\"Check if the database has teams. If not, run seed.\"\"\"
    # Ensure tables exist
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        result = await session.exec(select(Team).limit(1))
        teams = result.all()

    if len(teams) == 0:
        print('Database is empty — running seed...')
        from seed import seed
        await seed()
        print('Seeding complete!')
    else:
        print(f'Database already has data ({len(teams)} team(s) found). Skipping seed.')

    await engine.dispose()

asyncio.run(check_and_seed())
"

echo "Starting uvicorn server..."
exec uvicorn main:app --host 0.0.0.0 --port "${PORT:-8000}" --workers 1 --log-level info

#!/bin/bash
# ==============================================================
# AuctionFest Backend — Docker Entrypoint
# Seeds the database if empty, then starts uvicorn.
# ==============================================================

echo "=== System Info ==="
echo "User: $(whoami)"
echo "Working directory: $(pwd)"
echo "Files in /app:"
ls -F /app

# Check if database has data; seed if empty
echo "Checking database status..."

python -c "
import asyncio
import os
import sys

async def check():
    try:
        from database import engine
        from sqlmodel import SQLModel, select
        from sqlmodel.ext.asyncio.session import AsyncSession
        from sqlalchemy.orm import sessionmaker
        from models import Team

        print('Connecting to database...')
        async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with async_session() as session:
            # Simple query to check if teams exist
            result = await session.exec(select(Team).limit(1))
            teams = result.all()
            
            if len(teams) == 0:
                print('Database is empty. Running seed...')
                from seed import seed
                await seed()
                print('Seeding complete.')
            else:
                print(f'Database has {len(teams)} teams. Skipping seed.')
    except Exception as e:
        print(f'Warning: Database check/seed failed: {e}')
        print('Proceeding to start server anyway...')
    finally:
        try:
            from database import engine
            await engine.dispose()
        except:
            pass

asyncio.run(check())
" || echo "Warning: Startup check exited with error, continuing to uvicorn..."

echo "Starting uvicorn server on port ${PORT:-8000}..."
exec uvicorn main:app --host 0.0.0.0 --port "${PORT:-8000}" --workers 1 --log-level info


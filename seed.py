import asyncio
from database import init_db, get_session, engine
from models import Team, Plot, AuctionState, AuctionStatus, SQLModel
from sqlmodel import select

async def seed():
    # Force reset
    print("Resetting database...")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)
        await conn.run_sync(SQLModel.metadata.create_all)
    
    from sqlalchemy.orm import sessionmaker
    from sqlmodel.ext.asyncio.session import AsyncSession
    
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as session:
        print("Seeding Teams...")
        teams = [
            Team(name=f"Team {chr(65+i)}", passcode=f"pass{i}", budget=1000000)
            for i in range(10)
        ]
        session.add_all(teams)
        
        print("Seeding Plots...")
        plots = [
            Plot(number=i+1, current_bid=None)
            for i in range(12)
        ]
        session.add_all(plots)
        
        print("Seeding Auction State...")
        state = AuctionState(id=1, current_plot_number=1, status=AuctionStatus.NOT_STARTED)
        session.add(state)
        
        await session.commit()
        print("Seeding Complete!")

if __name__ == "__main__":
    asyncio.run(seed())

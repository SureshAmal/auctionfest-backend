import asyncio
import csv
import os
from database import init_db, get_session, engine
from models import Team, Plot, AuctionState, AuctionStatus, SQLModel
from sqlmodel import select

# Path to the CSV file
CSV_FILE = os.path.join(os.path.dirname(__file__), "..", "PLANOMIC PLOT DETAILS (2).csv")

def parse_total_price(price_str: str) -> int:
    """Parse total plot price from CSV string format."""
    try:
        # Remove currency symbol and commas
        cleaned = price_str.strip().replace("₹", "").replace(",", "").strip()
        # Handle cases like "20 000" if any, though replace space might be risky if not needed
        return int(cleaned) if cleaned else 0
    except (ValueError, AttributeError):
        return 0

async def seed():
    """Drop tables, recreate schema, and seed data from CSV."""
    print("Resetting database...")
    async with engine.begin() as conn:
        # Drop all tables to ensure schema changes (added columns) are applied
        await conn.run_sync(SQLModel.metadata.drop_all)
        await conn.run_sync(SQLModel.metadata.create_all)
    
    from sqlalchemy.orm import sessionmaker
    from sqlmodel.ext.asyncio.session import AsyncSession
    
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as session:
        print("Seeding Teams...")
        teams = [
            Team(name=f"Team {chr(65+i)}", passcode=f"pass{i}", budget=10000000)
            for i in range(10)
        ]
        session.add_all(teams)
        
        print(f"Reading plots from: {CSV_FILE}")
        if not os.path.exists(CSV_FILE):
             print(f"WARNING: CSV not found at {CSV_FILE}. Creating dummy plots.")
             plots = [
                Plot(
                    number=i+1, 
                    plot_type="RESIDENTIAL", 
                    base_price=1500, 
                    total_area=1000, 
                    actual_area=1000,
                    total_plot_price=1500000
                )
                for i in range(43)
             ]
        else:
            plots = []
            with open(CSV_FILE, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    plot_no_str = row.get("PLOT NO.", "").strip()
                    if not plot_no_str or not plot_no_str.isdigit():
                        continue
                        
                    plot = Plot(
                        number=int(plot_no_str),
                        plot_type=row.get("PLOT TYPE", "UNKNOWN").strip(),
                        total_area=int(row.get("TOTAL  AREA", "0").strip() or 0),
                        actual_area=int(row.get("ACTUTAL AREA", "0").strip() or 0),
                        base_price=int(row.get("BASE PRICE ", "1500").strip() or 1500),
                        total_plot_price=parse_total_price(row.get("TOTAL PLOT PRICE", "0")),
                        current_bid=None,
                        status="pending" # Default status
                    )
                    plots.append(plot)
            
        print(f"Seeding {len(plots)} plots...")
        session.add_all(plots)
        
        print("Seeding Auction State...")
        state = AuctionState(id=1, current_plot_number=1, status=AuctionStatus.NOT_STARTED)
        session.add(state)
        
        await session.commit()
        print("Seeding Complete!")

if __name__ == "__main__":
    asyncio.run(seed())

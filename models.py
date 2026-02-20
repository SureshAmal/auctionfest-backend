from typing import Optional, List
from datetime import datetime
from sqlmodel import Field, SQLModel, Relationship
from enum import Enum
import uuid
from decimal import Decimal

class PlotStatus(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    SOLD = "sold"

class AuctionStatus(str, Enum):
    NOT_STARTED = "not_started"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    WAITING_FOR_NEXT = "waiting_for_next"

class TeamBase(SQLModel):
    name: str = Field(index=True, unique=True)
    passcode: str # Simple auth
    budget: Decimal = Field(default=Decimal(1000000), decimal_places=2) # Example default
    spent: Decimal = Field(default=Decimal(0), decimal_places=2)
    plots_won: int = Field(default=0)

class Team(TeamBase, table=True):
    id: Optional[uuid.UUID] = Field(default_factory=uuid.uuid4, primary_key=True)
    
    bids: List["Bid"] = Relationship(back_populates="team")
    won_plots: List["Plot"] = Relationship(back_populates="winner_team")

class PlotBase(SQLModel):
    number: int = Field(index=True, unique=True)
    plot_type: str = Field(default="RESIDENTIAL")
    total_area: int = Field(default=0)
    actual_area: int = Field(default=0)
    base_price: int = Field(default=1500)
    total_plot_price: int = Field(default=0)
    status: PlotStatus = Field(default=PlotStatus.PENDING)
    current_bid: Optional[Decimal] = Field(default=None, decimal_places=2)
    round_adjustment: Decimal = Field(default=Decimal(0), decimal_places=2)
    
class Plot(PlotBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    winner_team_id: Optional[uuid.UUID] = Field(default=None, foreign_key="team.id")
    
    winner_team: Optional[Team] = Relationship(back_populates="won_plots")
    bids: List["Bid"] = Relationship(back_populates="plot")

class BidBase(SQLModel):
    amount: Decimal = Field(decimal_places=2)
    timestamp: datetime = Field(default_factory=datetime.utcnow)

class Bid(BidBase, table=True):
    id: Optional[uuid.UUID] = Field(default_factory=uuid.uuid4, primary_key=True)
    team_id: uuid.UUID = Field(foreign_key="team.id")
    plot_id: int = Field(foreign_key="plot.id")
    
    team: Team = Relationship(back_populates="bids")
    plot: Plot = Relationship(back_populates="bids")

class AuctionState(SQLModel, table=True):
    id: int = Field(default=1, primary_key=True)
    current_plot_number: int = Field(default=1)
    status: AuctionStatus = Field(default=AuctionStatus.NOT_STARTED)
    last_updated: datetime = Field(default_factory=datetime.utcnow)

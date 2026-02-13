from fastapi import APIRouter, Depends, HTTPException
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select
from database import get_session
from models import Team, Plot, Bid
from socket_manager import get_connected_count, get_connected_teams
import uuid

router = APIRouter(prefix="/api/data", tags=["data"])

@router.get("/plots")
async def get_plots(session: AsyncSession = Depends(get_session)):
    """Get all plots ordered by number."""
    stmt = select(Plot).order_by(Plot.number)
    result = await session.exec(stmt)
    return result.all()

@router.get("/teams")
async def get_teams(session: AsyncSession = Depends(get_session)):
    """Get all teams ordered by budget descending."""
    stmt = select(Team).order_by(Team.budget.desc())
    result = await session.exec(stmt)
    return result.all()

@router.get("/team/{team_id}")
async def get_team(team_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    """Get a specific team by ID."""
    team = await session.get(Team, team_id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    return team

@router.get("/connected")
async def get_connected():
    """Get the count and names of connected clients."""
    return {
        "count": get_connected_count(),
        "teams": get_connected_teams()
    }


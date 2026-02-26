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

@router.get("/bids/recent")
async def get_recent_bids(session: AsyncSession = Depends(get_session)):
    """Get the most recent 50 bids for the live feed."""
    stmt = (
        select(Bid, Team.name.label("team_name"), Plot.number.label("plot_number"))
        .join(Team, Bid.team_id == Team.id)
        .join(Plot, Bid.plot_id == Plot.id)
        .order_by(Bid.timestamp.desc())
        .limit(50)
    )
    result = await session.exec(stmt)
    
    bids_list = []
    for bid, team_name, plot_number in result:
        bids_list.append({
            "amount": float(bid.amount),
            "team_name": team_name,
            "plot_number": plot_number,
            "timestamp": bid.timestamp.isoformat()
        })
        
    return bids_list

from models import RebidOffer, RebidOfferStatus

@router.get("/rebid-offers")
async def get_active_rebid_offers(session: AsyncSession = Depends(get_session)):
    stmt = select(RebidOffer).where(RebidOffer.status == RebidOfferStatus.ACTIVE).order_by(RebidOffer.timestamp.desc())
    results = await session.exec(stmt)
    return [
        {
            "id": str(offer.id),
            "plot_number": offer.plot_number,
            "offering_team_id": str(offer.offering_team_id),
            "asking_price": float(offer.asking_price),
            "status": offer.status.value,
            "timestamp": offer.timestamp.isoformat()
        } for offer in results.all()
    ]

@router.get("/rebid-offers-sold")
async def get_sold_rebid_offers(session: AsyncSession = Depends(get_session)):
    """Get all sold rebid offers (with buyer info)."""
    stmt = select(RebidOffer).where(RebidOffer.status == RebidOfferStatus.SOLD).order_by(RebidOffer.timestamp.desc())
    results = await session.exec(stmt)
    offers = []
    for offer in results.all():
        # Get offering team name
        offering_stmt = select(Team).where(Team.id == offer.offering_team_id)
        offering_res = await session.exec(offering_stmt)
        offering_team = offering_res.first()
        
        offers.append({
            "id": str(offer.id),
            "plot_number": offer.plot_number,
            "offering_team_id": str(offer.offering_team_id),
            "offering_team_name": offering_team.name if offering_team else "Unknown",
            "asking_price": float(offer.asking_price),
            "status": offer.status.value,
            "timestamp": offer.timestamp.isoformat()
        })
    return offers


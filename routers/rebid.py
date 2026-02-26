from fastapi import APIRouter, Depends, HTTPException
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select
from decimal import Decimal
import uuid
import math

from database import get_session
from models import Plot, Team, RebidOffer, RebidOfferStatus, AuctionState
from socket_manager import sio
from .admin import get_auction_state, serialize # reuse utility function

router = APIRouter(prefix="/api/rebid", tags=["Rebid"])

@router.post("/offer")
async def create_offer(data: dict, session: AsyncSession = Depends(get_session)):
    state = await get_auction_state(session)
    if not state.rebid_phase_active:
        raise HTTPException(status_code=400, detail="Rebid phase is not active.")
        
    team_id_str = data.get("team_id")
    plot_number = data.get("plot_number")
    asking_price = data.get("asking_price")
    
    if not team_id_str or plot_number is None or asking_price is None:
        raise HTTPException(status_code=400, detail="Missing team_id, plot_number, or asking_price.")
        
    # Get team
    try:
        team_stmt = select(Team).where(Team.id == uuid.UUID(team_id_str))
        team = (await session.exec(team_stmt)).first()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid team_id format.")
        
    if not team:
        raise HTTPException(status_code=404, detail="Team not found.")
        
    # Get plot
    plot_stmt = select(Plot).where(Plot.number == plot_number)
    plot = (await session.exec(plot_stmt)).first()
    if not plot:
        raise HTTPException(status_code=404, detail="Plot not found.")
        
    if plot.winner_team_id != team.id:
        raise HTTPException(status_code=403, detail="You do not own this plot.")
        
    # Validation: Price must be between current value and 10% markup
    current_value = float((plot.current_bid or plot.total_plot_price) + plot.round_adjustment)
    max_allowed = current_value * 1.10
    
    if float(asking_price) < current_value:
        raise HTTPException(status_code=400, detail=f"Asking price cannot be below current value (Min: {current_value})")
    if float(asking_price) > max_allowed:
        raise HTTPException(status_code=400, detail=f"Asking price exceeds maximum 10% markup (Max: {max_allowed})")
        
    # Cancel previous active offers for this plot
    existing_stmt = select(RebidOffer).where(RebidOffer.plot_number == plot_number).where(RebidOffer.status == RebidOfferStatus.ACTIVE)
    existing_offers = (await session.exec(existing_stmt)).all()
    for offer in existing_offers:
        offer.status = RebidOfferStatus.CANCELLED
        session.add(offer)

    # Create new offer
    new_offer = RebidOffer(
        plot_number=plot.number,
        offering_team_id=team.id,
        asking_price=Decimal(asking_price),
        status=RebidOfferStatus.ACTIVE
    )
    
    session.add(new_offer)
    await session.commit()
    await session.refresh(new_offer)
    
    # Include team name in the emitted offer data
    offer_data = serialize(new_offer.dict())
    offer_data["team_name"] = team.name
    
    await sio.emit('new_rebid_offer', offer_data, room='auction_room')
    return {"status": "success", "offer": new_offer}

@router.post("/buy")
async def buy_offer(data: dict, session: AsyncSession = Depends(get_session)):
    state = await get_auction_state(session)
    if not state.rebid_phase_active:
        raise HTTPException(status_code=400, detail="Rebid phase is not active.")
        
    buyer_team_id_str = data.get("team_id")
    offer_id_str = data.get("offer_id")
    
    if not buyer_team_id_str or not offer_id_str:
        raise HTTPException(status_code=400, detail="Missing team_id or offer_id.")
        
    # Get buyer team
    try:
        buyer_stmt = select(Team).where(Team.id == uuid.UUID(buyer_team_id_str))
        buyer = (await session.exec(buyer_stmt)).first()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid team_id format.")
        
    if not buyer:
        raise HTTPException(status_code=404, detail="Buyer team not found.")
        
    # Get offer
    try:
        offer_stmt = select(RebidOffer).where(RebidOffer.id == uuid.UUID(offer_id_str))
        offer = (await session.exec(offer_stmt)).first()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid offer_id format.")
    
    if not offer or offer.status != RebidOfferStatus.ACTIVE:
        raise HTTPException(status_code=400, detail="Offer no longer available.")
        
    if offer.offering_team_id == buyer.id:
        raise HTTPException(status_code=400, detail="You cannot buy your own plot.")
        
    buyer_budget = buyer.budget - buyer.spent
    if buyer_budget < offer.asking_price:
        raise HTTPException(status_code=400, detail="Insufficient budget.")
        
    # Execute trade
    offer.status = RebidOfferStatus.SOLD
    
    # Get plot
    plot_stmt = select(Plot).where(Plot.number == offer.plot_number)
    plot = (await session.exec(plot_stmt)).first()
    
    # Get seller
    seller_stmt = select(Team).where(Team.id == offer.offering_team_id)
    seller = (await session.exec(seller_stmt)).first()
    
    # Financial transfer
    buyer.spent += offer.asking_price
    buyer.plots_won += 1
    
    seller.spent -= offer.asking_price
    seller.plots_won = max(0, seller.plots_won - 1)
    
    # Transfer plot ownership
    plot.winner_team_id = buyer.id
    
    # Establish new baseline value for the new owner based on asking price
    plot.current_bid = offer.asking_price
    plot.round_adjustment = Decimal(0)
    
    session.add(offer)
    session.add(buyer)
    session.add(seller)
    session.add(plot)
    await session.commit()
    
    # Include buyer info in the emitted offer data
    offer_data = serialize(offer.dict())
    offer_data["buyer_team_id"] = str(buyer.id)
    offer_data["buyer_name"] = buyer.name
    
    # Emit updates
    await sio.emit('rebid_offer_sold', offer_data, room='auction_room')
    await sio.emit('plot_update', serialize(plot.dict()), room='auction_room')
    
    # Emit team updates
    await sio.emit('team_update', serialize(buyer.dict()), room='auction_room')
    await sio.emit('team_update', serialize(seller.dict()), room='auction_room')
    
    return {"status": "success", "message": "Plot purchased successfully!"}


@router.post("/cancel-offer")
async def cancel_offer(data: dict, session: AsyncSession = Depends(get_session)):
    """Cancel an active sell offer (unsell). Only allowed during sell phase."""
    state = await get_auction_state(session)
    if not state.rebid_phase_active:
        raise HTTPException(status_code=400, detail="Cannot cancel — sell phase is not active.")

    offer_id_str = data.get("offer_id")
    team_id_str = data.get("team_id")

    if not offer_id_str or not team_id_str:
        raise HTTPException(status_code=400, detail="Missing offer_id or team_id.")

    try:
        offer_stmt = select(RebidOffer).where(RebidOffer.id == uuid.UUID(offer_id_str))
        offer = (await session.exec(offer_stmt)).first()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid offer_id format.")

    if not offer or offer.status != RebidOfferStatus.ACTIVE:
        raise HTTPException(status_code=400, detail="Offer not found or already closed.")

    if str(offer.offering_team_id) != team_id_str:
        raise HTTPException(status_code=403, detail="You can only cancel your own offers.")

    offer.status = RebidOfferStatus.CANCELLED
    session.add(offer)
    await session.commit()
    
    # Get team name for the emit
    team_stmt = select(Team).where(Team.id == offer.offering_team_id)
    team_obj = (await session.exec(team_stmt)).first()
    team_name = team_obj.name if team_obj else "Unknown"
    
    cancelled_data = serialize(offer.dict())
    cancelled_data["team_name"] = team_name
    
    await sio.emit('rebid_offer_cancelled', cancelled_data, room='auction_room')
    return {"status": "success", "message": "Offer cancelled."}


@router.get("/offers")
async def get_offers(session: AsyncSession = Depends(get_session)):
    """Get all active rebid offers."""
    stmt = select(RebidOffer).where(RebidOffer.status == RebidOfferStatus.ACTIVE)
    result = await session.exec(stmt)
    offers = result.all()

    enriched = []
    for offer in offers:
        # Get team name
        team_stmt = select(Team).where(Team.id == offer.offering_team_id)
        team = (await session.exec(team_stmt)).first()

        # Get plot info
        plot_stmt = select(Plot).where(Plot.number == offer.plot_number)
        plot = (await session.exec(plot_stmt)).first()

        enriched.append({
            **offer.dict(),
            "team_name": team.name if team else "Unknown",
            "plot_value": float((plot.current_bid or plot.total_plot_price or 0) + (plot.round_adjustment or 0)) if plot else 0
        })

    return serialize(enriched)

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select
from database import get_session
from models import AuctionState, AuctionStatus, Plot, PlotStatus, Team, Bid
from socket_manager import sio, serialize
import logging

router = APIRouter(prefix="/api/admin", tags=["admin"])
logger = logging.getLogger(__name__)

async def get_auction_state(session: AsyncSession) -> AuctionState:
    """Get or create the auction state singleton."""
    stmt = select(AuctionState).where(AuctionState.id == 1)
    result = await session.exec(stmt)
    state = result.first()
    if not state:
        state = AuctionState(id=1, current_plot_number=1, status=AuctionStatus.NOT_STARTED)
        session.add(state)
        await session.commit()
        await session.refresh(state)
    return state

@router.get("/state")
async def get_current_state(session: AsyncSession = Depends(get_session)):
    """Get current auction state and active plot info (for initial page load)."""
    state = await get_auction_state(session)
    
    # Get active plot details
    current_plot = None
    if state.current_plot_number:
        plot_stmt = select(Plot).where(Plot.number == state.current_plot_number)
        plot_res = await session.exec(plot_stmt)
        current_plot = plot_res.first()
    
    return serialize({
        "status": state.status,
        "current_plot_number": state.current_plot_number,
        "current_round": getattr(state, "current_round", 1),
        "current_plot": current_plot.dict() if current_plot else None
    })


@router.post("/start")
async def start_auction(session: AsyncSession = Depends(get_session)):
    state = await get_auction_state(session)
    state.status = AuctionStatus.RUNNING
    
    # Activate current plot
    plot_stmt = select(Plot).where(Plot.number == state.current_plot_number)
    plot_res = await session.exec(plot_stmt)
    plot = plot_res.first()
    
    if plot:
        plot.status = PlotStatus.ACTIVE
        session.add(plot)
    
    session.add(state)
    await session.commit()
    
    await sio.emit('auction_state_update', serialize({
        'status': state.status,
        'current_plot_number': state.current_plot_number,
        'current_round': getattr(state, "current_round", 1),
        'current_plot': plot.dict() if plot else None
    }), room='auction_room')
    return {"status": "started"}

@router.post("/pause")
async def pause_auction(session: AsyncSession = Depends(get_session)):
    state = await get_auction_state(session)
    state.status = AuctionStatus.PAUSED
    session.add(state)
    await session.commit()
    
    await sio.emit('auction_state_update', serialize({
        'status': state.status,
        'current_plot_number': state.current_plot_number,
        'current_round': getattr(state, "current_round", 1)
    }), room='auction_room')
    return {"status": "paused"}

@router.post("/sell")
async def sell_plot(session: AsyncSession = Depends(get_session)):
    """Initiate the selling countdown for the current plot."""
    state = await get_auction_state(session)
    
    if state.status != AuctionStatus.RUNNING:
        return {"status": "error", "detail": "Auction must be running to sell."}
        
    state.status = AuctionStatus.SELLING
    session.add(state)
    await session.commit()
    
    # Broadcast selling state so frontends start countdown
    current_plot_stmt = select(Plot).where(Plot.number == state.current_plot_number)
    current_plot_res = await session.exec(current_plot_stmt)
    current_plot = current_plot_res.first()
    
    await sio.emit('auction_state_update', serialize({
        'status': state.status,
        'current_plot_number': state.current_plot_number,
        'current_round': getattr(state, "current_round", 1),
        'current_plot': current_plot.dict() if current_plot else None
    }), room='auction_room')
    
    return {"status": "selling"}

@router.post("/next")
async def next_plot(session: AsyncSession = Depends(get_session)):
    state = await get_auction_state(session)
    
    # Close current plot
    current_plot_stmt = select(Plot).where(Plot.number == state.current_plot_number)
    current_plot_res = await session.exec(current_plot_stmt)
    current_plot = current_plot_res.first()
    
    if current_plot:
        current_plot.status = PlotStatus.SOLD
        
        # Deduct budget from winner if any
        if current_plot.winner_team_id and current_plot.current_bid:
             team_stmt = select(Team).where(Team.id == current_plot.winner_team_id)
             team_res = await session.exec(team_stmt)
             team = team_res.first()
             if team:
                 team.spent += current_plot.current_bid
                 team.plots_won += 1
                 session.add(team)
        
        session.add(current_plot)
    
    # Move to next
    state.current_plot_number += 1
    state.status = AuctionStatus.RUNNING
    
    # Activate next plot
    next_plot_stmt = select(Plot).where(Plot.number == state.current_plot_number)
    next_plot_res = await session.exec(next_plot_stmt)
    next_plot = next_plot_res.first()
    
    if next_plot:
        next_plot.status = PlotStatus.ACTIVE
        session.add(next_plot)
    else:
        state.status = AuctionStatus.COMPLETED
    
    session.add(state)
    await session.commit()
    
    await sio.emit('auction_state_update', serialize({
        'status': state.status,
        'current_plot_number': state.current_plot_number,
        'current_round': getattr(state, "current_round", 1),
        'current_plot': next_plot.dict() if next_plot else None
    }), room='auction_room')
    
    return {"status": "advanced", "new_plot": state.current_plot_number}

@router.post("/prev")
async def prev_plot(session: AsyncSession = Depends(get_session)):
    state = await get_auction_state(session)
    
    # Can't go back from plot 1
    if state.current_plot_number <= 1:
        return {"status": "error", "detail": "Already at the first plot"}
        
    # Reset current plot to pending
    current_plot_stmt = select(Plot).where(Plot.number == state.current_plot_number)
    current_plot_res = await session.exec(current_plot_stmt)
    current_plot = current_plot_res.first()
    
    if current_plot:
        current_plot.status = PlotStatus.PENDING
        # Optionally, we could clear its current_bid here, but usually going back implies keeping the bid or resetting it.
        # We'll keep the bids in the DB, just reset its status so it can be re-bid or just viewed.
        session.add(current_plot)
        
    # Go back to previous plot
    state.current_plot_number -= 1
    state.status = AuctionStatus.RUNNING
    
    # Get previous plot (the one we are returning to)
    prev_plot_stmt = select(Plot).where(Plot.number == state.current_plot_number)
    prev_plot_res = await session.exec(prev_plot_stmt)
    prev_plot = prev_plot_res.first()
    
    if prev_plot:
        # If it was sold, we need to refund the team
        if prev_plot.status == PlotStatus.SOLD and prev_plot.winner_team_id and prev_plot.current_bid:
             team_stmt = select(Team).where(Team.id == prev_plot.winner_team_id)
             team_res = await session.exec(team_stmt)
             team = team_res.first()
             if team:
                 # Refund the spent amount and decrement plots won
                 team.spent = max(0, team.spent - prev_plot.current_bid)
                 team.plots_won = max(0, team.plots_won - 1)
                 session.add(team)
                 
                 # Broadcast the refund to the specific team so their UI updates
                 await sio.emit('team_update', serialize({
                     'team_id': team.id,
                     'spent': float(team.spent),
                     'budget': float(team.budget)
                 }), room='auction_room')
                 
        # Reactivate the previous plot
        prev_plot.status = PlotStatus.ACTIVE
        session.add(prev_plot)
        
    session.add(state)
    await session.commit()
    
    await sio.emit('auction_state_update', serialize({
        'status': state.status,
        'current_plot_number': state.current_plot_number,
        'current_round': getattr(state, "current_round", 1),
        'current_plot': prev_plot.dict() if prev_plot else None
    }), room='auction_room')
    
    return {"status": "reversed", "new_plot": state.current_plot_number}


@router.post("/set-round")
async def set_round(data: dict, session: AsyncSession = Depends(get_session)):
    round_num = data.get("round", 1)
    state = await get_auction_state(session)
    
    # Store round in state or just emit it
    # Since we need to persist it, let's update state if it has the column
    if hasattr(state, "current_round"):
        state.current_round = round_num
        session.add(state)
        await session.commit()
        
    await sio.emit('round_change', {'current_round': round_num}, room='auction_room')
    return {"status": "success", "round": round_num}

@router.post("/reset")
async def reset_auction(session: AsyncSession = Depends(get_session)):
    """HARD RESET"""
    # 1. Reset State
    state = await get_auction_state(session)
    state.current_plot_number = 1
    state.status = AuctionStatus.NOT_STARTED
    session.add(state)
    
    # 2. Delete Bids
    # Using explicit fetch and delete to ensure ORM consistency
    from sqlmodel import delete
    # await session.exec(delete(Bid)) # Potential issue here, switching to execute
    await session.execute(delete(Bid))
    
    # 3. Reset Plots
    plots_stmt = select(Plot)
    plots_res = await session.exec(plots_stmt)
    plots = plots_res.all()
    for p in plots:
        p.status = PlotStatus.PENDING
        p.current_bid = None
        p.winner_team_id = None
        session.add(p)
        
    # 4. Reset Teams
    teams_stmt = select(Team)
    teams_res = await session.exec(teams_stmt)
    teams = teams_res.all()
    for t in teams:
        t.spent = 0
        t.plots_won = 0
        session.add(t)
        
    await session.commit()
    
    await sio.emit('auction_reset', {}, room='auction_room')
    return {"status": "reset_complete"}

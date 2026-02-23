from fastapi import APIRouter, Depends, HTTPException
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select
from database import get_session
from models import AuctionState, AuctionStatus, Plot, PlotStatus, Team, Bid
from socket_manager import sio, serialize
from pydantic import BaseModel
import logging
import os
import asyncio
from fastapi import BackgroundTasks

router = APIRouter(prefix="/api/admin", tags=["admin"])
logger = logging.getLogger(__name__)

# Admin password from environment variable, with a secure fallback
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "aufest2026")


class AdminLoginRequest(BaseModel):
    """Request body for admin password verification."""
    password: str


@router.post("/verify")
async def verify_admin(req: AdminLoginRequest):
    """Verify the admin password. Returns success or raises 401."""
    if req.password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="Invalid admin password")
    return {"status": "ok", "message": "Admin access granted"}

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

async def auto_advance_plot(current_plot_number: int):
    """Background task to wait 4 seconds and then advance the plot."""
    await asyncio.sleep(4)
    # Get a fresh session since the request one is closed
    from database import engine
    from sqlalchemy.orm import sessionmaker
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as session:
        state = await get_auction_state(session)
        # Only advance if we are still on the plot we started selling
        # and the auction wasn't reset/paused in the meantime
        if state.status == AuctionStatus.SELLING and state.current_plot_number == current_plot_number:
            # Replicate next_plot logic
            current_plot_stmt = select(Plot).where(Plot.number == state.current_plot_number)
            current_plot_res = await session.exec(current_plot_stmt)
            current_plot = current_plot_res.first()
            
            if current_plot:
                current_plot.status = PlotStatus.SOLD
                
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

@router.post("/sell")
async def sell_plot(background_tasks: BackgroundTasks, session: AsyncSession = Depends(get_session)):
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
    
    # Schedule auto-advance
    background_tasks.add_task(auto_advance_plot, state.current_plot_number)
    
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
                 
                 # Broadcast the team update so their UI and Leaderboard updates
                 await sio.emit('team_update', serialize({
                     'team_id': team.id,
                     'spent': float(team.spent),
                     'budget': float(team.budget),
                     'plots_won': team.plots_won
                 }), room='auction_room')
        
        session.add(current_plot)
        await sio.emit('plot_update', serialize(current_plot), room='auction_room')
    
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

@router.post("/rebid/toggle")
async def toggle_rebid(data: dict, session: AsyncSession = Depends(get_session)):
    is_active = data.get("is_active", False)
    state = await get_auction_state(session)
    
    state.rebid_phase_active = is_active
    session.add(state)
    await session.commit()
    
    await sio.emit('rebid_phase_update', {'is_active': is_active}, room='auction_room')
    return {"status": "success", "rebid_phase_active": is_active}

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

import csv
CSV_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "planomics-policy-cards.csv")

def read_policy_cards() -> list[dict]:
    cards = []
    if os.path.exists(CSV_FILE):
        with open(CSV_FILE, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                cards.append({
                    "round_id": int(row.get("round_id", 0)),
                    "question_id": int(row.get("question_id", 0)),
                    "policy_description": row.get("policy_description", "").strip()
                })
    return cards

@router.get("/questions/{round_id}")
async def get_questions(round_id: int):
    all_cards = read_policy_cards()
    return [c for c in all_cards if c["round_id"] == round_id]

class PushQuestionRequest(BaseModel):
    policy_description: str

@router.post("/push-question")
async def push_question(req: PushQuestionRequest, session: AsyncSession = Depends(get_session)):
    state = await get_auction_state(session)
    state.current_question = req.policy_description
    session.add(state)
    await session.commit()
    
    await sio.emit('active_question', {"question": req.policy_description}, room='auction_room')
    return {"status": "pushed"}

from models import AdjustmentHistory
from decimal import Decimal
import uuid

class AdjustPlotRequest(BaseModel):
    plot_numbers: list[int]
    adjustment_percent: float

@router.post("/adjust-plot")
async def adjust_plot(req: AdjustPlotRequest, session: AsyncSession = Depends(get_session)):
    if not req.plot_numbers:
        raise HTTPException(status_code=400, detail="No plots provided")
        
    plots_stmt = select(Plot).where(Plot.number.in_(req.plot_numbers))
    plots_res = await session.exec(plots_stmt)
    plots = plots_res.all()
    
    if not plots:
        raise HTTPException(status_code=404, detail="No matching plots found")
        
    transaction_id = str(uuid.uuid4())
    adjustments = []
    
    for plot in plots:
        base_price_decimal = Decimal(plot.current_bid) if plot.current_bid else Decimal(plot.total_plot_price)
        adjustment_val = base_price_decimal * Decimal(req.adjustment_percent) / Decimal(100)
        
        old_adj = plot.round_adjustment
        new_adj = old_adj + adjustment_val
        
        history = AdjustmentHistory(
            transaction_id=transaction_id,
            plot_number=plot.number,
            old_round_adjustment=old_adj,
            new_round_adjustment=new_adj
        )
        session.add(history)
        
        plot.round_adjustment = new_adj
        session.add(plot)
        
        adjustments.append({
            "plot_number": plot.number,
            "round_adjustment": float(new_adj)
        })
        
    await session.commit()
    
    for adj in adjustments:
        await sio.emit('plot_adjustment', {"plot_number": adj["plot_number"], "plot": adj}, room='auction_room')
        
    return {"status": "success", "transaction_id": transaction_id, "results": adjustments}

@router.post("/undo-adjustment")
async def undo_adjustment(session: AsyncSession = Depends(get_session)):
    # Find newest transaction
    stmt = select(AdjustmentHistory).order_by(AdjustmentHistory.timestamp.desc()).limit(1)
    res = await session.exec(stmt)
    latest = res.first()
    
    if not latest:
        return {"status": "error", "message": "No recent adjustments found"}
        
    tid = latest.transaction_id
    
    hist_stmt = select(AdjustmentHistory).where(AdjustmentHistory.transaction_id == tid)
    hist_res = await session.exec(hist_stmt)
    history_records = hist_res.all()
    
    reverted_plots = []
    for record in history_records:
        plot_stmt = select(Plot).where(Plot.number == record.plot_number)
        plot_res = await session.exec(plot_stmt)
        plot = plot_res.first()
        
        if plot:
            plot.round_adjustment = record.old_round_adjustment
            session.add(plot)
            reverted_plots.append({
                "plot_number": plot.number,
                "round_adjustment": float(plot.round_adjustment)
            })
            
        await session.delete(record)
        
    await session.commit()
    
    for plot in reverted_plots:
        await sio.emit('plot_adjustment', {"plot_number": plot["plot_number"], "plot": plot}, room='auction_room')
        
    return {"status": "success", "message": f"Reverted transaction {tid}", "reverted_plots": reverted_plots}


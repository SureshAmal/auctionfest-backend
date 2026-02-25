from fastapi import APIRouter, Depends, HTTPException
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select
from database import get_session
from models import AuctionState, AuctionStatus, Plot, PlotStatus, Team, Bid, RebidOffer, RebidOfferStatus, AdjustmentHistory
from socket_manager import sio, serialize
from pydantic import BaseModel
import logging
import os
import asyncio
import json
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
        "current_plot": current_plot.dict() if current_plot else None,
        "current_question": state.current_question,
        "current_policy_deltas": json.loads(state.current_policy_deltas) if state.current_policy_deltas else {},
        "rebid_phase_active": getattr(state, "rebid_phase_active", False),
        "round4_phase": state.round4_phase,
        "round4_bid_queue": json.loads(state.round4_bid_queue) if state.round4_bid_queue else [],
        "theme_config": json.loads(getattr(state, "theme_config", "{}")) if getattr(state, "theme_config", None) else {},
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
    """Background task to wait 6 seconds and then advance the plot."""
    await asyncio.sleep(6)
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
                         
                         await sio.emit('team_update', serialize({
                             'team_id': team.id,
                             'spent': float(team.spent),
                             'budget': float(team.budget),
                             'plots_won': team.plots_won
                         }), room='auction_room')
                
                session.add(current_plot)
                await sio.emit('plot_update', serialize(current_plot.dict()), room='auction_room')
            
            # Determine next plot number
            next_plot_number = None

            if state.round4_phase == "bid" and state.round4_bid_queue:
                import json
                # Round 4 bid phase: advance through the bid queue
                bid_queue = json.loads(state.round4_bid_queue)
                try:
                    current_idx = bid_queue.index(state.current_plot_number)
                    if current_idx + 1 < len(bid_queue):
                        next_plot_number = bid_queue[current_idx + 1]
                except ValueError:
                    pass
            else:
                next_plot_number = state.current_plot_number + 1
            
            state.status = AuctionStatus.RUNNING
            
            next_plot_obj = None
            if next_plot_number:
                state.current_plot_number = next_plot_number
                next_plot_stmt = select(Plot).where(Plot.number == next_plot_number)
                next_plot_res = await session.exec(next_plot_stmt)
                next_plot_obj = next_plot_res.first()
            
            if next_plot_obj:
                next_plot_obj.status = PlotStatus.ACTIVE
                session.add(next_plot_obj)
            else:
                state.status = AuctionStatus.PAUSED
            
            session.add(state)
            await session.commit()
            
            await sio.emit('auction_state_update', serialize({
                'status': state.status,
                'current_plot_number': state.current_plot_number,
                'current_round': getattr(state, "current_round", 1),
                'current_plot': next_plot_obj.dict() if next_plot_obj else None
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
    """Advance to the next plot. In Round 4 bid phase, follows the bid queue."""
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
        await sio.emit('plot_update', serialize(current_plot.dict()), room='auction_room')
    
    # Determine next plot number
    next_plot_number = None

    if state.round4_phase == "bid" and state.round4_bid_queue:
        # Round 4 bid phase: advance through the bid queue
        bid_queue = json.loads(state.round4_bid_queue)
        try:
            current_idx = bid_queue.index(state.current_plot_number)
            if current_idx + 1 < len(bid_queue):
                next_plot_number = bid_queue[current_idx + 1]
        except ValueError:
            # Current plot not in queue; shouldn't happen but handle gracefully
            pass
    else:
        # Normal sequential advancement
        next_plot_number = state.current_plot_number + 1

    state.status = AuctionStatus.RUNNING
    
    # Activate next plot
    next_plot_obj = None
    if next_plot_number:
        state.current_plot_number = next_plot_number
        next_plot_stmt = select(Plot).where(Plot.number == next_plot_number)
        next_plot_res = await session.exec(next_plot_stmt)
        next_plot_obj = next_plot_res.first()
    
    if next_plot_obj:
        next_plot_obj.status = PlotStatus.ACTIVE
        session.add(next_plot_obj)
    else:
        # Round is done — pause. Only admin's /end-game triggers COMPLETED.
        state.status = AuctionStatus.PAUSED
    
    session.add(state)
    await session.commit()
    
    await sio.emit('auction_state_update', serialize({
        'status': state.status,
        'current_plot_number': state.current_plot_number,
        'current_round': getattr(state, "current_round", 1),
        'current_plot': next_plot_obj.dict() if next_plot_obj else None
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
    """HARD RESET - Clears all auction data back to initial state."""
    from sqlmodel import delete
    
    # 1. Reset Auction State
    state = await get_auction_state(session)
    state.current_plot_number = 1
    state.status = AuctionStatus.NOT_STARTED
    state.current_round = 1
    state.current_question = None
    state.current_policy_deltas = None
    state.round4_phase = None
    state.round4_bid_queue = None
    state.rebid_phase_active = False
    session.add(state)
    
    # 2. Delete all Bids
    await session.execute(delete(Bid))
    
    # 3. Delete all Rebid Offers
    await session.execute(delete(RebidOffer))
    
    # 4. Delete all Adjustment History
    await session.execute(delete(AdjustmentHistory))
    
    # 5. Reset all Plots
    plots_stmt = select(Plot)
    plots_res = await session.exec(plots_stmt)
    all_plots = plots_res.all()
    for p in all_plots:
        p.status = PlotStatus.PENDING
        p.current_bid = None
        p.winner_team_id = None
        p.round_adjustment = 0
        session.add(p)
    
    # 6. Reset all Teams
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
    """Push a new policy question and clear previous policy deltas."""
    state = await get_auction_state(session)
    state.current_question = req.policy_description
    state.current_policy_deltas = None  # Clear deltas for new policy
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
            "round_adjustment": float(new_adj),
            "old_adjustment": float(old_adj)
        })
        
    await session.commit()
    
    # Persist current policy deltas to DB
    state = await get_auction_state(session)
    existing_deltas = json.loads(state.current_policy_deltas) if state.current_policy_deltas else {}
    for adj in adjustments:
        plot_num_str = str(adj["plot_number"])
        old_val = float(existing_deltas.get(plot_num_str, 0))
        # Compute the delta for this plot in this adjustment
        delta = float(adj["round_adjustment"]) - float(adj.get("old_adjustment", 0))
        existing_deltas[plot_num_str] = old_val + delta
    state.current_policy_deltas = json.dumps(existing_deltas)
    session.add(state)
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


@router.post("/start-round4-sell")
async def start_round4_sell(session: AsyncSession = Depends(get_session)):
    """Start Round 4 sell phase — teams can list plots for sale."""
    state = await get_auction_state(session)
    state.round4_phase = "sell"
    state.rebid_phase_active = True
    state.round4_bid_queue = None
    session.add(state)
    await session.commit()

    await sio.emit('round4_phase_update', {'phase': 'sell'}, room='auction_room')
    await sio.emit('rebid_phase_update', {'is_active': True}, room='auction_room')
    return {"status": "success", "phase": "sell"}


@router.post("/start-round4-bidding")
async def start_round4_bidding(session: AsyncSession = Depends(get_session)):
    """End sell phase, collect unsold listed plots, and start bidding on them."""
    state = await get_auction_state(session)

    # Close the sell marketplace
    state.rebid_phase_active = False
    state.round4_phase = "bid"

    # Find all ACTIVE (unsold) rebid offers — these go to auction
    active_stmt = select(RebidOffer).where(RebidOffer.status == RebidOfferStatus.ACTIVE)
    active_res = await session.exec(active_stmt)
    unsold_offers = active_res.all()

    # Mark them as cancelled (they'll now be auctioned normally instead)
    bid_queue = []
    for offer in unsold_offers:
        bid_queue.append(offer.plot_number)
        # Reset the plot so it can be auctioned fresh
        plot_stmt = select(Plot).where(Plot.number == offer.plot_number)
        plot_res = await session.exec(plot_stmt)
        plot = plot_res.first()
        if plot:
            # The selling team gets their money back (plot is no longer theirs for bidding)
            seller_stmt = select(Team).where(Team.id == offer.offering_team_id)
            seller_res = await session.exec(seller_stmt)
            seller = seller_res.first()
            if seller:
                seller.spent -= plot.current_bid or Decimal(0)
                seller.plots_won = max(0, seller.plots_won - 1)
                session.add(seller)
                await sio.emit('team_update', serialize({
                    'team_id': seller.id,
                    'spent': float(seller.spent),
                    'budget': float(seller.budget),
                    'plots_won': seller.plots_won
                }), room='auction_room')

            # Reset plot for fresh auction starting at the asking price
            plot.status = PlotStatus.PENDING
            plot.total_plot_price = float(offer.asking_price)
            plot.round_adjustment = 0
            plot.current_bid = None
            plot.winner_team_id = None
            session.add(plot)
            await sio.emit('plot_update', serialize(plot.dict()), room='auction_room')

            # Clear old bid history so the feed doesn't show Round 1 bids
            from models import Bid
            bid_stmt = select(Bid).where(Bid.plot_id == plot.id)
            old_bids = (await session.exec(bid_stmt)).all()
            for b in old_bids:
                await session.delete(b)

        offer.status = RebidOfferStatus.CANCELLED
        session.add(offer)

    # Sort and store the bid queue
    bid_queue.sort()
    state.round4_bid_queue = json.dumps(bid_queue)

    if bid_queue:
        # Set first plot in queue as active
        state.current_plot_number = bid_queue[0]
        state.status = AuctionStatus.RUNNING

        first_plot_stmt = select(Plot).where(Plot.number == bid_queue[0])
        first_plot_res = await session.exec(first_plot_stmt)
        first_plot = first_plot_res.first()
        if first_plot:
            first_plot.status = PlotStatus.ACTIVE
            session.add(first_plot)
    else:
        state.status = AuctionStatus.PAUSED

    session.add(state)
    await session.commit()

    await sio.emit('round4_phase_update', {'phase': 'bid', 'bid_queue': bid_queue}, room='auction_room')

    # Send state update so everyone sees the new plot
    current_plot = None
    if bid_queue:
        cp_stmt = select(Plot).where(Plot.number == bid_queue[0])
        cp_res = await session.exec(cp_stmt)
        current_plot = cp_res.first()

    await sio.emit('auction_state_update', serialize({
        'status': state.status,
        'current_plot': current_plot.dict() if current_plot else None,
        'current_plot_number': state.current_plot_number
    }), room='auction_room')

    return {"status": "success", "phase": "bid", "bid_queue": bid_queue}


@router.post("/end-game")
async def end_game(session: AsyncSession = Depends(get_session)):
    """End the game after Round 6 — sets status to completed."""
    state = await get_auction_state(session)
    state.status = AuctionStatus.COMPLETED
    state.round4_phase = None
    state.rebid_phase_active = False
    session.add(state)
    await session.commit()

    await sio.emit('auction_state_update', serialize({
        'status': 'completed',
        'current_plot': None,
        'current_plot_number': state.current_plot_number
    }), room='auction_room')
    return {"status": "game_ended"}

class ThemeUpdatePayload(BaseModel):
    variables: dict

@router.post("/theme")
async def update_theme(payload: ThemeUpdatePayload, session: AsyncSession = Depends(get_session)):
    """Save the global theme variables and broadcast them to all clients."""
    state = await get_auction_state(session)
    
    # Store theme as JSON string in the database
    state.theme_config = json.dumps(payload.variables)
    session.add(state)
    await session.commit()
    
    # Broadcast to all connected clients
    await sio.emit('theme_update', payload.variables, room='auction_room')
    
    return {"status": "success", "message": "Theme updated and broadcasted globally"}

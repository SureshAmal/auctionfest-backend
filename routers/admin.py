import asyncio
import json
import logging
import os
from decimal import Decimal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import select, or_
from sqlmodel.ext.asyncio.session import AsyncSession

from database import get_session
from models import (
    AdjustmentHistory,
    AuctionState,
    AuctionStatus,
    Bid,
    GameSnapshot,
    Plot,
    PlotStatus,
    RebidOffer,
    RebidOfferStatus,
    Team,
)
from socket_manager import serialize, sio

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
        state = AuctionState(
            id=1, current_plot_number=1, status=AuctionStatus.NOT_STARTED
        )
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

    return serialize(
        {
            "status": state.status,
            "current_plot_number": state.current_plot_number,
            "current_round": getattr(state, "current_round", 1),
            "current_plot": current_plot.dict() if current_plot else None,
            "current_question": state.current_question,
            "current_policy_deltas": json.loads(state.current_policy_deltas)
            if state.current_policy_deltas
            else {},
            "rebid_phase_active": getattr(state, "rebid_phase_active", False),
            "round4_phase": state.round4_phase,
            "round4_bid_queue": json.loads(state.round4_bid_queue)
            if state.round4_bid_queue
            else [],
            "theme_config": json.loads(getattr(state, "theme_config", "{}"))
            if getattr(state, "theme_config", None)
            else {},
            "admin_forced_theme": getattr(state, "admin_forced_theme", False),
        }
    )


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

    await sio.emit(
        "auction_state_update",
        serialize(
            {
                "status": state.status,
                "current_plot_number": state.current_plot_number,
                "current_round": getattr(state, "current_round", 1),
                "current_plot": plot.dict() if plot else None,
            }
        ),
        room="auction_room",
    )
    return {"status": "started"}


@router.post("/pause")
async def pause_auction(session: AsyncSession = Depends(get_session)):
    state = await get_auction_state(session)
    state.status = AuctionStatus.PAUSED
    session.add(state)
    await session.commit()

    await sio.emit(
        "auction_state_update",
        serialize(
            {
                "status": state.status,
                "current_plot_number": state.current_plot_number,
                "current_round": getattr(state, "current_round", 1),
            }
        ),
        room="auction_room",
    )
    return {"status": "paused"}

async def auto_save_game_state(session: AsyncSession, label: str):
    """Automatically save a game snapshot with the given label."""
    import json
    
    state = await get_auction_state(session)
    teams = (await session.exec(select(Team))).all()
    plots = (await session.exec(select(Plot))).all()
    bids = (await session.exec(select(Bid))).all()
    offers = (await session.exec(select(RebidOffer))).all()

    snapshot = {
        "auction_state": {
            "current_plot_number": state.current_plot_number,
            "status": state.status,
            "current_round": state.current_round,
            "current_question": state.current_question,
            "rebid_phase_active": state.rebid_phase_active,
            "round4_phase": state.round4_phase,
            "round4_bid_queue": state.round4_bid_queue,
            "current_policy_deltas": state.current_policy_deltas,
        },
        "teams": [
            {
                "id": str(t.id),
                "name": t.name,
                "passcode": t.passcode,
                "budget": float(t.budget),
                "spent": float(t.spent),
                "plots_won": t.plots_won,
                "is_banned": t.is_banned,
            }
            for t in teams
        ],
        "plots": [
            {
                "id": p.id,
                "number": p.number,
                "plot_type": p.plot_type,
                "total_area": p.total_area,
                "actual_area": p.actual_area,
                "base_price": p.base_price,
                "total_plot_price": p.total_plot_price,
                "status": p.status,
                "current_bid": float(p.current_bid) if p.current_bid else None,
                "round_adjustment": float(p.round_adjustment),
                "purchase_price": float(p.purchase_price) if p.purchase_price else None,
                "winner_team_id": str(p.winner_team_id) if p.winner_team_id else None,
            }
            for p in plots
        ],
        "bids": [
            {
                "id": str(b.id),
                "amount": float(b.amount),
                "team_id": str(b.team_id),
                "plot_id": b.plot_id,
                "timestamp": b.timestamp.isoformat(),
            }
            for b in bids
        ],
        "rebid_offers": [
            {
                "id": str(o.id),
                "plot_number": o.plot_number,
                "offering_team_id": str(o.offering_team_id),
                "asking_price": float(o.asking_price),
                "status": o.status,
                "timestamp": o.timestamp.isoformat(),
            }
            for o in offers
        ],
    }

    game_snapshot = GameSnapshot(
        label=label,
        snapshot_data=json.dumps(snapshot),
    )
    session.add(game_snapshot)
    await session.commit()
    return game_snapshot

async def auto_advance_plot(current_plot_number: int):
    """Background task to wait 6 seconds and then advance the plot."""
    await asyncio.sleep(5)
    # Get a fresh session since the request one is closed
    from sqlalchemy.orm import sessionmaker

    from database import engine

    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        state = await get_auction_state(session)
        # Only advance if we are still on the plot we started selling
        # and the auction wasn't reset/paused in the meantime
        if (
            state.status == AuctionStatus.SELLING
            and state.current_plot_number == current_plot_number
        ):
            # Replicate next_plot logic
            current_plot_stmt = select(Plot).where(
                Plot.number == state.current_plot_number
            )
            current_plot_res = await session.exec(current_plot_stmt)
            current_plot = current_plot_res.first()

            if current_plot:
                current_plot.status = (
                    PlotStatus.SOLD
                    if current_plot.winner_team_id
                    else PlotStatus.UNSOLD
                )

                seller_offer = None
                if state.round4_phase == "bid":
                    seller_offer_stmt = (
                        select(RebidOffer)
                        .where(
                            RebidOffer.plot_number == current_plot.number,
                            RebidOffer.status == RebidOfferStatus.CANCELLED,
                        )
                        .order_by(RebidOffer.timestamp.desc())
                    )
                    seller_offer = (await session.exec(seller_offer_stmt)).first()

                is_unsold_rebid = (
                    seller_offer
                    and current_plot.winner_team_id == seller_offer.offering_team_id
                )

                if is_unsold_rebid:
                    # Nobody outbid the seller. They keep their plot.
                    # Revert the current_bid back to what it was before the round started!
                    if current_plot.purchase_price is not None:
                        current_plot.current_bid = current_plot.purchase_price
                elif current_plot.winner_team_id and current_plot.current_bid:
                    team_stmt = select(Team).where(
                        Team.id == current_plot.winner_team_id
                    )
                    team = (await session.exec(team_stmt)).first()
                    if team:
                        team.spent += current_plot.current_bid
                        team.plots_won += 1
                        session.add(team)
                        await sio.emit(
                            "team_update",
                            serialize(
                                {
                                    "team_id": team.id,
                                    "spent": float(team.spent),
                                    "budget": float(team.budget),
                                    "plots_won": team.plots_won,
                                }
                            ),
                            room="auction_room",
                        )

                    if seller_offer:
                        # Credit the original seller with the buyer's bid price
                        seller_stmt = select(Team).where(
                            Team.id == seller_offer.offering_team_id
                        )
                        seller = (await session.exec(seller_stmt)).first()
                        if seller:
                            seller.spent -= current_plot.current_bid
                            seller.plots_won = max(0, seller.plots_won - 1)
                            session.add(seller)
                            await sio.emit(
                                "team_update",
                                serialize(
                                    {
                                        "team_id": seller.id,
                                        "spent": float(seller.spent),
                                        "budget": float(seller.budget),
                                        "plots_won": seller.plots_won,
                                    }
                                ),
                                room="auction_room",
                            )

                        seller_offer.status = RebidOfferStatus.SOLD
                        session.add(seller_offer)
                        offer_data = serialize(seller_offer.dict())
                        offer_data["buyer_team_id"] = str(team.id) if team else None
                        offer_data["buyer_name"] = team.name if team else "Unknown"
                        await sio.emit(
                            "rebid_offer_sold", offer_data, room="auction_room"
                        )

                session.add(current_plot)
                await sio.emit(
                    "plot_update", serialize(current_plot.dict()), room="auction_room"
                )
                
                if current_plot.status == PlotStatus.SOLD:
                    await sio.emit("plot_sold_summary", {
                        "plotNumber": current_plot.number,
                        "teamId": str(current_plot.winner_team_id) if current_plot.winner_team_id else None,
                        "price": float(current_plot.current_bid or current_plot.total_plot_price)
                    }, room="auction_room")

            # Perform Auto-Save
            label = f"Round {state.current_round} - Plot {current_plot.number} Sold"
            if current_plot.status == PlotStatus.UNSOLD:
                label = f"Round {state.current_round} - Plot {current_plot.number} Unsold"
            await auto_save_game_state(session, label)

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

            if not next_plot_number:
                # Normal sequential advancement: skip plots that are already won
                curr = state.current_plot_number
                while True:
                    curr += 1
                    check_stmt = select(Plot).where(Plot.number == curr)
                    check_plot = (await session.exec(check_stmt)).first()
                    if not check_plot:
                        break  # We reached the end
                    if not check_plot.winner_team_id:
                        next_plot_number = curr
                        break

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

            await sio.emit(
                "auction_state_update",
                serialize(
                    {
                        "status": state.status,
                        "current_plot_number": state.current_plot_number,
                        "current_round": getattr(state, "current_round", 1),
                        "current_plot": next_plot_obj.dict() if next_plot_obj else None,
                    }
                ),
                room="auction_room",
            )


@router.post("/sell")
async def sell_plot(
    background_tasks: BackgroundTasks, session: AsyncSession = Depends(get_session)
):
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

    await sio.emit(
        "auction_state_update",
        serialize(
            {
                "status": state.status,
                "current_plot_number": state.current_plot_number,
                "current_round": getattr(state, "current_round", 1),
                "current_plot": current_plot.dict() if current_plot else None,
            }
        ),
        room="auction_room",
    )

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
        current_plot.status = (
            PlotStatus.SOLD if current_plot.winner_team_id else PlotStatus.UNSOLD
        )

        seller_offer = None
        if state.round4_phase == "bid":
            seller_offer_stmt = (
                select(RebidOffer)
                .where(
                    RebidOffer.plot_number == current_plot.number,
                    RebidOffer.status == RebidOfferStatus.CANCELLED,
                )
                .order_by(RebidOffer.timestamp.desc())
            )
            seller_offer = (await session.exec(seller_offer_stmt)).first()

        is_unsold_rebid = (
            seller_offer
            and current_plot.winner_team_id == seller_offer.offering_team_id
        )

        if is_unsold_rebid:
            # Nobody outbid the seller. They keep their plot.
            # Revert the current_bid back to its original true value
            if current_plot.purchase_price is not None:
                current_plot.current_bid = current_plot.purchase_price
        elif current_plot.winner_team_id and current_plot.current_bid:
            team_stmt = select(Team).where(Team.id == current_plot.winner_team_id)
            team = (await session.exec(team_stmt)).first()
            if team:
                team.spent += current_plot.current_bid
                team.plots_won += 1
                session.add(team)
                await sio.emit(
                    "team_update",
                    serialize(
                        {
                            "team_id": team.id,
                            "spent": float(team.spent),
                            "budget": float(team.budget),
                            "plots_won": team.plots_won,
                        }
                    ),
                    room="auction_room",
                )

            if seller_offer:
                # Credit the original seller with the buyer's bid price
                seller_stmt = select(Team).where(
                    Team.id == seller_offer.offering_team_id
                )
                seller = (await session.exec(seller_stmt)).first()
                if seller:
                    seller.spent -= current_plot.current_bid
                    seller.plots_won = max(0, seller.plots_won - 1)
                    session.add(seller)
                    await sio.emit(
                        "team_update",
                        serialize(
                            {
                                "team_id": seller.id,
                                "spent": float(seller.spent),
                                "budget": float(seller.budget),
                                "plots_won": seller.plots_won,
                            }
                        ),
                        room="auction_room",
                    )

                seller_offer.status = RebidOfferStatus.SOLD
                session.add(seller_offer)
                offer_data = serialize(seller_offer.dict())
                offer_data["buyer_team_id"] = str(team.id) if team else None
                offer_data["buyer_name"] = team.name if team else "Unknown"
                await sio.emit("rebid_offer_sold", offer_data, room="auction_room")

        session.add(current_plot)
        await sio.emit(
            "plot_update", serialize(current_plot.dict()), room="auction_room"
        )
        
        if current_plot.status == PlotStatus.SOLD:
            await sio.emit("plot_sold_summary", {
                "plotNumber": current_plot.number,
                "teamId": str(current_plot.winner_team_id) if current_plot.winner_team_id else None,
                "price": float(current_plot.current_bid or current_plot.total_plot_price)
            }, room="auction_room")

        # Perform Auto-Save for explicit 'Next' action
        label = f"Round {state.current_round} - Plot {current_plot.number} Sold"
        if current_plot.status == PlotStatus.UNSOLD:
            label = f"Round {state.current_round} - Plot {current_plot.number} Unsold"
        # Append 'Manual' to easily distinguish it
        label += " (Manual Advance)"
        await auto_save_game_state(session, label)

    # Determine next plot number
    next_plot_number = None

    is_round4_end = False

    if state.round4_phase == "bid" and state.round4_bid_queue:
        # Round 4 bid phase: advance through the bid queue
        bid_queue = json.loads(state.round4_bid_queue)
        try:
            current_idx = bid_queue.index(state.current_plot_number)
            if current_idx + 1 < len(bid_queue):
                next_plot_number = bid_queue[current_idx + 1]
            else:
                is_round4_end = True
        except ValueError:
            # Current plot not in queue; shouldn't happen but handle gracefully
            pass

    if not next_plot_number and not is_round4_end:
        # Normal sequential advancement: skip plots that are already won by someone
        curr = state.current_plot_number
        while True:
            curr += 1
            check_stmt = select(Plot).where(Plot.number == curr)
            check_plot = (await session.exec(check_stmt)).first()
            if not check_plot:
                break  # We reached the end
            if not check_plot.winner_team_id:
                next_plot_number = curr
                break

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

    await sio.emit(
        "auction_state_update",
        serialize(
            {
                "status": state.status,
                "current_plot_number": state.current_plot_number,
                "current_round": getattr(state, "current_round", 1),
                "current_plot": next_plot_obj.dict() if next_plot_obj else None,
            }
        ),
        room="auction_room",
    )

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
        if (
            prev_plot.status == PlotStatus.SOLD
            and prev_plot.winner_team_id
            and prev_plot.current_bid
        ):
            team_stmt = select(Team).where(Team.id == prev_plot.winner_team_id)
            team_res = await session.exec(team_stmt)
            team = team_res.first()
            if team:
                # Refund the spent amount and decrement plots won
                team.spent = max(0, team.spent - prev_plot.current_bid)
                team.plots_won = max(0, team.plots_won - 1)
                session.add(team)

                # Broadcast the refund to the specific team so their UI updates
                await sio.emit(
                    "team_update",
                    serialize(
                        {
                            "team_id": team.id,
                            "spent": float(team.spent),
                            "budget": float(team.budget),
                        }
                    ),
                    room="auction_room",
                )

        # Reactivate the previous plot
        prev_plot.status = PlotStatus.ACTIVE
        session.add(prev_plot)

    session.add(state)
    await session.commit()

    await sio.emit(
        "auction_state_update",
        serialize(
            {
                "status": state.status,
                "current_plot_number": state.current_plot_number,
                "current_round": getattr(state, "current_round", 1),
                "current_plot": prev_plot.dict() if prev_plot else None,
            }
        ),
        room="auction_room",
    )

    return {"status": "reversed", "new_plot": state.current_plot_number}


@router.post("/set-round")
async def set_round(data: dict, session: AsyncSession = Depends(get_session)):
    round_num = data.get("round", 1)
    state = await get_auction_state(session)

    # Store round in state or just emit it
    # Since we need to persist it, let's update state if it has the column
    if hasattr(state, "current_round"):
        state.current_round = round_num

        if round_num == 4:
            state.round4_phase = "sell"
            state.rebid_phase_active = True
            state.round4_bid_queue = None

        session.add(state)
        await session.commit()

    await sio.emit("round_change", {"current_round": round_num}, room="auction_room")

    if round_num == 4:
        await sio.emit("round4_phase_update", {"phase": "sell"}, room="auction_room")
        await sio.emit("rebid_phase_update", {"is_active": True}, room="auction_room")

    return {"status": "success", "round": round_num}


@router.post("/force-resell/{plot_number}")
async def force_resell(plot_number: int, session: AsyncSession = Depends(get_session)):
    """Admin tool to force a sold plot into the Round 4 resell pool."""
    state = await get_auction_state(session)
    
    # Needs to be a valid plot
    plot_stmt = select(Plot).where(Plot.number == plot_number)
    plot_res = await session.exec(plot_stmt)
    plot = plot_res.first()
    
    if not plot:
        return {"status": "error", "message": "Plot not found"}

    # If it was sold, we need to refund the team
    if plot.winner_team_id:
        team_stmt = select(Team).where(Team.id == plot.winner_team_id)
        team_res = await session.exec(team_stmt)
        team = team_res.first()
        if team:
            # Refund the spent amount and decrement plots won
            if plot.current_bid:
                team.spent = max(0, float(team.spent) - float(plot.current_bid))
            elif plot.total_plot_price:
                team.spent = max(0, float(team.spent) - float(plot.total_plot_price))
            
            team.plots_won = max(0, team.plots_won - 1)
            session.add(team)

            # Broadcast the refund to the specific team so their UI updates
            await sio.emit(
                "team_update",
                serialize(
                    {
                        "team_id": team.id,
                        "spent": float(team.spent),
                        "budget": float(team.budget),
                        "plots_won": team.plots_won,
                    }
                ),
                room="auction_room",
            )
    
    # Reset plot cleanly
    plot.status = PlotStatus.UNSOLD
    plot.winner_team_id = None
    plot.current_bid = None
    plot.round_adjustment = 0
    plot.purchase_price = None
    if plot.base_price and plot.actual_area:
        plot.total_plot_price = float(plot.base_price * plot.actual_area)
    session.add(plot)

    from models import Bid
    bid_stmt = select(Bid).where(Bid.plot_id == plot.id)
    old_bids = (await session.exec(bid_stmt)).all()
    for b in old_bids:
        await session.delete(b)

    # Force inject into active Round 4 run if currently in `bid` phase
    if getattr(state, "current_round", 1) == 4 and getattr(state, "round4_phase", None) == "bid" and getattr(state, "round4_bid_queue", None):
        bid_queue = json.loads(state.round4_bid_queue)
        if plot.number not in bid_queue:
            bid_queue.append(plot.number)
            bid_queue.sort()
            state.round4_bid_queue = json.dumps(bid_queue)
            session.add(state)
            
            await sio.emit(
                "round4_phase_update",
                {"phase": "bid", "bid_queue": bid_queue},
                room="auction_room",
            )
            
            # Since it's in the queue, label it pending so it acts normally when next comes around.
            plot.status = PlotStatus.PENDING
            session.add(plot)

    await session.commit()

    await sio.emit(
        "plot_update", serialize(plot.dict()), room="auction_room"
    )

    return {"status": "success", "message": f"Plot {plot_number} forced to resell queue."}


@router.post("/rebid/toggle")
async def toggle_rebid(data: dict, session: AsyncSession = Depends(get_session)):
    is_active = data.get("is_active", False)
    state = await get_auction_state(session)

    state.rebid_phase_active = is_active
    session.add(state)
    await session.commit()

    await sio.emit("rebid_phase_update", {"is_active": is_active}, room="auction_room")
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

    await sio.emit("auction_reset", {}, room="auction_room")
    return {"status": "reset_complete"}


from models import PolicyCard


@router.get("/questions/{round_id}")
async def get_questions(round_id: int, session: AsyncSession = Depends(get_session)):
    stmt = select(PolicyCard).where(PolicyCard.round_id == round_id)
    res = await session.exec(stmt)
    cards = res.all()
    return [
        {
            "round_id": c.round_id,
            "question_id": c.question_id,
            "policy_description": c.policy_description,
        }
        for c in cards
    ]


class PushQuestionRequest(BaseModel):
    policy_description: str


@router.post("/push-question")
async def push_question(
    req: PushQuestionRequest, session: AsyncSession = Depends(get_session)
):
    """Push a new policy question and clear previous policy deltas."""
    state = await get_auction_state(session)
    state.current_question = req.policy_description
    state.current_policy_deltas = None  # Clear deltas for new policy
    session.add(state)
    await session.commit()

    await sio.emit(
        "active_question", {"question": req.policy_description}, room="auction_room"
    )
    return {"status": "pushed"}


import uuid
from decimal import Decimal

from models import AdjustmentHistory


class AdjustPlotRequest(BaseModel):
    plot_numbers: list[int]
    adjustment_percent: float


@router.post("/adjust-plot")
async def adjust_plot(
    req: AdjustPlotRequest, session: AsyncSession = Depends(get_session)
):
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
        base_price_decimal = (
            Decimal(plot.current_bid)
            if plot.current_bid
            else Decimal(plot.total_plot_price)
        )
        adjustment_val = (
            base_price_decimal * Decimal(req.adjustment_percent) / Decimal(100)
        )

        old_adj = plot.round_adjustment
        new_adj = old_adj + adjustment_val

        history = AdjustmentHistory(
            transaction_id=transaction_id,
            plot_number=plot.number,
            old_round_adjustment=old_adj,
            new_round_adjustment=new_adj,
        )
        session.add(history)

        plot.round_adjustment = new_adj
        session.add(plot)

        adjustments.append(
            {
                "plot_number": plot.number,
                "round_adjustment": float(new_adj),
                "old_adjustment": float(old_adj),
            }
        )

    await session.commit()

    # Persist current policy deltas to DB
    state = await get_auction_state(session)
    existing_deltas = (
        json.loads(state.current_policy_deltas) if state.current_policy_deltas else {}
    )
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
        await sio.emit(
            "plot_adjustment",
            {"plot_number": adj["plot_number"], "plot": adj},
            room="auction_room",
        )

    label = f"Round {state.current_round} - Adjustment Applied"
    if state.current_question:
        # Find the matching PolicyCard to use P1, P2 format
        from models import PolicyCard
        card_stmt = select(PolicyCard).where(
            PolicyCard.round_id == state.current_round,
            PolicyCard.policy_description == state.current_question
        )
        card = (await session.exec(card_stmt)).first()
        
        if card:
            label += f" (P{card.question_id})"
        else:
            # Fallback if card is somehow not found
            q_summary = state.current_question[:30] + ("..." if len(state.current_question) > 30 else "")
            label += f" ({q_summary})"
    
    await auto_save_game_state(session, label)

    return {
        "status": "success",
        "transaction_id": transaction_id,
        "results": adjustments,
    }


@router.post("/undo-adjustment")
async def undo_adjustment(session: AsyncSession = Depends(get_session)):
    # Find newest transaction
    stmt = (
        select(AdjustmentHistory).order_by(AdjustmentHistory.timestamp.desc()).limit(1)
    )
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
            reverted_plots.append(
                {
                    "plot_number": plot.number,
                    "round_adjustment": float(plot.round_adjustment),
                }
            )

        await session.delete(record)

    await session.commit()

    for plot in reverted_plots:
        await sio.emit(
            "plot_adjustment",
            {"plot_number": plot["plot_number"], "plot": plot},
            room="auction_room",
        )

    return {
        "status": "success",
        "message": f"Reverted transaction {tid}",
        "reverted_plots": reverted_plots,
    }


@router.post("/start-round4-sell")
async def start_round4_sell(session: AsyncSession = Depends(get_session)):
    """Start Round 4 sell phase — teams can list plots for sale."""
    state = await get_auction_state(session)
    state.round4_phase = "sell"
    state.rebid_phase_active = True
    state.round4_bid_queue = None
    session.add(state)
    await session.commit()

    await sio.emit("round4_phase_update", {"phase": "sell"}, room="auction_room")
    await sio.emit("rebid_phase_update", {"is_active": True}, room="auction_room")
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

    # Find all completely unsold plots from Round 1 (no winner OR status is unsold or pending)
    unsold_plots_stmt = select(Plot).where(
        or_(
            Plot.winner_team_id == None, 
            Plot.status == PlotStatus.UNSOLD,
            Plot.status == PlotStatus.PENDING
        )
    )
    unsold_plots_res = await session.exec(unsold_plots_stmt)
    unsold_round1_plots = unsold_plots_res.all()

    unsold_queue = []
    rebid_queue = []

    # Add unsold round 1 plots to unsold queue
    for plot in unsold_round1_plots:
        if plot.number not in unsold_queue:
            unsold_queue.append(plot.number)
            plot.status = PlotStatus.PENDING
            plot.winner_team_id = None
            plot.current_bid = None
            session.add(plot)

    # Mark rebid offers as cancelled and add to rebid queue
    for offer in unsold_offers:
        if offer.plot_number not in unsold_queue and offer.plot_number not in rebid_queue:
            rebid_queue.append(offer.plot_number)

        plot_stmt = select(Plot).where(Plot.number == offer.plot_number)
        plot_res = await session.exec(plot_stmt)
        plot = plot_res.first()
        if plot:
            # DO NOT deduct ownership or plots_won here.
            # Let the seller retain the plot until it is outbid.
            plot.status = PlotStatus.PENDING
            
            # Backup the true original value to purchase_price so we can restore it if unsold
            if plot.current_bid is not None:
                plot.purchase_price = plot.current_bid
            else:
                plot.purchase_price = plot.total_plot_price + plot.round_adjustment
            
            # Set the floor to the team's asking price
            plot.current_bid = offer.asking_price
            
            session.add(plot)
            await sio.emit("plot_update", serialize(plot.dict()), room="auction_room")

            # Clear old bid history so the feed doesn't show Round 1 bids
            from models import Bid

            bid_stmt = select(Bid).where(Bid.plot_id == plot.id)
            old_bids = (await session.exec(bid_stmt)).all()
            for b in old_bids:
                await session.delete(b)

        offer.status = RebidOfferStatus.CANCELLED
        session.add(offer)

    # Sort queues independently and combine: selling plots first, then unsold
    rebid_queue.sort()
    unsold_queue.sort()
    bid_queue = rebid_queue + unsold_queue
    
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

    await sio.emit(
        "round4_phase_update",
        {"phase": "bid", "bid_queue": bid_queue},
        room="auction_room",
    )

    # Send state update so everyone sees the new plot
    current_plot = None
    if bid_queue:
        cp_stmt = select(Plot).where(Plot.number == bid_queue[0])
        cp_res = await session.exec(cp_stmt)
        current_plot = cp_res.first()

    await sio.emit(
        "auction_state_update",
        serialize(
            {
                "status": state.status,
                "current_plot": current_plot.dict() if current_plot else None,
                "current_plot_number": state.current_plot_number,
            }
        ),
        room="auction_room",
    )

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

    await sio.emit(
        "auction_state_update",
        serialize(
            {
                "status": "completed",
                "current_plot": None,
                "current_plot_number": state.current_plot_number,
            }
        ),
        room="auction_room",
    )
    return {"status": "game_ended"}


class ThemeUpdatePayload(BaseModel):
    variables: dict
    is_forced: bool = True  # Default to forced (admin broadcast)


@router.post("/theme")
async def update_theme(
    payload: ThemeUpdatePayload, session: AsyncSession = Depends(get_session)
):
    """Save the global theme variables and broadcast them to all clients."""
    state = await get_auction_state(session)

    # Store theme as JSON string in the database
    state.theme_config = json.dumps(payload.variables)
    state.admin_forced_theme = payload.is_forced
    session.add(state)
    await session.commit()

    # Broadcast to all connected clients with forced flag
    await sio.emit("theme_update", {"config": payload.variables, "is_forced": payload.is_forced}, room="auction_room")

    return {"status": "success", "message": "Theme updated and broadcasted globally"}


@router.post("/theme/reset")
async def reset_theme(session: AsyncSession = Depends(get_session)):
    """Reset the admin-forced theme, allowing users to use their local theme."""
    state = await get_auction_state(session)

    state.admin_forced_theme = False
    session.add(state)
    await session.commit()

    # Notify clients to reset to their local theme
    await sio.emit("theme_update", {"config": {}, "is_forced": False}, room="auction_room")

    return {"status": "success", "message": "Theme reset - users can now use their local theme"}


@router.post("/teams/{team_id}/toggle-ban")
async def toggle_team_ban(
    team_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    """Toggle the ban status of a team."""
    stmt = select(Team).where(Team.id == team_id)
    res = await session.exec(stmt)
    team = res.first()

    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    # Toggle the status
    team.is_banned = not getattr(team, "is_banned", False)
    session.add(team)
    await session.commit()

    # If we are banning them, we must forcefully kick their active socket
    if team.is_banned:
        from socket_manager import kick_banned_team

        await kick_banned_team(team.id)

    return {"status": "success", "team_id": team.id, "is_banned": team.is_banned}


@router.post("/teams/{team_id}/disconnect")
async def disconnect_team(
    team_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    """Force disconnect a connected team's socket session.

    This does NOT ban the team — they can reconnect freely.
    It simply drops their current WebSocket connection.
    """
    stmt = select(Team).where(Team.id == team_id)
    res = await session.exec(stmt)
    team = res.first()

    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    from socket_manager import force_disconnect_team

    was_connected = await force_disconnect_team(team.id)

    if not was_connected:
        return {
            "status": "not_connected",
            "message": f"Team '{team.name}' was not connected.",
        }

    return {
        "status": "success",
        "message": f"Team '{team.name}' has been disconnected.",
    }


class SaveStateRequest(BaseModel):
    """Request body for saving game state."""

    label: str = ""


@router.post("/save-state")
async def save_game_state(
    req: SaveStateRequest, session: AsyncSession = Depends(get_session)
):
    """Save a full snapshot of the current game state."""
    # Gather all data
    state = await get_auction_state(session)
    teams = (await session.exec(select(Team))).all()
    plots = (await session.exec(select(Plot))).all()
    bids = (await session.exec(select(Bid))).all()
    offers = (await session.exec(select(RebidOffer))).all()

    snapshot = {
        "auction_state": {
            "current_plot_number": state.current_plot_number,
            "status": state.status,
            "current_round": state.current_round,
            "current_question": state.current_question,
            "rebid_phase_active": state.rebid_phase_active,
            "round4_phase": state.round4_phase,
            "round4_bid_queue": state.round4_bid_queue,
            "current_policy_deltas": state.current_policy_deltas,
        },
        "teams": [
            {
                "id": str(t.id),
                "name": t.name,
                "passcode": t.passcode,
                "budget": float(t.budget),
                "spent": float(t.spent),
                "plots_won": t.plots_won,
                "is_banned": t.is_banned,
            }
            for t in teams
        ],
        "plots": [
            {
                "id": p.id,
                "number": p.number,
                "plot_type": p.plot_type,
                "total_area": p.total_area,
                "actual_area": p.actual_area,
                "base_price": p.base_price,
                "total_plot_price": p.total_plot_price,
                "status": p.status,
                "current_bid": float(p.current_bid) if p.current_bid else None,
                "round_adjustment": float(p.round_adjustment),
                "purchase_price": float(p.purchase_price) if p.purchase_price else None,
                "winner_team_id": str(p.winner_team_id) if p.winner_team_id else None,
            }
            for p in plots
        ],
        "bids": [
            {
                "id": str(b.id),
                "amount": float(b.amount),
                "team_id": str(b.team_id),
                "plot_id": b.plot_id,
                "timestamp": b.timestamp.isoformat(),
            }
            for b in bids
        ],
        "rebid_offers": [
            {
                "id": str(o.id),
                "plot_number": o.plot_number,
                "offering_team_id": str(o.offering_team_id),
                "asking_price": float(o.asking_price),
                "status": o.status,
                "timestamp": o.timestamp.isoformat(),
            }
            for o in offers
        ],
    }

    label = req.label or f"Round {state.current_round} - Plot {state.current_plot_number}"
    game_snapshot = GameSnapshot(
        label=label,
        snapshot_data=json.dumps(snapshot),
    )
    session.add(game_snapshot)
    await session.commit()
    await session.refresh(game_snapshot)

    return {
        "status": "success",
        "snapshot_id": game_snapshot.id,
        "label": game_snapshot.label,
    }


@router.get("/saved-states")
async def list_saved_states(session: AsyncSession = Depends(get_session)):
    """List all saved game snapshots (without the full data blob)."""
    stmt = select(GameSnapshot).order_by(GameSnapshot.created_at.desc())
    results = (await session.exec(stmt)).all()
    return [
        {
            "id": s.id,
            "label": s.label,
            "created_at": s.created_at.isoformat(),
        }
        for s in results
    ]


@router.post("/restore-state/{snapshot_id}")
async def restore_game_state(
    snapshot_id: int, session: AsyncSession = Depends(get_session)
):
    """Restore the game to a previously saved snapshot.

    This wipes all current bids, rebid offers, then restores teams,
    plots, and auction state from the snapshot.
    """
    stmt = select(GameSnapshot).where(GameSnapshot.id == snapshot_id)
    snap = (await session.exec(stmt)).first()
    if not snap:
        raise HTTPException(status_code=404, detail="Snapshot not found")

    data = json.loads(snap.snapshot_data)

    # 1. Delete current bids and rebid offers
    all_bids = (await session.exec(select(Bid))).all()
    for b in all_bids:
        await session.delete(b)
    all_offers = (await session.exec(select(RebidOffer))).all()
    for o in all_offers:
        await session.delete(o)

    # 2. Restore teams
    for t_data in data["teams"]:
        t_stmt = select(Team).where(Team.id == t_data["id"])
        team = (await session.exec(t_stmt)).first()
        if team:
            team.spent = Decimal(str(t_data["spent"]))
            team.plots_won = t_data["plots_won"]
            team.is_banned = t_data.get("is_banned", False)
            session.add(team)

    # 3. Restore plots
    for p_data in data["plots"]:
        p_stmt = select(Plot).where(Plot.number == p_data["number"])
        plot = (await session.exec(p_stmt)).first()
        if plot:
            plot.status = p_data["status"]
            plot.current_bid = Decimal(str(p_data["current_bid"])) if p_data["current_bid"] else None
            plot.round_adjustment = Decimal(str(p_data["round_adjustment"]))
            plot.purchase_price = Decimal(str(p_data["purchase_price"])) if p_data.get("purchase_price") else None
            plot.winner_team_id = p_data["winner_team_id"]
            plot.total_plot_price = p_data["total_plot_price"]
            session.add(plot)

    # 4. Restore bids
    from datetime import datetime as dt

    for b_data in data.get("bids", []):
        bid = Bid(
            id=b_data["id"],
            amount=Decimal(str(b_data["amount"])),
            team_id=b_data["team_id"],
            plot_id=b_data["plot_id"],
            timestamp=dt.fromisoformat(b_data["timestamp"]),
        )
        session.add(bid)

    # 5. Restore rebid offers
    for o_data in data.get("rebid_offers", []):
        offer = RebidOffer(
            id=o_data["id"],
            plot_number=o_data["plot_number"],
            offering_team_id=o_data["offering_team_id"],
            asking_price=Decimal(str(o_data["asking_price"])),
            status=o_data["status"],
            timestamp=dt.fromisoformat(o_data["timestamp"]),
        )
        session.add(offer)

    # 6. Restore auction state
    state = await get_auction_state(session)
    s_data = data["auction_state"]
    state.current_plot_number = s_data["current_plot_number"]
    state.status = s_data["status"]
    state.current_round = s_data["current_round"]
    state.current_question = s_data.get("current_question")
    state.rebid_phase_active = s_data.get("rebid_phase_active", False)
    state.round4_phase = s_data.get("round4_phase")
    state.round4_bid_queue = s_data.get("round4_bid_queue")
    state.current_policy_deltas = s_data.get("current_policy_deltas")
    session.add(state)

    await session.commit()

    # Broadcast full refresh to all clients
    current_plot = None
    cp_stmt = select(Plot).where(Plot.number == state.current_plot_number)
    cp_res = await session.exec(cp_stmt)
    current_plot = cp_res.first()

    await sio.emit(
        "auction_state_update",
        serialize(
            {
                "status": state.status,
                "current_plot_number": state.current_plot_number,
                "current_round": state.current_round,
                "current_plot": current_plot.dict() if current_plot else None,
            }
        ),
        room="auction_room",
    )

    # Broadcast team updates
    restored_teams = (await session.exec(select(Team))).all()
    for team in restored_teams:
        await sio.emit(
            "team_update",
            serialize(
                {
                    "team_id": team.id,
                    "spent": float(team.spent),
                    "budget": float(team.budget),
                    "plots_won": team.plots_won,
                }
            ),
            room="auction_room",
        )

    return {"status": "success", "message": f"Restored to snapshot: {snap.label}"}


@router.delete("/saved-states/{snapshot_id}")
async def delete_saved_state(
    snapshot_id: int, session: AsyncSession = Depends(get_session)
):
    """Delete a saved game snapshot."""
    stmt = select(GameSnapshot).where(GameSnapshot.id == snapshot_id)
    snap = (await session.exec(stmt)).first()
    if not snap:
        raise HTTPException(status_code=404, detail="Snapshot not found")

    await session.delete(snap)
    await session.commit()
    return {"status": "success", "message": "Snapshot deleted"}

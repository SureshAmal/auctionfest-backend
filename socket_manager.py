import socketio
import asyncio
from typing import Any
from models import Team, Plot, Bid, AuctionState, PlotStatus, AuctionStatus
from database import get_session, engine
from sqlmodel import select
from sqlalchemy.orm import selectinload
import logging
from datetime import datetime
import uuid
from decimal import Decimal

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

sio = socketio.AsyncServer(
    async_mode='asgi',
    cors_allowed_origins='*',
    ping_timeout=25,
    ping_interval=10
)

# ---------------------------------------------------------------------------
# PRESENCE TRACKING — keyed by team_id / role, NOT socket SID
# ---------------------------------------------------------------------------
# Maps team_id -> {sid, team_name} for teams
# Maps role_sid -> {sid, role} for admin / spectator (they don't have team_id)
# The key design: on disconnect, we only remove a team if the disconnecting
# SID is still the CURRENT SID for that team. If the user refreshed, the new
# SID replaced the old one already, so the old disconnect is a no-op.
# ---------------------------------------------------------------------------
_team_presence: dict[str, dict] = {}       # team_id -> {sid, team_name}
_other_clients: dict[str, dict] = {}       # sid -> {role, team_name} for admin/spectator
_sid_to_team: dict[str, str] = {}          # sid -> team_id (reverse lookup)


def get_connected_count() -> int:
    """Return total number of connected clients (teams + admin + spectators)."""
    return len(_team_presence) + len(_other_clients)


def get_connected_teams() -> list[str]:
    """Return list of connected team names."""
    names = [info['team_name'] for info in _team_presence.values() if info.get('team_name')]
    names += [info.get('team_name', info['role'].capitalize()) for info in _other_clients.values()]
    return names


async def broadcast_connection_count():
    """Broadcast updated connection count and team list to all clients in auction_room."""
    try:
        await sio.emit('connection_count', {
            'count': get_connected_count(),
            'teams': get_connected_teams()
        }, room='auction_room')
    except Exception as e:
        logger.error(f"Error broadcasting connection count: {e}")


def serialize(data):
    """Recursively serialize data for Socket.IO emission."""
    if isinstance(data, list):
        return [serialize(item) for item in data]
    if isinstance(data, dict):
        return {key: serialize(value) for key, value in data.items()}
    if isinstance(data, uuid.UUID):
        return str(data)
    if isinstance(data, Decimal):
        return float(data)
    if isinstance(data, datetime):
        return data.isoformat()
    return data


# ---------------------------------------------------------------------------
# SOCKET EVENTS
# ---------------------------------------------------------------------------

@sio.event
async def connect(sid, environ):
    """Handle new client connection. Keep this minimal — no emits."""
    logger.info(f"Client connected: {sid}")


@sio.event
async def disconnect(sid):
    """Handle disconnect. Only remove presence if this SID is still the active one for the team."""
    logger.info(f"Client disconnected: {sid}")

    team_id = _sid_to_team.pop(sid, None)

    if team_id:
        current_info = _team_presence.get(team_id)
        if current_info and current_info.get('sid') == sid:
            # This SID is still the active one — the team truly disconnected.
            _team_presence.pop(team_id, None)
            logger.info(f"Team {team_id} ({current_info.get('team_name')}) is now offline.")
            await broadcast_connection_count()
        else:
            # A newer SID already replaced this one (page refresh). Do nothing.
            logger.info(f"Stale disconnect for team {team_id} (sid {sid}). Current sid is {current_info.get('sid') if current_info else 'none'}. Ignoring.")
    else:
        # Non-team client (admin/spectator)
        removed = _other_clients.pop(sid, None)
        if removed:
            logger.info(f"Non-team client disconnected: {removed.get('role')}")
            await broadcast_connection_count()


@sio.event
async def leave_auction(sid):
    """Explicit leave — always removes presence regardless of SID freshness."""
    logger.info(f"Client leaving explicitly: {sid}")

    team_id = _sid_to_team.pop(sid, None)
    if team_id:
        _team_presence.pop(team_id, None)
    else:
        _other_clients.pop(sid, None)

    await broadcast_connection_count()


@sio.event
async def join_auction(sid, data):
    """
    Register presence for a team or role.

    For teams: tracks by team_id. If the team already has an active SID
    from a DIFFERENT device, the new connection is rejected. If it's the
    same team refreshing (old SID already gone or being replaced), the
    new SID seamlessly takes over.

    Args:
        data: {'team_id': '...'} for teams, or {'role': 'admin'/'spectator'} for others.
    """
    logger.info(f"Client {sid} joining auction: {data}")

    try:
        team_id = data.get('team_id')
        role = data.get('role', 'team')

        if team_id:
            str_team_id = str(team_id)

            # "Last login wins" — if team is already connected on another SID,
            # kick the OLD device and let the NEW one take over.
            # This also handles page refresh seamlessly (old SID is already gone
            # or about to disconnect, so the kick is a no-op).
            existing = _team_presence.get(str_team_id)
            if existing and existing['sid'] != sid:
                old_sid = existing['sid']
                logger.info(f"Team {team_id} reconnecting. Kicking old sid {old_sid}, accepting new sid {sid}.")
                _sid_to_team.pop(old_sid, None)
                try:
                    await sio.emit('connection_rejected', {
                        'message': 'Your team logged in from another device. This session has been disconnected.'
                    }, room=old_sid)
                    await sio.disconnect(old_sid)
                except Exception as e:
                    logger.warning(f"Error kicking old sid {old_sid}: {e}")

            # Look up team name from DB
            team_name = 'Unknown'
            try:
                from sqlmodel.ext.asyncio.session import AsyncSession as AS2
                from sqlalchemy.orm import sessionmaker as sm2
                async_session2 = sm2(engine, class_=AS2, expire_on_commit=False)
                async with async_session2() as s2:
                    team_stmt = select(Team).where(Team.id == team_id)
                    team_res = await s2.exec(team_stmt)
                    team = team_res.first()

                    if team and getattr(team, 'is_banned', False):
                        logger.warning(f"Banned team {team_id} attempted to join auction.")
                        await sio.emit('banned', {'message': 'Your team has been banned from the auction.'}, room=sid)
                        await sio.disconnect(sid)
                        return

                    team_name = team.name if team else 'Unknown'
            except Exception as e:
                logger.error(f"DB error looking up team {team_id}: {e}")

            # Register presence — keyed by team_id, not SID
            _team_presence[str_team_id] = {'sid': sid, 'team_name': team_name}
            _sid_to_team[sid] = str_team_id
            logger.info(f"Team {team_name} (id={str_team_id}) registered with sid {sid}.")

        else:
            # Admin / Spectator
            _other_clients[sid] = {'role': role, 'team_name': role.capitalize()}
            logger.info(f"Non-team client ({role}) registered with sid {sid}.")

        # Join the Socket.IO room for broadcasts
        try:
            await sio.enter_room(sid, 'auction_room')
        except Exception as e:
            logger.warning(f"Failed to enter auction_room for {sid}: {e}")
            return

        await broadcast_connection_count()

        # Send current auction state to the newly joined client
        try:
            from sqlmodel.ext.asyncio.session import AsyncSession
            from sqlalchemy.orm import sessionmaker

            async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with async_session() as session:
                state_statement = select(AuctionState).where(AuctionState.id == 1)
                result = await session.exec(state_statement)
                state = result.first()

                if not state:
                    state = AuctionState(id=1, current_plot_number=1, status=AuctionStatus.NOT_STARTED)
                    session.add(state)
                    await session.commit()
                    await session.refresh(state)

                current_plot = None
                if state.current_plot_number:
                    plot_stmt = select(Plot).where(Plot.number == state.current_plot_number)
                    plot_res = await session.exec(plot_stmt)
                    current_plot = plot_res.first()

                await sio.emit('auction_state_update', serialize({
                    'status': state.status,
                    'current_plot': current_plot.dict() if current_plot else None,
                    'current_plot_number': state.current_plot_number,
                    'current_round': state.current_round,
                    'current_question': getattr(state, "current_question", None)
                }), room=sid)
        except Exception as e:
            logger.error(f"Error sending initial state to {sid}: {e}")
            await sio.emit('auction_state_update', serialize({
                'status': 'not_started',
                'current_plot': None,
                'current_plot_number': 1,
                'current_question': None
            }), room=sid)

    except Exception as e:
        logger.error(f"CRITICAL: Unhandled error in join_auction for {sid}: {e}", exc_info=True)


@sio.event
async def place_bid(sid, data):
    """
    Handle a bid from a team.

    Args:
        data: {'team_id': 'uuid', 'amount': 10000}
    """
    logger.info(f"Bid received from {sid}: {data}")

    from sqlmodel.ext.asyncio.session import AsyncSession
    from sqlalchemy.orm import sessionmaker
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        # 1. Check Auction Status
        state_stmt = select(AuctionState).where(AuctionState.id == 1)
        state_res = await session.exec(state_stmt)
        state = state_res.first()

        if not state or state.status not in (AuctionStatus.RUNNING, AuctionStatus.SELLING):
            await sio.emit('bid_error', {'message': 'Auction is not running'}, room=sid)
            return

        # 2. Get Plot
        plot_stmt = select(Plot).where(Plot.number == state.current_plot_number)
        plot_res = await session.exec(plot_stmt)
        plot = plot_res.first()

        if not plot or plot.status != PlotStatus.ACTIVE:
            await sio.emit('bid_error', {'message': 'Plot is not active'}, room=sid)
            return

        amount = float(data.get('amount', 0))
        team_id = data.get('team_id')

        # 3. Get Team
        team_stmt = select(Team).where(Team.id == team_id)
        team_res = await session.exec(team_stmt)
        team = team_res.first()

        if not team:
            await sio.emit('bid_error', {'message': 'Invalid team'}, room=sid)
            return

        # 4. Validate Bid
        if getattr(team, 'is_banned', False):
            await sio.emit('bid_error', {'message': 'Your team has been banned and cannot place bids.'}, room=sid)
            return

        current_highest = float(plot.current_bid) if plot.current_bid else 0
        adjusted_base = float(plot.total_plot_price) + float(plot.round_adjustment)
        min_required = current_highest + 100000 if current_highest > 0 else (adjusted_base or 100000)

        if amount < min_required:
             await sio.emit('bid_error', {'message': f'Minimum bid is ₹{min_required:,.0f}'}, room=sid)
             return

        if plot.winner_team_id == team.id:
             await sio.emit('bid_error', {'message': 'You already hold the highest bid!'}, room=sid)
             return

        if amount > float(team.budget - team.spent):
             await sio.emit('bid_error', {'message': 'Insufficient budget'}, room=sid)
             return

        # 5. Place Bid
        plot.current_bid = Decimal(amount)
        plot.winner_team_id = team.id
        session.add(plot)

        # Abort sell countdown if active
        was_selling = False
        if state.status == AuctionStatus.SELLING:
            state.status = AuctionStatus.RUNNING
            session.add(state)
            was_selling = True

        # Create Bid Record
        new_bid = Bid(
            amount=Decimal(amount),
            team_id=team.id,
            plot_id=plot.id,
            timestamp=datetime.utcnow()
        )
        session.add(new_bid)

        await session.commit()

        # 6. Broadcast Update
        await sio.emit('new_bid', serialize({
            'amount': amount,
            'team_id': team.id,
            'team_name': team.name,
            'plot_number': plot.number,
            'timestamp': str(new_bid.timestamp)
        }), room='auction_room')

        # Update plot info for everyone
        await sio.emit('plot_update', serialize({
            'plot': plot.dict(),
            'winner_team': team.name
        }), room='auction_room')

        if was_selling:
            await sio.emit('auction_state_update', serialize({
                'status': state.status,
                'current_plot_number': state.current_plot_number,
                'current_round': state.current_round,
                'current_question': getattr(state, "current_question", None),
                'rebid_phase_active': state.rebid_phase_active,
                'round4_phase': state.round4_phase,
                'round4_bid_queue': state.round4_bid_queue
            }), room='auction_room')


async def kick_banned_team(team_id: Any):
    """Forcefully disconnect all active sockets for a banned team."""
    str_team_id = str(team_id)

    info = _team_presence.pop(str_team_id, None)
    if info:
        sid = info['sid']
        _sid_to_team.pop(sid, None)
        logger.warning(f"Kicking banned team session: {sid}")
        await sio.emit('banned', {'message': 'Your team has been banned from the auction.'}, room=sid)
        await sio.disconnect(sid)
        await broadcast_connection_count()

import socketio
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
    cors_allowed_origins='*', # For development
    ping_timeout=20,
    ping_interval=10
)

# Track connected clients: {sid: {'team_id': ..., 'team_name': ..., 'role': ...}}
connected_clients: dict[str, dict] = {}

def get_connected_count() -> int:
    """Return the number of connected clients."""
    return len(connected_clients)

def get_connected_teams() -> list[str]:
    """Return list of connected team names."""
    return [c['team_name'] for c in connected_clients.values() if c.get('team_name')]

async def broadcast_connection_count():
    """Broadcast updated connection count to all clients in the auction room."""
    await sio.emit('connection_count', {
        'count': get_connected_count(),
        'teams': get_connected_teams()
    }, room='auction_room')

def serialize(data):
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

@sio.event
async def connect(sid, environ):
    """Handle new client connection."""
    logger.info(f"Client connected: {sid}")
    connected_clients[sid] = {'role': 'unknown'}
    await sio.emit('connection_response', {'data': 'Connected'}, room=sid)

@sio.event
async def disconnect(sid):
    """Handle client disconnection and broadcast updated count."""
    logger.info(f"Client disconnected: {sid}")
    connected_clients.pop(sid, None)
    await broadcast_connection_count()

@sio.event
async def leave_auction(sid):
    """Explicitly handle client leaving before socket closes."""
    logger.info(f"Client leaving explicitly: {sid}")
    connected_clients.pop(sid, None)
    await broadcast_connection_count()

@sio.event
async def join_auction(sid, data):
    """
    Data should contain {'team_id': '...'} or {'role': 'admin'/'spectator'}
    """
    logger.info(f"Client {sid} joining auction: {data}")
    
    # Check if sid is still connected
    if sid not in connected_clients:
        logger.warning(f"Client {sid} disconnected before join_auction completed")
        return
    
    # Track who joined
    team_id = data.get('team_id')
    role = data.get('role', 'team')
    
    if team_id:
        str_team_id = str(team_id)
        # Prevent multiple connections for the same team
        for existing_sid, info in list(connected_clients.items()):
            if info.get('team_id') == str_team_id and existing_sid != sid:
                logger.warning(f"Team {team_id} reconnected. Disconnecting old sid: {existing_sid}")
                await sio.emit('connection_rejected', {'message': 'Connected from another device. This session is now disconnected.'}, room=existing_sid)
                await sio.disconnect(existing_sid)
                
                # Remove old client from tracking explicitly to keep count accurate immediately
                connected_clients.pop(existing_sid, None)

        # Look up team name
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

            connected_clients[sid] = {
                'team_id': str(team_id),
                'team_name': team.name if team else 'Unknown',
                'role': 'team'
            }
    else:
        connected_clients[sid] = {'role': role, 'team_name': role.capitalize()}
    
    try:
        await sio.enter_room(sid, 'auction_room')
    except Exception as e:
        logger.warning(f"Failed to enter room for {sid}: {e}")
        return
    
    await broadcast_connection_count()
    
    # Send current state immediately upon join
    # We need a new session here since this is an event handler
    from sqlmodel.ext.asyncio.session import AsyncSession
    from sqlalchemy.orm import sessionmaker
    
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
         # Get current auction state
        state_statement = select(AuctionState).where(AuctionState.id == 1)
        result = await session.exec(state_statement)
        state = result.first()
        
        if not state:
            # Initialize if not exists
            state = AuctionState(id=1, current_plot_number=1, status=AuctionStatus.NOT_STARTED)
            session.add(state)
            await session.commit()
            await session.refresh(state)

        # Get current plot info if active
        current_plot = None
        if state.current_plot_number:
            plot_stmt = select(Plot).where(Plot.number == state.current_plot_number)
            plot_res = await session.exec(plot_stmt)
            current_plot = plot_res.first()

        await sio.emit('auction_state_update', serialize({
            'status': state.status,
            'current_plot': current_plot.dict() if current_plot else None,
            'current_plot_number': state.current_plot_number,
            'current_question': getattr(state, "current_question", None)
        }), room=sid)

@sio.event
async def place_bid(sid, data):
    """
    Data: {'team_id': 'uuid', 'amount': 10000}
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
        # Update Plot
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
    to_disconnect = []
    
    for sid, info in list(connected_clients.items()):
        if info.get('team_id') == str_team_id:
            to_disconnect.append(sid)
            
    for sid in to_disconnect:
        logger.warning(f"Kicking banned team session: {sid}")
        # Notify the client they are banned so they can redirect/logout
        await sio.emit('banned', {'message': 'Your team has been banned from the auction.'}, room=sid)
        await sio.disconnect(sid)


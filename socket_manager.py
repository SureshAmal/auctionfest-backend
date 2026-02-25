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
    async_mode="asgi", cors_allowed_origins="*", ping_interval=10, ping_timeout=15
)

# Constants
GRACE_PERIOD = 30000  # 30 seconds
HEARTBEAT_TIMEOUT = 20000  # 20 seconds

# Track connected teams: {team_id: {socket_id, team_name, status, connected_at, last_heartbeat}}
connected_teams: dict[str, dict] = {}

# Reverse lookup: {socket_id: team_id}
socket_to_team: dict[str, str] = {}

# Disconnect grace period timers: {team_id: setTimeout reference}
disconnect_timers: dict[str, Any] = {}

# Track connected clients (for auction room)
connected_clients: dict[str, dict] = {}


def get_connected_count() -> int:
    """Return the number of connected clients."""
    return len(connected_clients)


def get_connected_teams_list() -> list[str]:
    """Return list of connected team names."""
    return [c["team_name"] for c in connected_clients.values() if c.get("team_name")]


def get_online_teams_array() -> list[dict]:
    """Return array of online teams with their status."""
    teams = []
    for team_id, info in connected_teams.items():
        teams.append(
            {
                "teamId": team_id,
                "teamName": info.get("team_name", "Unknown"),
                "status": info.get("status", "active"),
                "connectedAt": info.get("connected_at"),
                "lastHeartbeat": info.get("last_heartbeat"),
            }
        )
    return teams


async def broadcast_online_teams():
    """Broadcast updated online teams list to all connected sockets."""
    teams_array = get_online_teams_array()
    await sio.emit("online-teams-updated", teams_array)
    logger.info(f"[Socket] Broadcast online teams: {len(teams_array)} teams")


async def broadcast_connection_count():
    """Broadcast updated connection count to all clients in the auction room."""
    await sio.emit(
        "connection_count",
        {"count": get_connected_count(), "teams": get_connected_teams_list()},
        room="auction_room",
    )


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
    logger.info(f"[Socket] Client connected: {sid}")
    connected_clients[sid] = {"role": "unknown"}
    await sio.emit("connection_response", {"data": "Connected"}, room=sid)


@sio.event
async def disconnect(sid):
    """Handle client disconnection with grace period."""
    logger.info(f"[Socket] Client disconnected: {sid}")

    # Check if this was a registered team
    team_id = socket_to_team.get(sid)

    if team_id and team_id in connected_teams:
        # Cancel any existing grace timer
        if team_id in disconnect_timers:
            logger.info(f"[Socket] Cancelling disconnect timer for team {team_id}")
            # Note: Cannot cancel asyncio timer directly, but we track it

        # Set status to reconnecting instead of removing immediately
        connected_teams[team_id]["status"] = "reconnecting"
        connected_teams[team_id]["disconnect_time"] = datetime.utcnow().isoformat()

        # Remove from socket mapping but keep in connected_teams for grace period
        del socket_to_team[sid]

        # Start grace period timer
        async def remove_after_grace():
            await asyncio.sleep(GRACE_PERIOD / 1000)
            if (
                team_id in connected_teams
                and connected_teams[team_id].get("status") == "reconnecting"
            ):
                logger.info(f"[Socket] Grace period expired, removing team {team_id}")
                connected_teams.pop(team_id, None)
                disconnect_timers.pop(team_id, None)
                await broadcast_online_teams()

        # Schedule removal
        disconnect_timers[team_id] = asyncio.create_task(remove_after_grace())

        # Broadcast update showing reconnecting status
        await broadcast_online_teams()
        logger.info(
            f"[Socket] Team {team_id} marked as reconnecting, grace period started"
        )

    # Remove from connected_clients
    connected_clients.pop(sid, None)
    await broadcast_connection_count()


@sio.event
async def team_register(sid, data):
    """
    Register a team when they connect or reconnect.
    Data: {'team_id': 'uuid', 'team_name': 'Team Name'}
    """
    team_id = str(data.get("team_id"))
    team_name = data.get("team_name", "Unknown")

    logger.info(f"[Socket] Team registering: {team_id} ({team_name}) from sid: {sid}")

    # Cancel any existing grace period timer for this team
    if team_id in disconnect_timers:
        logger.info(f"[Socket] Cancelling grace period for team {team_id}")
        disconnect_timers.pop(team_id, None)

    # Check if team already connected on another socket
    old_sid = None
    for existing_sid, existing_team_id in socket_to_team.items():
        if existing_team_id == team_id:
            old_sid = existing_sid
            break

    if old_sid:
        logger.info(
            f"[Socket] Team {team_id} already connected on {old_sid}, disconnecting old socket"
        )
        await sio.emit(
            "force-disconnect",
            {"message": "Connected from another device"},
            room=old_sid,
        )
        await sio.disconnect(old_sid)

    # Store team info
    connected_teams[team_id] = {
        "socket_id": sid,
        "team_name": team_name,
        "status": "active",
        "connected_at": datetime.utcnow().isoformat(),
        "last_heartbeat": datetime.utcnow().isoformat(),
    }

    # Update reverse lookup
    socket_to_team[sid] = team_id

    # Ensure client is in auction room
    await sio.enter_room(sid, "auction_room")

    # Broadcast updated online teams
    await broadcast_online_teams()
    logger.info(f"[Socket] Team {team_id} registered as active")


@sio.event
async def heartbeat(sid, data):
    """
    Receive heartbeat from client.
    Data: {'team_id': 'uuid'}
    """
    team_id = str(data.get("team_id"))

    if team_id in connected_teams:
        connected_teams[team_id]["last_heartbeat"] = datetime.utcnow().isoformat()
        connected_teams[team_id]["status"] = "active"
        await sio.emit("heartbeat-ack", {"received": True}, room=sid)
        logger.debug(f"[Heartbeat] Received from team {team_id}")


@sio.event
async def tab_visibility(sid, data):
    """
    Handle tab visibility changes.
    Data: {'team_id': 'uuid', 'is_visible': true/false}
    """
    team_id = str(data.get("team_id"))
    is_visible = data.get("is_visible", True)

    if team_id in connected_teams:
        connected_teams[team_id]["status"] = "active" if is_visible else "idle"
        connected_teams[team_id]["last_heartbeat"] = datetime.utcnow().isoformat()
        await broadcast_online_teams()
        logger.info(
            f"[Visibility] Team {team_id} status: {'active' if is_visible else 'idle'}"
        )


@sio.event
async def team_logout(sid, data):
    """
    Handle explicit team logout.
    Data: {'team_id': 'uuid'}
    IMMEDIATELY remove team - no grace period.
    """
    team_id = str(data.get("team_id"))

    logger.info(f"[Logout] Team {team_id} logging out explicitly")

    # Cancel any grace period timer
    if team_id in disconnect_timers:
        disconnect_timers.pop(team_id, None)

    # IMMEDIATELY remove from connected teams
    connected_teams.pop(team_id, None)

    # Remove from socket mapping
    socket_to_team.pop(sid, None)

    # Remove from connected_clients
    connected_clients.pop(sid, None)

    # Force disconnect the socket
    await sio.disconnect(sid)

    # Broadcast updated list
    await broadcast_online_teams()
    await broadcast_connection_count()
    logger.info(f"[Logout] Team {team_id} removed immediately")


@sio.event
async def join_auction(sid, data):
    """
    Data should contain {'team_id': '...'} or {'role': 'admin'/'spectator'}
    Also triggers team registration.
    """
    logger.info(f"Client {sid} joining auction: {data}")

    # Track who joined
    team_id = data.get("team_id")
    role = data.get("role", "team")

    if team_id:
        str_team_id = str(team_id)

        # Prevent multiple connections for the same team
        existing_sid = None
        for existing_sid_check, info in list(connected_clients.items()):
            if info.get("team_id") == str_team_id and existing_sid_check != sid:
                existing_sid = existing_sid_check
                break

        if existing_sid:
            logger.warning(
                f"Team {team_id} attempted multiple connections from sid {sid}. Existing sid: {existing_sid}"
            )
            await sio.emit(
                "connection_rejected",
                {
                    "message": "Your team is already connected to the live tracker from another device. Please disconnect the other device first."
                },
                room=sid,
            )
            await sio.disconnect(sid)
            return

        # Look up team name
        from sqlmodel.ext.asyncio.session import AsyncSession as AS2
        from sqlalchemy.orm import sessionmaker as sm2

        async_session2 = sm2(engine, class_=AS2, expire_on_commit=False)
        async with async_session2() as s2:
            team_stmt = select(Team).where(Team.id == team_id)
            team_res = await s2.exec(team_stmt)
            team = team_res.first()
            team_name = team.name if team else "Unknown"

            connected_clients[sid] = {
                "team_id": str_team_id,
                "team_name": team_name,
                "role": "team",
            }

            # Auto-register team
            await team_register(sid, {"team_id": str_team_id, "team_name": team_name})
    else:
        connected_clients[sid] = {"role": role, "team_name": role.capitalize()}

    await sio.enter_room(sid, "auction_room")
    await broadcast_connection_count()

    # Send current state immediately upon join
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
            state = AuctionState(
                id=1, current_plot_number=1, status=AuctionStatus.NOT_STARTED
            )
            session.add(state)
            await session.commit()
            await session.refresh(state)

        # Get current plot info if active
        current_plot = None
        if state.current_plot_number:
            plot_stmt = select(Plot).where(Plot.number == state.current_plot_number)
            plot_res = await session.exec(plot_stmt)
            current_plot = plot_res.first()

        await sio.emit(
            "auction_state_update",
            serialize(
                {
                    "status": state.status,
                    "current_plot": current_plot.dict() if current_plot else None,
                    "current_plot_number": state.current_plot_number,
                    "current_question": getattr(state, "current_question", None),
                }
            ),
            room=sid,
        )


@sio.event
async def get_online_teams(sid):
    """Return current online teams list to the requester."""
    await sio.emit("online-teams-updated", get_online_teams_array(), room=sid)


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

        if not state or state.status not in (
            AuctionStatus.RUNNING,
            AuctionStatus.SELLING,
        ):
            await sio.emit("bid_error", {"message": "Auction is not running"}, room=sid)
            return

        # 2. Get Plot
        plot_stmt = select(Plot).where(Plot.number == state.current_plot_number)
        plot_res = await session.exec(plot_stmt)
        plot = plot_res.first()

        if not plot or plot.status != PlotStatus.ACTIVE:
            await sio.emit("bid_error", {"message": "Plot is not active"}, room=sid)
            return

        amount = float(data.get("amount", 0))
        team_id = data.get("team_id")

        # 3. Get Team
        team_stmt = select(Team).where(Team.id == team_id)
        team_res = await session.exec(team_stmt)
        team = team_res.first()

        if not team:
            await sio.emit("bid_error", {"message": "Invalid team"}, room=sid)
            return

        # 4. Validate Bid
        current_highest = float(plot.current_bid) if plot.current_bid else 0
        if amount <= current_highest:
            await sio.emit(
                "bid_error",
                {"message": f"Bid must be higher than {current_highest}"},
                room=sid,
            )
            return

        if plot.winner_team_id == team.id:
            await sio.emit(
                "bid_error", {"message": "You already hold the highest bid!"}, room=sid
            )
            return

        if amount > float(team.budget - team.spent):
            await sio.emit("bid_error", {"message": "Insufficient budget"}, room=sid)
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
            timestamp=datetime.utcnow(),
        )
        session.add(new_bid)

        await session.commit()

        # 6. Broadcast Update
        await sio.emit(
            "new_bid",
            serialize(
                {
                    "amount": amount,
                    "team_id": team.id,
                    "team_name": team.name,
                    "plot_number": plot.number,
                    "timestamp": str(new_bid.timestamp),
                }
            ),
            room="auction_room",
        )

        # Update plot info for everyone
        await sio.emit(
            "plot_update",
            serialize({"plot": plot.dict(), "winner_team": team.name}),
            room="auction_room",
        )

        if was_selling:
            await sio.emit(
                "auction_state_update",
                serialize(
                    {
                        "status": state.status,
                        "current_plot_number": state.current_plot_number,
                        "current_round": state.current_round,
                        "current_question": getattr(state, "current_question", None),
                        "rebid_phase_active": state.rebid_phase_active,
                        "round4_phase": state.round4_phase,
                        "round4_bid_queue": state.round4_bid_queue,
                    }
                ),
                room="auction_room",
            )


# Stale connection cleanup task
async def cleanup_stale_connections():
    """Periodically check for stale connections."""
    import asyncio

    while True:
        await asyncio.sleep(30)  # Run every 30 seconds
        now = datetime.utcnow()

        for team_id, info in list(connected_teams.items()):
            if info.get("status") == "active":
                last_hb = info.get("last_heartbeat")
                if last_hb:
                    last_hb_time = datetime.fromisoformat(
                        last_hb.replace("Z", "+00:00")
                    )
                    elapsed = (now - last_hb_time).total_seconds() * 1000

                    if elapsed > HEARTBEAT_TIMEOUT:
                        # Check if socket still exists and is connected
                        sid = info.get("socket_id")
                        if (
                            sid not in socket_to_team
                            or socket_to_team.get(sid) != team_id
                        ):
                            # Socket gone, start grace period
                            logger.info(
                                f"[Socket] No heartbeat from team {team_id} for {elapsed}ms, starting removal"
                            )
                            info["status"] = "reconnecting"
                            info["disconnect_time"] = now.isoformat()

                            async def remove_stale():
                                await asyncio.sleep(GRACE_PERIOD / 1000)
                                if (
                                    team_id in connected_teams
                                    and connected_teams[team_id].get("status")
                                    == "reconnecting"
                                ):
                                    connected_teams.pop(team_id, None)
                                    disconnect_timers.pop(team_id, None)
                                    await broadcast_online_teams()

                            disconnect_timers[team_id] = asyncio.create_task(
                                remove_stale()
                            )
                            await broadcast_online_teams()
                        else:
                            # Socket exists but no heartbeat, mark as idle
                            info["status"] = "idle"
                            await broadcast_online_teams()


# Start cleanup task
import asyncio

asyncio.create_task(cleanup_stale_connections())

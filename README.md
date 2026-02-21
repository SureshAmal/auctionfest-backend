# AU-FEST 2026 Auction Backend

Real-time auction backend for AU-FEST 2026 land plot auction system. Built with FastAPI and Socket.IO for real-time bidding updates.

## Tech Stack

- **FastAPI** - REST API framework
- **Socket.IO** - Real-time bidirectional communication
- **SQLModel** - Database ORM (supports PostgreSQL/SQLite)
- **PostgreSQL** - Primary database (via asyncpg)
- **pytest** - Testing framework

## Features

- Team authentication with passcode
- Real-time bid updates via WebSocket
- Admin controls: start, pause, advance to next plot, reset auction
- Plot management with status tracking (pending, active, sold)
- Budget tracking for teams
- Connected client monitoring

## Setup

### Prerequisites

- Python 3.12+
- PostgreSQL database

### Installation

```bash
uv sync
```

### Environment Variables

Create a `.env` file:

```env
DATABASE_URL=postgresql+asyncpg://user:password@host:5432/auctionfest
SECRET_KEY=asdjkasd
ALLOWED_ORIGINS=http://localhost:5173,http://localhost:3000
```

### Database Setup

```bash
# Seed database with sample data
python seed.py
```

### Running the Server

```bash
uv run uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

The server runs on `http://localhost:8000`

## API Endpoints

### Authentication

- `POST /api/auth/login` - Team login

### Data

- `GET /api/data/plots` - Get all plots
- `GET /api/data/teams` - Get all teams
- `GET /api/data/team/{team_id}` - Get specific team
- `GET /api/data/connected` - Get connected client count

### Admin

- `GET /api/admin/state` - Get auction state
- `POST /api/admin/start` - Start auction
- `POST /api/admin/pause` - Pause auction
- `POST /api/admin/next` - Move to next plot
- `POST /api/admin/reset` - Reset auction

## Socket.IO Events

### Emitted Events

- `auction_state_update` - Auction state changes
- `bid_update` - New bid placed
- `auction_reset` - Auction reset

### Client Events (handled server-side)

- `join_room` - Join auction room
- `place_bid` - Place a bid on current plot

## Database Models

- **Team** - Bidding teams with budget and spent tracking
- **Plot** - Auction plots with area, price, and status
- **Bid** - Individual bids with amount and timestamp
- **AuctionState** - Global auction state (current plot, status)

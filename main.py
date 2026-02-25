from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from socket_manager import sio
import socketio
from database import init_db
from routers import auth, admin, data, rebid
from models import *  # Load models
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    try:
        await init_db()
    except Exception as e:
        print(f"CRITICAL: Database initialization failed: {e}")
        print("Continuing to start server, but database features will fail.")
    yield

    # Shutdown (if needed)

server = FastAPI(title="AU-FEST 2026 Auction", lifespan=lifespan)

# CORS 
# User requested wildcard '*' access
server.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Allow ALL origins
    allow_credentials=False, # Credentials (cookies) not supported with wildcard origin
    allow_methods=["*"],
    allow_headers=["*"],
)

# API Routers
server.include_router(auth.router)
server.include_router(admin.router)
server.include_router(data.router)
server.include_router(rebid.router)

# Mount Socket.IO
app = socketio.ASGIApp(sio, server)

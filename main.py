from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from socket_manager import sio
import socketio
from database import init_db
from routers import auth, admin, data
from models import * # Load models

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from socket_manager import sio
import socketio
from database import init_db
from routers import auth, admin, data
from models import * # Load models

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await init_db()
    yield
    # Shutdown (if needed)

server = FastAPI(title="AU-FEST 2026 Auction", lifespan=lifespan)

# CORS
origins = ["*"] # Adjust for production
server.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API Routers
server.include_router(auth.router)
server.include_router(admin.router)
server.include_router(data.router)

# Mount Socket.IO
app = socketio.ASGIApp(sio, server)

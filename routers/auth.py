from fastapi import APIRouter, Depends, HTTPException
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select
from database import get_session
from models import Team
from pydantic import BaseModel

router = APIRouter(prefix="/api/auth", tags=["auth"])

class LoginRequest(BaseModel):
    name: str
    passcode: str

@router.post("/login")
async def login(creds: LoginRequest, session: AsyncSession = Depends(get_session)):
    stmt = select(Team).where(Team.name == creds.name)
    result = await session.exec(stmt)
    team = result.first()
    
    if not team:
        raise HTTPException(status_code=401, detail="Invalid team name")
        
    if team.passcode != creds.passcode:
        raise HTTPException(status_code=401, detail="Invalid passcode")
        
    if getattr(team, 'is_banned', False):
        raise HTTPException(status_code=403, detail="Your team has been banned from the auction.")
        
    return team

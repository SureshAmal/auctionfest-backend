import pytest
from models import Team, Plot
from sqlmodel import select

@pytest.mark.asyncio
async def test_create_team(session):
    team = Team(name="Test Team", passcode="1234")
    session.add(team)
    await session.commit()
    
    stmt = select(Team).where(Team.name == "Test Team")
    result = await session.exec(stmt)
    assert result.first().name == "Test Team"

@pytest.mark.asyncio
async def test_login(client, session):
    # Setup
    team = Team(name="Login Team", passcode="secret")
    session.add(team)
    await session.commit()
    
    # Success
    response = await client.post("/api/auth/login", json={"name": "Login Team", "passcode": "secret"})
    assert response.status_code == 200
    assert response.json()["name"] == "Login Team"
    
    # Fail Password
    response = await client.post("/api/auth/login", json={"name": "Login Team", "passcode": "wrong"})
    assert response.status_code == 401
    
    # Fail Name
    response = await client.post("/api/auth/login", json={"name": "Wrong Team", "passcode": "secret"})
    assert response.status_code == 401

@pytest.mark.asyncio
async def test_data_endpoints(client, session):
    response = await client.get("/api/data/plots")
    assert response.status_code == 200
    assert isinstance(response.json(), list)
    
    response = await client.get("/api/data/teams")
    assert response.status_code == 200
    assert isinstance(response.json(), list)

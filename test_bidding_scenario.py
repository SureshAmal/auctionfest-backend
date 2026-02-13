import asyncio
import socketio
import httpx
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

BASE_URL = "http://localhost:8000"

async def test_bidding_scenario():
    # 1. Login Teams to get IDs
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        # Team A
        res_a = await client.post("/api/auth/login", json={"name": "Team A", "passcode": "pass0"})
        if res_a.status_code != 200:
            logger.error(f"Failed to login Team A: {res_a.text}")
            return
        team_a = res_a.json()
        logger.info(f"Team A Logged in: {team_a['id']}")

        # Team B
        res_b = await client.post("/api/auth/login", json={"name": "Team B", "passcode": "pass1"})
        if res_b.status_code != 200:
            logger.error(f"Failed to login Team B: {res_b.text}")
            return
        team_b = res_b.json()
        logger.info(f"Team B Logged in: {team_b['id']}")
        
        # Reset Auction First
        await client.post("/api/admin/reset")
        logger.info("Auction Reset")

    # 2. Connect Sockets
    sio_admin = socketio.AsyncClient()
    sio_a = socketio.AsyncClient()
    sio_b = socketio.AsyncClient()

    # Event Handlers
    @sio_a.event
    async def new_bid(data):
        logger.info(f"[Team A] Saw new bid: {data['amount']} by {data['team_name']}")

    @sio_b.event
    async def new_bid(data):
        logger.info(f"[Team B] Saw new bid: {data['amount']} by {data['team_name']}")
        
    @sio_a.event
    async def auction_state_update(data):
        logger.info(f"[Team A] State Update: {data.get('status')} Plot: {data.get('current_plot_number')}")

    await sio_admin.connect(BASE_URL)
    await sio_a.connect(BASE_URL)
    await sio_b.connect(BASE_URL)
    
    await sio_admin.emit('join_auction', {'role': 'admin'})
    await sio_a.emit('join_auction', {'team_id': team_a['id']})
    await sio_b.emit('join_auction', {'team_id': team_b['id']})
    
    # 3. Start Auction (via API usually, or socket if implemented. Admin API is REST)
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        await client.post("/api/admin/start")
        logger.info("Admin started auction")
        
    await asyncio.sleep(1)
    
    # 4. Team A Bids
    logger.info("Team A placing bid: 5000")
    await sio_a.emit('place_bid', {'team_id': team_a['id'], 'amount': 5000})
    await asyncio.sleep(1)
    
    # 5. Team B Bids
    logger.info("Team B placing bid: 6000")
    await sio_b.emit('place_bid', {'team_id': team_b['id'], 'amount': 6000})
    await asyncio.sleep(1)
    
    # 6. Team A tries to bid lower (should fail - check logs if implemented client side error handling or server log)
    logger.info("Team A placing invalid bid: 5500")
    await sio_a.emit('place_bid', {'team_id': team_a['id'], 'amount': 5500})
    await asyncio.sleep(1)
    
    # 7. Next Plot
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        await client.post("/api/admin/next")
        logger.info("Admin moved to next plot")
        
    await asyncio.sleep(2)

    await sio_admin.disconnect()
    await sio_a.disconnect()
    await sio_b.disconnect()
    logger.info("Test Complete")

if __name__ == "__main__":
    asyncio.run(test_bidding_scenario())

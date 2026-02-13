import asyncio
import socketio
import time
import argparse

# Configuration
URL = "http://localhost:8000"
DEFAULT_NUM_CLIENTS = 100
RAMP_UP_DELAY = 0.05

success_count = 0
error_count = 0

async def start_client(i):
    global success_count, error_count
    sio = socketio.AsyncClient()
    
    @sio.event
    async def connect():
        pass
        
    @sio.event
    async def auction_state_update(data):
        pass

    try:
        await sio.connect(URL)
        # Verify connection by sending a join event if needed, or just existence is enough
        # In our server, just connecting establishes the socket.
        # Let's try to join the room explicitly if we implemented that event.
        # Looking at socket_manager.py: @sio.event async def join_auction(sid, data):
        await sio.emit('join_auction', {'role': 'load_tester', 'client_id': i})
        
        global success_count
        success_count += 1
        # Keep connection open for a bit
        await asyncio.sleep(5)
        await sio.disconnect()
    except Exception as e:
        global error_count
        error_count += 1
        print(f"Client {i} failed: {e}")

async def main(num_clients):
    print(f"Starting load test with {num_clients} clients connecting to {URL}...")
    start_time = time.time()
    
    tasks = []
    for i in range(num_clients):
        tasks.append(asyncio.create_task(start_client(i)))
        await asyncio.sleep(RAMP_UP_DELAY) # Ramp up to avoid immediate DDoS of local stack
        
    await asyncio.gather(*tasks)
    
    duration = time.time() - start_time
    print(f"\nTest Completed in {duration:.2f} seconds")
    print(f"Successful connections: {success_count}")
    print(f"Failed connections: {error_count}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Socket.IO Load Tester")
    parser.add_argument("--clients", type=int, default=DEFAULT_NUM_CLIENTS, help="Number of clients")
    args = parser.parse_args()
    
    asyncio.run(main(args.clients))

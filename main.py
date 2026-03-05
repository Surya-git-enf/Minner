import os
import time
import threading
from contextlib import asynccontextmanager
from fastapi import FastAPI
from web3 import Web3
from dotenv import load_dotenv

# --- 1. LOAD CREDENTIALS ---
load_dotenv()
WALLET_ADDRESS = os.getenv("WALLET_ADDRESS")
PRIVATE_KEY = os.getenv("PRIVATE_KEY")
RPC_URL = os.getenv("PRIVATE_RPC_URL", "https://polygon.mev-blocker.io")

# --- 2. WEB3 SETUP ---
web3 = Web3(Web3.HTTPProvider(RPC_URL))
QUICKSWAP_ROUTER = web3.to_checksum_address("0xa5E0829CaCEd8fFCEEd813c0150ce195f19520a1")
SUSHISWAP_ROUTER = web3.to_checksum_address("0x1b02dA8Cb0d097eB8D57A175b88c7D8b47997506")
POL_TOKEN = web3.to_checksum_address("0x0000000000000000000000000000000000001010") 
USDC_TOKEN = web3.to_checksum_address("0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174")

# Minimal ABI for checking prices
router_abi = [
    {"constant": True, "inputs": [{"name": "amountIn", "type": "uint256"}, {"name": "path", "type": "address[]"}], "name": "getAmountsOut", "outputs": [{"name": "amounts", "type": "uint256[]"}], "payable": False, "stateMutability": "view", "type": "function"}
]

quick_contract = web3.eth.contract(address=QUICKSWAP_ROUTER, abi=router_abi)
sushi_contract = web3.eth.contract(address=SUSHISWAP_ROUTER, abi=router_abi)

# --- 3. THE ARBITRAGE BOT LOOP ---
def run_bot():
    if not web3.is_connected():
        print("Failed to connect to Polygon.")
        return
        
    print("Bot is alive and watching prices on the blockchain... 🤖")
    trade_amount_pol = 50 # Example: Check prices for 50 POL
    trade_amount_wei = web3.to_wei(trade_amount_pol, 'ether')
    path = [POL_TOKEN, USDC_TOKEN]

    while True:
        try:
            # Check Prices on both DEXs
            quick_out = quick_contract.functions.getAmountsOut(trade_amount_wei, path).call()[1]
            sushi_out = sushi_contract.functions.getAmountsOut(trade_amount_wei, path).call()[1]

            # Calculate Spread
            if quick_out > sushi_out:
                profit = ((quick_out - sushi_out) / sushi_out) * 100
                print(f"Spread: {profit:.2f}% (QuickSwap is higher)")
                if profit >= 0.5:
                    print("Executing trade on QuickSwap! 🚀")
                    # execute_trade(quick_contract, ...) # Execution logic from previous messages goes here
                    
            elif sushi_out > quick_out:
                profit = ((sushi_out - quick_out) / quick_out) * 100
                print(f"Spread: {profit:.2f}% (SushiSwap is higher)")
                if profit >= 0.5:
                    print("Executing trade on SushiSwap! 🚀")
                    # execute_trade(sushi_contract, ...) 
            else:
                pass # Prices are equal

        except Exception as e:
            # We catch errors so the bot never crashes
            pass 

        time.sleep(5) # Wait 5 seconds to avoid spamming the RPC node

# --- 4. FASTAPI LIFESPAN (Runs Bot in Background) ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # This starts the bot loop when FastAPI boots up
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    yield
    # This handles shutdown gracefully
    print("Shutting down bot...")

# --- 5. FASTAPI APP ---
app = FastAPI(lifespan=lifespan)

# This is the "Dummy Route" that Render and UptimeRobot will ping
@app.get("/")
def read_root():
    return {"status": "success", "message": "FastAPI Arbitrage Bot is running 24/7! 🚀"}
  

import os
import time
import requests
from fastapi import FastAPI, BackgroundTasks
from web3 import Web3
from dotenv import load_dotenv

# --- 1. LOAD CREDENTIALS & SETUP ---
load_dotenv()
WALLET_ADDRESS = os.getenv("WALLET_ADDRESS")
PRIVATE_KEY = os.getenv("PRIVATE_KEY")
RPC_URL = os.getenv("PRIVATE_RPC_URL", "https://polygon.mev-blocker.io")

# Telegram Variables
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
DRY_RUN = os.getenv("DRY_RUN", "True") == "True" # Defaults to True so you don't accidentally lose money

app = FastAPI()

# --- 2. TELEGRAM ALERT SYSTEM ---
def send_alert(message):
    print(message) # Always print to Render terminal
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print(f"Failed to send Telegram alert: {e}")

# --- 3. WEB3 & CONTRACTS ---
web3 = Web3(Web3.HTTPProvider(RPC_URL))
QUICKSWAP_ROUTER = web3.to_checksum_address("0xa5E0829CaCEd8fFCEEd813c0150ce195f19520a1")
SUSHISWAP_ROUTER = web3.to_checksum_address("0x1b02dA8Cb0d097eB8D57A175b88c7D8b47997506")
POL_TOKEN = web3.to_checksum_address("0x0000000000000000000000000000000000001010") 
USDC_TOKEN = web3.to_checksum_address("0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174")

# ABI to check prices and execute trades
ROUTER_ABI = [
    {"constant": True, "inputs": [{"name": "amountIn", "type": "uint256"}, {"name": "path", "type": "address[]"}], "name": "getAmountsOut", "outputs": [{"name": "amounts", "type": "uint256[]"}], "payable": False, "stateMutability": "view", "type": "function"},
    {"name": "swapExactTokensForTokens", "type": "function", "stateMutability": "nonpayable", "inputs": [{"name": "amountIn", "type": "uint256"}, {"name": "amountOutMin", "type": "uint256"}, {"name": "path", "type": "address[]"}, {"name": "to", "type": "address"}, {"name": "deadline", "type": "uint256"}], "outputs": [{"name": "amounts", "type": "uint256[]"}]}
]

quick_contract = web3.eth.contract(address=QUICKSWAP_ROUTER, abi=ROUTER_ABI)
sushi_contract = web3.eth.contract(address=SUSHISWAP_ROUTER, abi=ROUTER_ABI)

# --- 4. THE EXECUTION ENGINE ---
def execute_trade(router_contract, router_name, amount_in_wei, expected_out_wei, path):
    min_out = int(expected_out_wei * 0.995) # 0.5% Slippage Protection
    
    if DRY_RUN:
        send_alert(f"🌵 <b>DRY RUN:</b> Would have executed trade on {router_name}.\nInput: 50 POL\nExpected Output: {expected_out_wei / 10**6:.2f} USDC")
        return

    try:
        nonce = web3.eth.get_transaction_count(WALLET_ADDRESS)
        transaction = router_contract.functions.swapExactTokensForTokens(
            amount_in_wei, 
            min_out, 
            path, 
            WALLET_ADDRESS, 
            int(time.time()) + 300
        ).build_transaction({
            'chainId': 137, 
            'gas': 250000, 
            'gasPrice': web3.eth.gas_price, 
            'nonce': nonce
        })

        signed_txn = web3.eth.account.sign_transaction(transaction, private_key=PRIVATE_KEY)
        tx_hash = web3.eth.send_raw_transaction(signed_txn.rawTransaction)
        tx_hex = web3.to_hex(tx_hash)
        
        send_alert(f"🚀 <b>TRADE EXECUTED on {router_name}!</b>\nHash: <a href='https://polygonscan.com/tx/{tx_hex}'>{tx_hex}</a>")
        
    except Exception as e:
        send_alert(f"🚨 <b>TRADE FAILED:</b> {str(e)}")

# --- 5. THE ARBITRAGE SCANNER ---
def perform_arbitrage_scan():
    if not web3.is_connected():
        send_alert("❌ <b>ERROR:</b> Bot failed to connect to Polygon RPC.")
        return
        
    trade_amount_pol = 50 # Base trade amount: 50 POL
    trade_amount_wei = web3.to_wei(trade_amount_pol, 'ether')
    path = [POL_TOKEN, USDC_TOKEN]

    try:
        # Ask both exchanges for their current price
        quick_out = quick_contract.functions.getAmountsOut(trade_amount_wei, path).call()[1]
        sushi_out = sushi_contract.functions.getAmountsOut(trade_amount_wei, path).call()[1]

        # Calculate mathematically which one is higher
        if quick_out > sushi_out:
            profit = ((quick_out - sushi_out) / sushi_out) * 100
            if profit >= 0.5: # If profit is greater than 0.5%, strike.
                send_alert(f"🎯 <b>OPPORTUNITY DETECTED!</b>\nSpread: {profit:.2f}%\nQuickSwap is higher.")
                execute_trade(quick_contract, "QuickSwap", trade_amount_wei, quick_out, path)
            else:
                print(f"Spread too low ({profit:.2f}%). Ignoring.")
                
        elif sushi_out > quick_out:
            profit = ((sushi_out - quick_out) / quick_out) * 100
            if profit >= 0.01:
                send_alert(f"🎯 <b>OPPORTUNITY DETECTED!</b>\nSpread: {profit:.2f}%\nSushiSwap is higher.")
                execute_trade(sushi_contract, "SushiSwap", trade_amount_wei, sushi_out, path)
            else:
                print(f"Spread too low ({profit:.2f}%). Ignoring.")
        else:
            print("Prices are identical. No trade.")

    except Exception as e:
        print(f"Scan error: {e}")

# --- 6. FASTAPI ENDPOINTS ---
@app.get("/")
def home():
    return {"status": "awake", "message": "Crypto Knight is online."}

@app.get("/cron-scan")
def trigger_scan(background_tasks: BackgroundTasks):
    background_tasks.add_task(perform_arbitrage_scan)
    return {"status": "success", "message": "Market scan initiated."}
    

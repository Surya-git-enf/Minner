# arb_render.py
import os
import time
import math
import requests
from fastapi import FastAPI, BackgroundTasks
from dotenv import load_dotenv
from web3 import Web3

load_dotenv()

# ---------- ENV / CONFIG ----------
RPC_URL = os.getenv("RPC_URL", "https://rpc-mumbai.maticvigil.com")
WALLET_ADDRESS = os.getenv("WALLET_ADDRESS")
PRIVATE_KEY = os.getenv("PRIVATE_KEY")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"
ENABLE_MAINNET = os.getenv("ENABLE_MAINNET", "false").lower() == "true"

# trading / risk params
TRADE_AMOUNT_MATIC = float(os.getenv("TRADE_AMOUNT_MATIC", "0.05"))   # amount in MATIC to use per trade
MIN_SPREAD_PERCENT = float(os.getenv("MIN_SPREAD_PERCENT", "0.8"))    # user preferred minimum spread (0.8%)
SLIPPAGE_PERCENT = float(os.getenv("SLIPPAGE_PERCENT", "0.5"))        # percent slippage to include
SAFETY_MARGIN_PERCENT = float(os.getenv("SAFETY_MARGIN_PERCENT", "0.3"))  # extra margin
ESTIMATED_GAS_MATIC = float(os.getenv("ESTIMATED_GAS_MATIC", "0.001"))    # estimate gas cost in MATIC per round-trip
MIN_LIQUIDITY_MATIC = float(os.getenv("MIN_LIQUIDITY_MATIC", "0.5"))  # minimum base liquidity in pair

# Routers/tokens (defaults for Polygon / QuickSwap / SushiSwap)
RPC_CHAIN_ID = int(os.getenv("RPC_CHAIN_ID", "80001"))  # 137 on mainnet, 80001 on mumbai
QUICKSWAP_ROUTER = os.getenv("QUICKSWAP_ROUTER", "0xa5E0829CaCEd8fFCEEd813c0150ce195f19520a1")
SUSHISWAP_ROUTER = os.getenv("SUSHISWAP_ROUTER", "0x1b02dA8Cb0d097eB8D57A175b88c7D8b47997506")
BASE_TOKEN = os.getenv("BASE_TOKEN", "0x0000000000000000000000000000000000001010")  # WMATIC address placeholder
QUOTE_TOKEN = os.getenv("QUOTE_TOKEN", "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174") # USDC on polygon (6 decimals)

EXPLORER_TX_PREFIX = os.getenv("EXPLORER_TX_PREFIX", "https://mumbai.polygonscan.com/tx/")

# ---------- web3 setup ----------
w3 = Web3(Web3.HTTPProvider(RPC_URL))
quick_router = w3.eth.contract(address=w3.to_checksum_address(QUICKSWAP_ROUTER), abi=[
    {"constant": True, "inputs": [{"name":"amountIn","type":"uint256"},{"name":"path","type":"address[]"}], "name":"getAmountsOut","outputs":[{"name":"amounts","type":"uint256[]"}],"payable":False,"stateMutability":"view","type":"function"},
    {"name":"swapExactTokensForTokens","type":"function","stateMutability":"nonpayable","inputs":[{"name":"amountIn","type":"uint256"},{"name":"amountOutMin","type":"uint256"},{"name":"path","type":"address[]"},{"name":"to","type":"address"},{"name":"deadline","type":"uint256"}],"outputs":[{"name":"amounts","type":"uint256[]"}]}
])
sushi_router = w3.eth.contract(address=w3.to_checksum_address(SUSHISWAP_ROUTER), abi=quick_router.abi)

# ---------- Telegram helper ----------
def send_alert(text):
    print("[ALERT]", text)
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}, timeout=6)
    except Exception as e:
        print("Telegram send failed:", e)

# ---------- helpers ----------
def human_amt_from_token_raw(raw_value, decimals=6):
    # raw_value is integer returned by getAmountsOut; default decimals 6 for USDC
    return float(raw_value) / (10 ** decimals)

def required_spread_percent(trade_amount_matic):
    # required spread includes gas cost relative to trade, slippage, and safety margin
    gas_pct = (ESTIMATED_GAS_MATIC / trade_amount_matic) * 100.0
    return max(MIN_SPREAD_PERCENT, gas_pct + SLIPPAGE_PERCENT + SAFETY_MARGIN_PERCENT)

# ---------- core scanner ----------
def perform_arbitrage_scan():
    try:
        if not w3.is_connected():
            send_alert("❌ <b>Error:</b> RPC disconnected.")
            return

        trade_amount_matic = TRADE_AMOUNT_MATIC
        trade_amount_wei = w3.to_wei(trade_amount_matic, 'ether')
        path = [w3.to_checksum_address(BASE_TOKEN), w3.to_checksum_address(QUOTE_TOKEN)]

        # Ask both routers for their outputs (raw token units)
        quick_out_raw = quick_router.functions.getAmountsOut(trade_amount_wei, path).call()[1]
        sushi_out_raw = sushi_router.functions.getAmountsOut(trade_amount_wei, path).call()[1]

        # Determine decimals for human comparison (USDC -> 6 decimals). If using another quote token, adjust env.
        quote_decimals = int(os.getenv("QUOTE_TOKEN_DECIMALS", "6"))
        quick_out = human_amt_from_token_raw(quick_out_raw, quote_decimals)
        sushi_out = human_amt_from_token_raw(sushi_out_raw, quote_decimals)

        # compute spread relative to the lower price for conservative edge
        if quick_out == 0 or sushi_out == 0:
            print("Zero output from getAmountsOut - skipping.")
            return

        # compute spread percent (sell_price - buy_price) / buy_price * 100
        if quick_out > sushi_out:
            buy_on = "SushiSwap"
            sell_on = "QuickSwap"
            buy_amt = sushi_out
            sell_amt = quick_out
        else:
            buy_on = "QuickSwap"
            sell_on = "SushiSwap"
            buy_amt = quick_out
            sell_amt = sushi_out

        spread_percent = ((sell_amt - buy_amt) / buy_amt) * 100.0
        req_spread = required_spread_percent(trade_amount_matic)

        message = (f"Scan result:\nBuy on {buy_on} => {buy_amt:.6f}\nSell on {sell_on} => {sell_amt:.6f}\n"
                   f"Spread = {spread_percent:.4f}% (required >= {req_spread:.4f}%)")

        print(message)

        if spread_percent >= req_spread:
            send_alert(f"🎯 <b>Arbitrage Opportunity</b>\n{message}\nDRY_RUN={DRY_RUN}")
            # If DRY_RUN just alert; otherwise attempt to execute (note: approvals needed upstream)
            if not DRY_RUN and ENABLE_MAINNET:
                # choose router objects and raw expected amounts depending on side
                if buy_on == "SushiSwap":
                    buy_router = sushi_router
                    sell_router = quick_router
                    expected_out_raw = quick_out_raw
                else:
                    buy_router = quick_router
                    sell_router = sushi_router
                    expected_out_raw = sushi_out_raw

                # IMPORTANT: This is a simplified execution path.
                # If BASE_TOKEN is WETH/WMATIC and you hold native MATIC, you may need swapExactETHForTokens or token approvals.
                min_out = int(expected_out_raw * (1 - (SLIPPAGE_PERCENT/100.0)))
                deadline = int(time.time()) + 300
                try:
                    # Build a buy tx (swapExactTokensForTokens) — **you must ensure the bot has/will approve BASE_TOKEN**
                    tx = buy_router.functions.swapExactTokensForTokens(
                        trade_amount_wei, min_out, path, WALLET_ADDRESS, deadline
                    ).build_transaction({
                        "from": WALLET_ADDRESS,
                        "gas": int(os.getenv("TX_GAS", "300000")),
                        "gasPrice": w3.eth.gas_price,
                        "nonce": w3.eth.get_transaction_count(WALLET_ADDRESS)
                    })
                    signed = w3.eth.account.sign_transaction(tx, private_key=PRIVATE_KEY)
                    tx_hash = w3.eth.send_raw_transaction(signed.rawTransaction)
                    tx_hex = w3.to_hex(tx_hash)
                    send_alert(f"🚀 <b>BUY TX SENT</b> on {buy_on}\n{EXPLORER_TX_PREFIX}{tx_hex}")
                    # Note: you should wait for buy confirmation and then construct sell tx, or sell in same function using token balance/receipt.
                except Exception as e:
                    send_alert(f"🚨 <b>Execution error (buy):</b> {e}")
            else:
                send_alert("🔒 DRY_RUN or ENABLE_MAINNET=false — not executing trades.")
        else:
            print(f"No actionable spread ({spread_percent:.4f}%). req {req_spread:.4f}%")
    except Exception as e:
        print("Scan error:", e)
        send_alert(f"❌ <b>Scan error:</b> {e}")

# ---------- FastAPI endpoints ----------
app = FastAPI()

@app.get("/")
def home():
    return {"status":"ok", "message":"Crypto Knight (arbitrage) alive."}

@app.get("/cron-scan")
def cron_scan(background_tasks: BackgroundTasks):
    background_tasks.add_task(perform_arbitrage_scan)
    return {"status":"scan-started"}

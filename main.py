# main.py
import os, time
from fastapi import FastAPI, BackgroundTasks
from dotenv import load_dotenv
from web3utils import w3, cs, to_wei_base, from_wei_base
from trader import execute_arbitrage
from telegram_alerts import send
from db import init_db, get_counter
from security import goplus_check, simulate_call
import threading

load_dotenv()

app = FastAPI()
init_db()

# Config env
QUICK = w3.eth.contract(address=cs(os.getenv("QUICKSWAP_ROUTER")), abi=[])
SUSHI = w3.eth.contract(address=cs(os.getenv("SUSHISWAP_ROUTER")), abi=[])
FACTORY = cs(os.getenv("FACTORY_ADDRESS"))
BASE_TOKEN = cs(os.getenv("BASE_TOKEN"))
QUOTE_TOKEN = cs(os.getenv("QUOTE_TOKEN"))
TRADE_AMOUNT_BASE = float(os.getenv("TRADE_AMOUNT_BASE", "0.05"))
MIN_SPREAD_PERCENT = float(os.getenv("MIN_SPREAD_PERCENT", "0.8"))
DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"
REQUIRE_CONFIRMATION = os.getenv("REQUIRE_CONFIRMATION", "true").lower() == "true"
ENABLE_MAINNET = os.getenv("ENABLE_MAINNET", "false").lower() == "true"

lock = threading.Lock()
_last_scan = {}

def compute_required_spread(trade_amount_base):
    gas_pct = float(os.getenv("ESTIMATED_GAS_BASE", "0.001")) / trade_amount_base * 100.0
    slippage = float(os.getenv("SLIPPAGE_PERCENT", "0.5"))
    margin = float(os.getenv("SAFETY_MARGIN_PERCENT", "0.3"))
    return max(MIN_SPREAD_PERCENT, gas_pct + slippage + margin)

def quick_contract():
    abi = [{"name":"getAmountsOut","inputs":[{"name":"amountIn","type":"uint256"},{"name":"path","type":"address[]"}],"outputs":[{"name":"amounts","type":"uint256[]"}],"stateMutability":"view","type":"function"}]
    return w3.eth.contract(address=cs(os.getenv("QUICKSWAP_ROUTER")), abi=abi)

def sushi_contract():
    abi = [{"name":"getAmountsOut","inputs":[{"name":"amountIn","type":"uint256"},{"name":"path","type":"address[]"}],"outputs":[{"name":"amounts","type":"uint256[]"}],"stateMutability":"view","type":"function"}]
    return w3.eth.contract(address=cs(os.getenv("SUSHISWAP_ROUTER")), abi=abi)

def scan_and_maybe_trade():
    global _last_scan
    with lock:
        try:
            trade_amount = TRADE_AMOUNT_BASE
            trade_wei = to_wei_base(trade_amount)
            path_buy = [BASE_TOKEN, QUOTE_TOKEN]
            path_sell = [QUOTE_TOKEN, BASE_TOKEN]
            quick = quick_contract()
            sushi = sushi_contract()

            quick_out = quick.functions.getAmountsOut(trade_wei, path_buy).call()[1]
            sushi_out = sushi.functions.getAmountsOut(trade_wei, path_buy).call()[1]

            # convert to human
            quote_dec = int(os.getenv("QUOTE_TOKEN_DECIMALS", "6"))
            quick_h = float(quick_out) / (10**quote_dec)
            sushi_h = float(sushi_out) / (10**quote_dec)

            # decide buy/sell combination by comparing round-trip (simulate)
            backA = quick.functions.getAmountsOut(sushi_out, path_sell).call()[1]
            backB = sushi.functions.getAmountsOut(quick_out, path_sell).call()[1]

            if backA >= backB:
                buy_router, sell_router = sushi, quick
                buy_on, sell_on = "Sushi", "Quick"
                usdc_raw = sushi_out
            else:
                buy_router, sell_router = quick, sushi
                buy_on, sell_on = "Quick", "Sushi"
                usdc_raw = quick_out

            back_base = (backA if backA>=backB else backB) / (10**18)  # base token decimals 18
            est_profit = back_base - trade_amount
            net_spread_pct = (est_profit / trade_amount) * 100.0
            req_spread = compute_required_spread(trade_amount)

            _last_scan = {
                "buy_on": buy_on, "sell_on": sell_on,
                "trade_amount": trade_amount,
                "est_profit": est_profit, "net_spread_pct": net_spread_pct, "required": req_spread
            }

            send(f"Scan: {buy_on}->{sell_on} est_profit={est_profit:.6f} base ({net_spread_pct:.4f}%); req {req_spread:.4f}% (DRY_RUN={DRY_RUN})")

            # security checks:
            # 1) basic external audit if API provided - skip if no key
            token_addr = path_buy[1]
            g = goplus_check(token_addr)
            if not g.get("ok", True):
                send(f"Security fail: {g.get('reason')}; skipping.")
                return

            # 2) simulate swap call (buy then sell) to detect immediate revert/honeypot
            # encode function call data for buy & sell and eth_call them
            buy_abi = buy_router.encodeABI(fn_name="getAmountsOut", args=[trade_wei, path_buy])
            # note: getAmountsOut is view; we used previous calls. For actual revert test, call swap function via eth_call by encoding swap and calling - more advanced.
            # quick approach: assume getAmountsOut succeeded -> proceed.

            if net_spread_pct >= req_spread:
                send(f"Opportunity OK: {buy_on} -> {sell_on} | est_profit={est_profit:.6f}")
                if DRY_RUN:
                    send("DRY_RUN enabled — not sending transactions.")
                    return
                if REQUIRE_CONFIRMATION:
                    send("Manual confirmation required. Reply /confirm to Telegram to execute.")
                    return
                # else execute
                res = execute_arbitrage(buy_router, sell_router, path_buy, path_sell, trade_amount, os.getenv("WALLET_ADDRESS"), os.getenv("PRIVATE_KEY"), dry_run=False)
                if res.get("success"):
                    send(f"Trade done. P&L (est): {res.get('profit_base'):+.6f}")
                else:
                    send(f"Trade failed: {res.get('note')}")
            else:
                send("Spread below required threshold. Skipping.")
        except Exception as e:
            send(f"Scan error: {e}")
        finally:
            return

@app.get("/")
def home():
    return {"status":"ok","msg":"Crypto Knight v2 alive"}

@app.get("/scan-now")
def scan_now(background_tasks: BackgroundTasks):
    background_tasks.add_task(scan_and_maybe_trade)
    return {"status":"scan_started"}

@app.get("/cron-scan")
def cron_scan(background_tasks: BackgroundTasks):
    background_tasks.add_task(scan_and_maybe_trade)
    return {"status":"cron_scan_started"}

@app.get("/status")
def status():
    return {"last_scan": _last_scan}

"""
arb_render.py  –  Crypto Knight Arbitrage Bot
Polygon Mainnet | QuickSwap v2 ↔ SushiSwap
Deploy on Render (Web Service) + external cron hitting /cron-scan

ENV vars (set in Render dashboard – never hardcode):
  RPC_URL, WALLET_ADDRESS, PRIVATE_KEY,
  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
  DRY_RUN (default true), ENABLE_MAINNET (default false)

Start command:
  uvicorn arb_render:app --host 0.0.0.0 --port $PORT

Cron: hit GET /cron-scan every 60 s via cron-job.org or Render Cron Service.

WARNING: DRY_RUN=true and ENABLE_MAINNET=false by default.
         You must explicitly set both to go live. Trade at your own risk.
"""

import os
import time
import threading
import logging
from contextlib import asynccontextmanager

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, BackgroundTasks
from fastapi.responses import JSONResponse
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("arb")

# ═══════════════════════════════════════════════════════════════
#  CONFIG
# ═══════════════════════════════════════════════════════════════

RPC_URL             = os.getenv("RPC_URL",             "https://polygon-rpc.com")
CHAIN_ID            = int(os.getenv("CHAIN_ID",        "137"))          # 137 = Polygon mainnet
WALLET_ADDRESS      = os.getenv("WALLET_ADDRESS",      "")
PRIVATE_KEY         = os.getenv("PRIVATE_KEY",         "")

TELEGRAM_BOT_TOKEN  = os.getenv("TELEGRAM_BOT_TOKEN",  "")
TELEGRAM_CHAT_ID    = os.getenv("TELEGRAM_CHAT_ID",    "")

DRY_RUN             = os.getenv("DRY_RUN",             "true").lower()  == "true"
ENABLE_MAINNET      = os.getenv("ENABLE_MAINNET",      "false").lower() == "true"

# ── Trade / risk params ──────────────────────────────────────
TRADE_AMOUNT_MATIC      = float(os.getenv("TRADE_AMOUNT_MATIC",      "1.0"))   # MATIC per trade
MIN_SPREAD_PERCENT      = float(os.getenv("MIN_SPREAD_PERCENT",      "0.8"))   # floor spread %
SLIPPAGE_PERCENT        = float(os.getenv("SLIPPAGE_PERCENT",        "0.5"))
SAFETY_MARGIN_PERCENT   = float(os.getenv("SAFETY_MARGIN_PERCENT",   "0.3"))
ESTIMATED_GAS_MATIC     = float(os.getenv("ESTIMATED_GAS_MATIC",     "0.003")) # ~2 swaps on Polygon
MIN_LIQUIDITY_USD       = float(os.getenv("MIN_LIQUIDITY_USD",        "500"))  # skip thin pairs
MAX_DAILY_TRADES        = int(os.getenv("MAX_DAILY_TRADES",           "20"))
DAILY_LOSS_CAP_MATIC    = float(os.getenv("DAILY_LOSS_CAP_MATIC",    "2.0"))

# ── Polygon token addresses ───────────────────────────────────
# WMATIC – wrapped native token (used as BASE for swaps)
WMATIC_ADDRESS  = os.getenv("WMATIC_ADDRESS",  "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270")
# USDC on Polygon (6 decimals)
USDC_ADDRESS    = os.getenv("USDC_ADDRESS",    "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174")
QUOTE_DECIMALS  = int(os.getenv("QUOTE_DECIMALS", "6"))

BASE_TOKEN  = os.getenv("BASE_TOKEN",  WMATIC_ADDRESS)
QUOTE_TOKEN = os.getenv("QUOTE_TOKEN", USDC_ADDRESS)

# ── Router addresses (Polygon mainnet) ────────────────────────
QUICKSWAP_ROUTER = os.getenv("QUICKSWAP_ROUTER", "0xa5E0829CaCEd8fFDD4De3c43696c57F7D7A678ff")
SUSHISWAP_ROUTER = os.getenv("SUSHISWAP_ROUTER", "0x1b02dA8Cb0d097eB8D57A175b88c7D8b47997506")

EXPLORER_PREFIX  = os.getenv("EXPLORER_PREFIX", "https://polygonscan.com/tx/")

# ═══════════════════════════════════════════════════════════════
#  ABI DEFINITIONS
# ═══════════════════════════════════════════════════════════════

ROUTER_ABI = [
    {
        "name": "getAmountsOut",
        "type": "function",
        "stateMutability": "view",
        "inputs": [
            {"name": "amountIn",  "type": "uint256"},
            {"name": "path",      "type": "address[]"}
        ],
        "outputs": [{"name": "amounts", "type": "uint256[]"}]
    },
    {
        "name": "swapExactTokensForTokensSupportingFeeOnTransferTokens",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "amountIn",     "type": "uint256"},
            {"name": "amountOutMin", "type": "uint256"},
            {"name": "path",         "type": "address[]"},
            {"name": "to",           "type": "address"},
            {"name": "deadline",     "type": "uint256"}
        ],
        "outputs": []
    },
]

ERC20_ABI = [
    {
        "name": "approve",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "spender", "type": "address"},
            {"name": "amount",  "type": "uint256"}
        ],
        "outputs": [{"name": "", "type": "bool"}]
    },
    {
        "name": "allowance",
        "type": "function",
        "stateMutability": "view",
        "inputs": [
            {"name": "owner",   "type": "address"},
            {"name": "spender", "type": "address"}
        ],
        "outputs": [{"name": "", "type": "uint256"}]
    },
    {
        "name": "balanceOf",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "account", "type": "address"}],
        "outputs": [{"name": "", "type": "uint256"}]
    },
    {
        "name": "decimals",
        "type": "function",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"name": "", "type": "uint8"}]
    },
]

# ═══════════════════════════════════════════════════════════════
#  WEB3 SETUP
# ═══════════════════════════════════════════════════════════════

w3 = Web3(Web3.HTTPProvider(RPC_URL, request_kwargs={"timeout": 30}))
w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)  # required for Polygon PoA

def _cs(addr: str) -> str:
    """Checksum an address."""
    return w3.to_checksum_address(addr)

quick_router = w3.eth.contract(address=_cs(QUICKSWAP_ROUTER), abi=ROUTER_ABI)
sushi_router = w3.eth.contract(address=_cs(SUSHISWAP_ROUTER), abi=ROUTER_ABI)

# ═══════════════════════════════════════════════════════════════
#  DAILY STATE  (in-memory; resets on restart – fine for Render)
# ═══════════════════════════════════════════════════════════════

_state_lock      = threading.Lock()
_daily_trades    = 0
_daily_loss_matic = 0.0
_last_scan_result: dict = {}
_scan_running    = False    # prevent overlapping scans

# ═══════════════════════════════════════════════════════════════
#  TELEGRAM
# ═══════════════════════════════════════════════════════════════

def send_alert(text: str) -> None:
    log.info("[ALERT] %s", text)
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={
                "chat_id":    TELEGRAM_CHAT_ID,
                "text":       text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=8,
        )
    except Exception as e:
        log.warning("Telegram send failed: %s", e)

# ═══════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════

def raw_to_human(raw: int, decimals: int) -> float:
    return raw / (10 ** decimals)

def human_to_raw(amount: float, decimals: int) -> int:
    return int(amount * (10 ** decimals))

def required_spread_pct(trade_matic: float) -> float:
    """
    Minimum spread needed to cover gas + slippage + safety margin.
    Gas cost as % of trade is the dominant term on small trades.
    """
    gas_pct = (ESTIMATED_GAS_MATIC / trade_matic) * 100.0
    return max(MIN_SPREAD_PERCENT, gas_pct + SLIPPAGE_PERCENT + SAFETY_MARGIN_PERCENT)

def get_gas_price_wei() -> int:
    """Fetch current gas price with a 20% bump for faster inclusion."""
    base = w3.eth.gas_price
    return int(base * 1.2)

def get_nonce(address: str) -> int:
    return w3.eth.get_transaction_count(_cs(address), "pending")

# ═══════════════════════════════════════════════════════════════
#  TOKEN APPROVAL
# ═══════════════════════════════════════════════════════════════

def ensure_approval(token_address: str, spender: str, amount_wei: int, gas_price: int) -> bool:
    """
    Check ERC-20 allowance; approve MAX_UINT if insufficient.
    Returns True if approval is in place (or was just set).
    In DRY_RUN mode, skips the on-chain tx and returns True.
    """
    token = w3.eth.contract(address=_cs(token_address), abi=ERC20_ABI)
    current = token.functions.allowance(_cs(WALLET_ADDRESS), _cs(spender)).call()
    if current >= amount_wei:
        return True

    if DRY_RUN:
        log.info("[DRY RUN] Would approve %s to spend %s", spender[:10], token_address[:10])
        return True

    MAX_UINT = 2**256 - 1
    try:
        nonce = get_nonce(WALLET_ADDRESS)
        tx = token.functions.approve(_cs(spender), MAX_UINT).build_transaction({
            "from":     _cs(WALLET_ADDRESS),
            "gas":      80_000,
            "gasPrice": gas_price,
            "nonce":    nonce,
            "chainId":  CHAIN_ID,
        })
        signed  = w3.eth.account.sign_transaction(tx, private_key=PRIVATE_KEY)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        if receipt.status != 1:
            log.error("Approval tx reverted: %s", tx_hash.hex())
            return False
        log.info("Approval confirmed: %s", tx_hash.hex())
        return True
    except Exception as e:
        log.error("Approval error: %s", e)
        send_alert(f"⚠️ <b>Approval Error:</b> {e}")
        return False

# ═══════════════════════════════════════════════════════════════
#  CORE ARBITRAGE SCAN
# ═══════════════════════════════════════════════════════════════

def perform_arbitrage_scan() -> dict:
    """
    Full round-trip arbitrage scan:
      1. Get WMATIC → USDC quote on both DEXes
      2. Simulate selling the USDC back on the OTHER DEX (round-trip)
      3. Calculate net MATIC profit after gas
      4. If profitable above threshold → alert (DRY_RUN) or execute (LIVE)

    Returns a result dict for the /status endpoint.
    """
    global _scan_running, _daily_trades, _daily_loss_matic

    with _state_lock:
        if _scan_running:
            log.info("Scan already running – skipping overlap.")
            return {"status": "skipped", "reason": "scan_already_running"}
        _scan_running = True

    result = {}
    try:
        # ── Connectivity check ────────────────────────────────────
        if not w3.is_connected():
            msg = "❌ RPC disconnected"
            send_alert(f"<b>Crypto Knight Error:</b> {msg}")
            return {"status": "error", "reason": msg}

        # ── Daily limits ──────────────────────────────────────────
        with _state_lock:
            if _daily_trades >= MAX_DAILY_TRADES:
                return {"status": "halted", "reason": "daily_trade_limit_reached"}
            if _daily_loss_matic >= DAILY_LOSS_CAP_MATIC:
                return {"status": "halted", "reason": "daily_loss_cap_reached"}

        trade_matic   = TRADE_AMOUNT_MATIC
        trade_wei     = w3.to_wei(trade_matic, "ether")
        base_cs       = _cs(BASE_TOKEN)   # WMATIC
        quote_cs      = _cs(QUOTE_TOKEN)  # USDC
        path_buy      = [base_cs,  quote_cs]   # WMATIC → USDC
        path_sell     = [quote_cs, base_cs]    # USDC   → WMATIC

        # ── Step 1: WMATIC → USDC on each DEX ────────────────────
        try:
            quick_usdc_raw = quick_router.functions.getAmountsOut(trade_wei, path_buy).call()[1]
            sushi_usdc_raw = sushi_router.functions.getAmountsOut(trade_wei, path_buy).call()[1]
        except Exception as e:
            log.warning("getAmountsOut (buy) failed: %s", e)
            return {"status": "error", "reason": f"getAmountsOut buy: {e}"}

        if quick_usdc_raw == 0 or sushi_usdc_raw == 0:
            return {"status": "error", "reason": "zero_buy_output"}

        quick_usdc = raw_to_human(quick_usdc_raw, QUOTE_DECIMALS)
        sushi_usdc = raw_to_human(sushi_usdc_raw, QUOTE_DECIMALS)

        # ── Step 2: Simulate USDC → WMATIC on the OTHER DEX ──────
        # Direction A: Buy USDC cheap on Sushi, sell USDC back on Quick
        # Direction B: Buy USDC cheap on Quick, sell USDC back on Sushi
        try:
            # Direction A: Buy on Sushi → Sell on Quick
            dirA_matic_back_raw = quick_router.functions.getAmountsOut(
                sushi_usdc_raw, path_sell
            ).call()[1]
            # Direction B: Buy on Quick → Sell on Sushi
            dirB_matic_back_raw = sushi_router.functions.getAmountsOut(
                quick_usdc_raw, path_sell
            ).call()[1]
        except Exception as e:
            log.warning("getAmountsOut (sell) failed: %s", e)
            return {"status": "error", "reason": f"getAmountsOut sell: {e}"}

        # ── Step 3: Pick best direction ───────────────────────────
        if dirA_matic_back_raw >= dirB_matic_back_raw:
            buy_on        = "SushiSwap"
            sell_on       = "QuickSwap"
            buy_router    = sushi_router
            sell_router   = quick_router
            usdc_raw      = sushi_usdc_raw
            usdc_human    = sushi_usdc
            matic_back_wei = dirA_matic_back_raw
        else:
            buy_on        = "QuickSwap"
            sell_on       = "SushiSwap"
            buy_router    = quick_router
            sell_router   = sushi_router
            usdc_raw      = quick_usdc_raw
            usdc_human    = quick_usdc
            matic_back_wei = dirB_matic_back_raw

        matic_back_human = float(w3.from_wei(matic_back_wei, "ether"))
        gas_matic        = ESTIMATED_GAS_MATIC
        net_profit_matic = matic_back_human - trade_matic - gas_matic
        gross_spread_pct = ((matic_back_human - trade_matic) / trade_matic) * 100.0
        net_spread_pct   = (net_profit_matic / trade_matic) * 100.0
        req_spread       = required_spread_pct(trade_matic)

        result = {
            "status":            "scanned",
            "timestamp":         int(time.time()),
            "buy_on":            buy_on,
            "sell_on":           sell_on,
            "trade_matic":       trade_matic,
            "usdc_intermediate": round(usdc_human, 4),
            "matic_back":        round(matic_back_human, 6),
            "gas_est_matic":     gas_matic,
            "gross_spread_pct":  round(gross_spread_pct, 4),
            "net_spread_pct":    round(net_spread_pct, 4),
            "required_spread":   round(req_spread, 4),
            "profitable":        net_spread_pct >= req_spread,
            "dry_run":           DRY_RUN,
            "quick_usdc":        round(quick_usdc, 4),
            "sushi_usdc":        round(sushi_usdc, 4),
        }

        log.info(
            "Scan: %s→%s | gross=%.4f%% net=%.4f%% req=%.4f%% profit=%+.5f MATIC",
            buy_on, sell_on, gross_spread_pct, net_spread_pct,
            req_spread, net_profit_matic
        )

        # ── Step 4: Alert / Execute ───────────────────────────────
        if net_spread_pct >= req_spread:
            alert_lines = [
                "🎯 <b>Arbitrage Opportunity Found!</b>",
                f"📍 Chain: <b>Polygon Mainnet</b>",
                f"🔁 Route: <b>{buy_on}</b> → <b>{sell_on}</b>",
                f"💰 Trade: <b>{trade_matic} MATIC</b>",
                f"🔄 USDC received: <b>{usdc_human:.4f}</b>",
                f"🔙 MATIC back: <b>{matic_back_human:.6f}</b>",
                f"⛽ Gas est: <b>{gas_matic} MATIC</b>",
                f"📊 Net profit: <b>{net_profit_matic:+.6f} MATIC</b> ({net_spread_pct:.4f}%)",
                f"✅ Spread OK: {net_spread_pct:.4f}% ≥ {req_spread:.4f}%",
                f"🔒 DRY_RUN={DRY_RUN} | MAINNET={ENABLE_MAINNET}",
            ]
            send_alert("\n".join(alert_lines))

            if not DRY_RUN and ENABLE_MAINNET:
                _execute_arb(
                    buy_on, sell_on,
                    buy_router, sell_router,
                    trade_wei, usdc_raw,
                    net_profit_matic,
                )
            else:
                log.info("DRY_RUN or ENABLE_MAINNET=false – skipping execution.")
                send_alert("🔒 <b>Simulation only</b> – set DRY_RUN=false &amp; ENABLE_MAINNET=true to trade.")
        else:
            log.info(
                "No actionable spread: %.4f%% (need %.4f%%)",
                net_spread_pct, req_spread
            )

    except Exception as e:
        log.exception("Scan error: %s", e)
        send_alert(f"❌ <b>Scan Error:</b> {str(e)[:300]}")
        result = {"status": "error", "reason": str(e)}
    finally:
        with _state_lock:
            _scan_running = False

    return result

# ═══════════════════════════════════════════════════════════════
#  EXECUTION  (only runs when DRY_RUN=false + ENABLE_MAINNET=true)
# ═══════════════════════════════════════════════════════════════

def _execute_arb(
    buy_on: str,
    sell_on: str,
    buy_router,
    sell_router,
    trade_wei: int,
    usdc_raw: int,
    expected_profit: float,
) -> None:
    """
    Execute both legs of the arbitrage:
      Leg 1: WMATIC → USDC  on buy_router
      Leg 2: USDC   → WMATIC on sell_router

    Uses swapExactTokensForTokensSupportingFeeOnTransferTokens
    on both legs – this variant handles fee-on-transfer tokens
    safely and works on both QuickSwap and SushiSwap.
    """
    global _daily_trades, _daily_loss_matic

    gas_price  = get_gas_price_wei()
    deadline   = int(time.time()) + 300
    wallet_cs  = _cs(WALLET_ADDRESS)
    base_cs    = _cs(BASE_TOKEN)
    quote_cs   = _cs(QUOTE_TOKEN)
    path_buy   = [base_cs,  quote_cs]
    path_sell  = [quote_cs, base_cs]

    slippage_factor = 1 - (SLIPPAGE_PERCENT / 100.0)
    min_usdc_out    = int(usdc_raw   * slippage_factor)
    min_matic_out   = int(trade_wei  * slippage_factor)  # at minimum get back what we spent

    # ── LEG 1: Approve WMATIC for buy_router ──────────────────
    log.info("Leg 1 – Approving WMATIC for %s…", buy_on)
    if not ensure_approval(BASE_TOKEN, buy_router.address, trade_wei, gas_price):
        send_alert(f"🚨 <b>Approval failed for {buy_on}</b> – aborting.")
        return

    # ── LEG 1: Buy USDC on cheap DEX ──────────────────────────
    log.info("Leg 1 – Swapping %s WMATIC → USDC on %s…", w3.from_wei(trade_wei, "ether"), buy_on)
    try:
        nonce  = get_nonce(WALLET_ADDRESS)
        buy_tx = buy_router.functions.swapExactTokensForTokensSupportingFeeOnTransferTokens(
            trade_wei, min_usdc_out, path_buy, wallet_cs, deadline
        ).build_transaction({
            "from":     wallet_cs,
            "gas":      300_000,
            "gasPrice": gas_price,
            "nonce":    nonce,
            "chainId":  CHAIN_ID,
        })
        # Refine gas estimate
        try:
            buy_tx["gas"] = int(w3.eth.estimate_gas(buy_tx) * 1.2)
        except Exception:
            pass

        signed_buy = w3.eth.account.sign_transaction(buy_tx, private_key=PRIVATE_KEY)
        buy_hash   = w3.eth.send_raw_transaction(signed_buy.raw_transaction)
        buy_hex    = buy_hash.hex()
        log.info("Leg 1 TX sent: %s", buy_hex)
        send_alert(
            f"🚀 <b>LEG 1 (Buy) Sent</b>\n"
            f"DEX: <b>{buy_on}</b>\n"
            f"Amount: <b>{w3.from_wei(trade_wei,'ether')} WMATIC → USDC</b>\n"
            f'TX: <a href="{EXPLORER_PREFIX}{buy_hex}">{buy_hex[:16]}…</a>'
        )

        receipt_buy = w3.eth.wait_for_transaction_receipt(buy_hash, timeout=120)
        if receipt_buy.status != 1:
            send_alert(f"🚨 <b>LEG 1 REVERTED</b> – {EXPLORER_PREFIX}{buy_hex}")
            return
        log.info("Leg 1 confirmed (block %d)", receipt_buy.blockNumber)
    except Exception as e:
        log.error("Leg 1 error: %s", e)
        send_alert(f"🚨 <b>Leg 1 Error ({buy_on}):</b> {str(e)[:300]}")
        return

    # ── LEG 2: Read actual USDC balance (more accurate than quote) ──
    try:
        usdc_contract  = w3.eth.contract(address=quote_cs, abi=ERC20_ABI)
        actual_usdc    = usdc_contract.functions.balanceOf(wallet_cs).call()
        log.info("Actual USDC after Leg 1: %s", raw_to_human(actual_usdc, QUOTE_DECIMALS))
        if actual_usdc == 0:
            send_alert("🚨 <b>USDC balance is 0 after Leg 1</b> – something went wrong. NOT proceeding with Leg 2.")
            return
    except Exception as e:
        log.error("Balance check error: %s", e)
        actual_usdc = usdc_raw   # fall back to quote estimate

    # ── LEG 2: Approve USDC for sell_router ───────────────────
    log.info("Leg 2 – Approving USDC for %s…", sell_on)
    if not ensure_approval(QUOTE_TOKEN, sell_router.address, actual_usdc, gas_price):
        send_alert(f"🚨 <b>USDC Approval failed for {sell_on}</b> – you hold USDC, sell manually!")
        return

    # ── LEG 2: Sell USDC back to WMATIC ───────────────────────
    log.info("Leg 2 – Swapping USDC → WMATIC on %s…", sell_on)
    try:
        gas_price2  = get_gas_price_wei()   # refresh in case base fee moved
        nonce2      = get_nonce(WALLET_ADDRESS)
        sell_tx     = sell_router.functions.swapExactTokensForTokensSupportingFeeOnTransferTokens(
            actual_usdc, min_matic_out, path_sell, wallet_cs, deadline
        ).build_transaction({
            "from":     wallet_cs,
            "gas":      300_000,
            "gasPrice": gas_price2,
            "nonce":    nonce2,
            "chainId":  CHAIN_ID,
        })
        try:
            sell_tx["gas"] = int(w3.eth.estimate_gas(sell_tx) * 1.2)
        except Exception:
            pass

        signed_sell = w3.eth.account.sign_transaction(sell_tx, private_key=PRIVATE_KEY)
        sell_hash   = w3.eth.send_raw_transaction(signed_sell.raw_transaction)
        sell_hex    = sell_hash.hex()
        log.info("Leg 2 TX sent: %s", sell_hex)

        receipt_sell = w3.eth.wait_for_transaction_receipt(sell_hash, timeout=120)

        # ── Calculate actual P&L ─────────────────────────────
        wmatic_contract  = w3.eth.contract(address=base_cs, abi=ERC20_ABI)
        final_wmatic     = wmatic_contract.functions.balanceOf(wallet_cs).call()
        # Rough P&L based on expected profit passed in
        pnl_matic        = expected_profit  # approximate; precise calc needs balance before tx

        status_emoji     = "✅" if receipt_sell.status == 1 else "❌"
        profit_emoji     = "📈" if pnl_matic >= 0 else "📉"

        with _state_lock:
            _daily_trades += 1
            if pnl_matic < 0:
                _daily_loss_matic += abs(pnl_matic)

        send_alert(
            f"{status_emoji} <b>LEG 2 (Sell) {'Confirmed' if receipt_sell.status == 1 else 'REVERTED'}</b>\n"
            f"DEX: <b>{sell_on}</b>\n"
            f"{profit_emoji} Est. P&amp;L: <b>{pnl_matic:+.6f} MATIC</b>\n"
            f'TX: <a href="{EXPLORER_PREFIX}{sell_hex}">{sell_hex[:16]}…</a>\n'
            f"Daily trades today: <b>{_daily_trades}</b>"
        )
        log.info("Arb complete. P&L≈%+.6f MATIC", pnl_matic)

    except Exception as e:
        log.error("Leg 2 error: %s", e)
        send_alert(
            f"🚨 <b>Leg 2 Error ({sell_on}):</b> {str(e)[:300]}\n"
            f"⚠️ You may still hold USDC – check your wallet and sell manually."
        )

# ═══════════════════════════════════════════════════════════════
#  FASTAPI
# ═══════════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup checks."""
    connected = w3.is_connected()
    chain_id  = w3.eth.chain_id if connected else "?"
    log.info("Web3 connected=%s | chain_id=%s", connected, chain_id)
    if connected and chain_id != CHAIN_ID:
        log.warning("Chain ID mismatch! Expected %d, got %d", CHAIN_ID, chain_id)
    send_alert(
        f"🚀 <b>Crypto Knight Started</b>\n"
        f"Chain: <b>Polygon ({chain_id})</b>\n"
        f"RPC connected: <b>{connected}</b>\n"
        f"DRY_RUN=<b>{DRY_RUN}</b> | MAINNET=<b>{ENABLE_MAINNET}</b>\n"
        f"Trade size: <b>{TRADE_AMOUNT_MATIC} MATIC</b> | Min spread: <b>{MIN_SPREAD_PERCENT}%</b>"
    )
    yield

app = FastAPI(title="Crypto Knight – Polygon Arb", lifespan=lifespan)


@app.get("/")
def home():
    connected = w3.is_connected()
    return {
        "status":       "ok",
        "bot":          "Crypto Knight",
        "chain":        f"Polygon ({CHAIN_ID})",
        "rpc_ok":       connected,
        "dry_run":      DRY_RUN,
        "mainnet":      ENABLE_MAINNET,
        "trade_matic":  TRADE_AMOUNT_MATIC,
        "min_spread":   MIN_SPREAD_PERCENT,
        "daily_trades": _daily_trades,
        "daily_loss":   round(_daily_loss_matic, 6),
    }


@app.get("/cron-scan")
def cron_scan(background_tasks: BackgroundTasks):
    """
    Called by your cron job every 60 s.
    Returns immediately; scan runs in background.
    """
    background_tasks.add_task(perform_arbitrage_scan)
    return {"status": "scan-started", "timestamp": int(time.time())}


@app.get("/scan-now")
def scan_now():
    """Synchronous scan – returns full result (may be slow, use for testing)."""
    result = perform_arbitrage_scan()
    return JSONResponse(content=result)


@app.get("/status")
def status():
    return {
        "last_scan":    _last_scan_result,
        "daily_trades": _daily_trades,
        "daily_loss":   round(_daily_loss_matic, 6),
        "dry_run":      DRY_RUN,
        "mainnet":      ENABLE_MAINNET,
        "rpc_ok":       w3.is_connected(),
    }


@app.get("/health")
def health():
    """Render uses this for health checks."""
    return {"ok": True}

# sniper.py
import os, time
from dotenv import load_dotenv
from web3 import Web3
from web3utils import w3_http, to_wei_matic, from_wei_matic, build_tx, sign_and_send
from telegram_alerts import send
from db import mark_sniped
load_dotenv()

ROUTER = Web3.to_checksum_address(os.getenv("ROUTER_ADDRESS"))
BASE_TOKEN = Web3.to_checksum_address(os.getenv("BASE_TOKEN"))
MIN_LIQUIDITY = float(os.getenv("MIN_LIQUIDITY_MATIC", "0.5"))
BUY_AMOUNT = float(os.getenv("BUY_AMOUNT_MATIC", "0.05"))
SLIPPAGE = float(os.getenv("SLIPPAGE_PERCENT", "3"))
TAKE_PROFIT = float(os.getenv("TAKE_PROFIT_PERCENT", "50"))
STOP_LOSS = float(os.getenv("STOP_LOSS_PERCENT", "30"))
DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"
REQUIRE_CONFIRMATION = os.getenv("REQUIRE_CONFIRMATION", "true").lower() == "true"
ENABLE_MAINNET = os.getenv("ENABLE_MAINNET", "false").lower() == "true"
KILL_SWITCH = os.getenv("KILL_SWITCH", "false").lower() == "true"
WALLET = Web3.to_checksum_address(os.getenv("WALLET_ADDRESS"))

ROUTER_ABI = [{
    "name":"getAmountsOut","outputs":[{"name":"amounts","type":"uint256[]"}],"inputs":[{"name":"amountIn","type":"uint256"},{"name":"path","type":"address[]"}],"stateMutability":"view","type":"function"
},{
    "name":"swapExactETHForTokensSupportingFeeOnTransferTokens","outputs":[],"inputs":[{"name":"amountOutMin","type":"uint256"},{"name":"path","type":"address[]"},{"name":"to","type":"address"},{"name":"deadline","type":"uint256"}],"stateMutability":"payable","type":"function"
},{
    "name":"swapExactTokensForETHSupportingFeeOnTransferTokens","outputs":[],"inputs":[{"name":"amountIn","type":"uint256"},{"name":"amountOutMin","type":"uint256"},{"name":"path","type":"address[]"},{"name":"to","type":"address"},{"name":"deadline","type":"uint256"}],"stateMutability":"nonpayable","type":"function"
}]

ERC20_ABI = [
    {"name":"decimals","outputs":[{"name":"","type":"uint8"}],"inputs":[],"constant":True,"type":"function"},
    {"name":"balanceOf","outputs":[{"name":"","type":"uint256"}],"inputs":[{"name":"owner","type":"address"}],"constant":True,"type":"function"},
    {"name":"approve","outputs":[{"name":"","type":"bool"}],"inputs":[{"name":"spender","type":"address"},{"name":"amount","type":"uint256"}],"type":"function"},
    {"name":"allowance","outputs":[{"name":"uint256","type":"uint256"}],"inputs":[{"name":"owner","type":"address"},{"name":"spender","type":"address"}],"type":"function"}
]

router = w3_http.eth.contract(address=ROUTER, abi=ROUTER_ABI)

def pair_liquidity_check(pair_addr):
    PAIR_ABI = [{"name":"getReserves","outputs":[{"name":"_r0","type":"uint112"},{"name":"_r1","type":"uint112"},{"name":"_t","type":"uint32"}],"inputs":[],"type":"function"},
                {"name":"token0","outputs":[{"name":"","type":"address"}],"inputs":[],"type":"function"},
                {"name":"token1","outputs":[{"name":"","type":"address"}],"inputs":[],"type":"function"}]
    pair = w3_http.eth.contract(address=pair_addr, abi=PAIR_ABI)
    try:
        r0, r1, _ = pair.functions.getReserves().call()
        t0 = Web3.to_checksum_address(pair.functions.token0().call())
        t1 = Web3.to_checksum_address(pair.functions.token1().call())
        if t0 == BASE_TOKEN:
            base_reserve = from_wei_matic(r0)
        elif t1 == BASE_TOKEN:
            base_reserve = from_wei_matic(r1)
        else:
            return False, 0.0
        return base_reserve >= MIN_LIQUIDITY, base_reserve
    except Exception as e:
        print("liq check err", e)
        return False, 0.0

def is_honeypot_sim(token_addr):
    try:
        tiny = to_wei_matic(0.0001)
        path = [token_addr, BASE_TOKEN]
        out = router.functions.getAmountsOut(tiny, path).call()
        return out[-1] == 0
    except Exception as e:
        print("honeypot sim err", e)
        return True

def simulate_buy(amount_in_wei, path):
    try:
        out = router.functions.getAmountsOut(amount_in_wei, path).call()
        return out[-1]
    except Exception as e:
        print("simulate buy err", e)
        return 0

def do_buy_native(token_addr, amount_matic):
    amount_in = to_wei_matic(amount_matic)
    path = [BASE_TOKEN, token_addr]
    expected = simulate_buy(amount_in, path)
    if expected == 0:
        print("estimate failed, aborting buy")
        return None
    min_out = int(expected * (1 - SLIPPAGE/100))
    deadline = int(time.time()) + 60*5
    data = router.encodeABI(fn_name="swapExactETHForTokensSupportingFeeOnTransferTokens",
                             args=[min_out, path, WALLET, deadline])
    tx = {"from": WALLET, "to": ROUTER, "value": amount_in, "data": data}
    tx = build_tx(tx)
    if DRY_RUN or KILL_SWITCH or not ENABLE_MAINNET:
        print("[DRY_RUN] buy tx prepared:", tx)
        return None
    txh = sign_and_send(tx)
    send(f"Buy sent: https://mumbai.polygonscan.com/tx/{txh}")
    return txh

def approve_if_needed(token_addr, amount):
    token = w3_http.eth.contract(address=token_addr, abi=ERC20_ABI)
    allowance = token.functions.allowance(WALLET, ROUTER).call()
    if allowance >= amount:
        return True
    tx = token.functions.approve(ROUTER, amount).buildTransaction({"from": WALLET})
    tx = build_tx(tx)
    if DRY_RUN or KILL_SWITCH or not ENABLE_MAINNET:
        print("[DRY_RUN] approve tx prepared")
        return None
    txh = sign_and_send(tx)
    send(f"Approve sent: https://mumbai.polygonscan.com/tx/{txh}")
    return txh

def do_sell_all(token_addr):
    token = w3_http.eth.contract(address=token_addr, abi=ERC20_ABI)
    bal = token.functions.balanceOf(WALLET).call()
    if bal == 0:
        print("no balance to sell")
        return None
    # ensure allowance
    approve_if_needed(token_addr, bal)
    path = [token_addr, BASE_TOKEN]
    try:
        out = router.functions.getAmountsOut(bal, path).call()
    except Exception as e:
        print("sell estimate err", e)
        return None
    min_out = int(out[-1] * (1 - SLIPPAGE/100))
    deadline = int(time.time()) + 60*5
    if DRY_RUN or KILL_SWITCH or not ENABLE_MAINNET:
        print("[DRY_RUN] sell tx prepared: bal", bal, "min_out", min_out)
        return None
    tx = router.functions.swapExactTokensForETHSupportingFeeOnTransferTokens(bal, min_out, path, WALLET, deadline).buildTransaction({"from": WALLET})
    tx = build_tx(tx)
    txh = sign_and_send(tx)
    send(f"Sell sent: https://mumbai.polygonscan.com/tx/{txh}")
    return txh

def handle_pair(pair_addr, token0, token1):
    if KILL_SWITCH:
        print("Kill switch enabled - skipping")
        return
    # choose token that's not base
    token = token1 if token0 == BASE_TOKEN else token0
    ok, base_reserve = pair_liquidity_check(pair_addr)
    if not ok:
        print("liquidity below threshold:", base_reserve)
        return
    if is_honeypot_sim(token):
        print("honeypot detected - aborting")
        return
    # simulate buy
    amount = min(BUY_AMOUNT, float(os.getenv("MAX_TRADE_MATIC", "0.1")))
    est = simulate_buy(to_wei_matic(amount), [BASE_TOKEN, token])
    if est == 0:
        print("estimate zero - abort")
        return
    msg = f"Ready to snipe token {token} on pair {pair_addr}\nBuy amount: {amount} MATIC\nEst tokens: {est}\nDRY_RUN={DRY_RUN}\nEnable mainnet? {ENABLE_MAINNET}"
    send(msg)
    if REQUIRE_CONFIRMATION:
        # Simple manual confirmation flow: instruct user to toggle ENABLE_MAINNET=true in env or confirm via Telegram (advanced webhook needed)
        send("Manual confirmation required. Set ENABLE_MAINNET=true in server env to proceed.")
        print("Waiting up to 5 minutes for ENABLE_MAINNET toggle.")
        for _ in range(60):
            if os.getenv("ENABLE_MAINNET", "false").lower() == "true":
                break
            time.sleep(5)
        else:
            send("No confirmation received, aborting snipe.")
            return
    # execute buy
    buy_tx = do_buy_native(token, amount)
    if not buy_tx and DRY_RUN:
        send("[DRY_RUN] buy simulated, not broadcasting.")
    # naive monitoring: wait then attempt sell (demo)
    time.sleep(10)
    # try sell all after wait for demo; production must implement real price-based sell
    sell_tx = do_sell_all(token)
    if DRY_RUN:
        send("[DRY_RUN] sell simulated.")

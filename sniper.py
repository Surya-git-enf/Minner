# sniper.py
import os, time, math
from web3 import Web3
from web3utils import w3_http, build_tx, sign_and_send, to_wei, from_wei
from dotenv import load_dotenv
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

# Minimal ABIs
ROUTER_ABI = [{
    "name":"getAmountsOut","outputs":[{"name":"amounts","type":"uint256[]"}],"inputs":[{"name":"amountIn","type":"uint256"},{"name":"path","type":"address[]"}],"stateMutability":"view","type":"function"
},{
    "name":"swapExactETHForTokensSupportingFeeOnTransferTokens","outputs":[],"inputs":[{"name":"amountOutMin","type":"uint256"},{"name":"path","type":"address[]"},{"name":"to","type":"address"},{"name":"deadline","type":"uint256"}],"stateMutability":"payable","type":"function"
},{
    "name":"swapExactTokensForETHSupportingFeeOnTransferTokens","outputs":[],"inputs":[{"name":"amountIn","type":"uint256"},{"name":"amountOutMin","type":"uint256"},{"name":"path","type":"address[]"},{"name":"to","type":"address"},{"name":"deadline","type":"uint256"}],"stateMutability":"nonpayable","type":"function"
}]
ERC20_ABI = [{"name":"decimals","outputs":[{"type":"uint8","name":""}],"inputs":[],"constant":True,"type":"function"},
             {"name":"balanceOf","outputs":[{"type":"uint256","name":""}],"inputs":[{"name":"owner","type":"address"}],"constant":True,"type":"function"},
             {"name":"approve","outputs":[{"type":"bool","name":""}],"inputs":[{"name":"spender","type":"address"},{"name":"amount","type":"uint256"}],"type":"function"},
             {"name":"allowance","outputs":[{"type":"uint256","name":""}],"inputs":[{"name":"owner","type":"address"},{"name":"spender","type":"address"}],"type":"function"}]

router = w3_http.eth.contract(address=ROUTER, abi=ROUTER_ABI)

def pair_liquidity_check(pair_addr):
    # pair reserves check (use pair contract)
    PAIR_ABI = [{"name":"getReserves","outputs":[{"type":"uint112","name":"_r0"},{"type":"uint112","name":"_r1"},{"type":"uint32","name":"_t"}],"inputs":[],"constant":True,"type":"function"},{"name":"token0","outputs":[{"type":"address","name":""}],"inputs":[],"constant":True,"type":"function"},{"name":"token1","outputs":[{"type":"address","name":""}],"inputs":[],"constant":True,"type":"function"}]
    pair = w3_http.eth.contract(address=pair_addr, abi=PAIR_ABI)
    try:
        r0, r1, _ = pair.functions.getReserves().call()
        tok0 = Web3.to_checksum_address(pair.functions.token0().call())
        tok1 = Web3.to_checksum_address(pair.functions.token1().call())
        # map base token
        if tok0 == BASE_TOKEN:
            base_reserve = from_wei(r0)
        elif tok1 == BASE_TOKEN:
            base_reserve = from_wei(r1)
        else:
            return False, 0.0
        return base_reserve >= MIN_LIQUIDITY, base_reserve
    except Exception as e:
        print("liquidity check failed:", e)
        return False, 0.0

def is_honeypot_sim(token_addr):
    # basic simulation: attempt to estimate selling back tiny amount
    try:
        tiny = to_wei(0.0001)
        path = [token_addr, BASE_TOKEN]
        out = router.functions.getAmountsOut(tiny, path).call()
        return out[-1] == 0
    except Exception as e:
        print("honeypot simulation error", e)
        return True

def approve_if_needed(token_addr, amount):
    token = w3_http.eth.contract(address=token_addr, abi=ERC20_ABI)
    allowance = token.functions.allowance(Web3.to_checksum_address(os.getenv("WALLET_ADDRESS")), RO

UTER).call()
    if allowance >= amount:
        return True
    tx = token.functions.approve(ROUTER, amount).build_transaction({"from": os.getenv("WALLET_ADDRESS")})
    tx = build_tx(tx)
    txh = sign_and_send(tx)
    print("Approve tx:", txh)
    return txh

def buy(token_addr, pair_addr):
    # path: [BASE_TOKEN, token]
    amount_in = to_wei(BUY_AMOUNT)
    path = [BASE_TOKEN, token_addr]
    # estimate output
    try:
        out = router.functions.getAmountsOut(amount_in, path).call()
    except Exception as e:
        print("estimate failed:", e)
        return None
    expected = out[-1]
    min_out = int(expected * (1 - SLIPPAGE/100))
    deadline = int(time.time()) + 60*5
    tx = {
        "from": os.getenv("WALLET_ADDRESS"),
        "to": RO
UTER,
        "value": amount_in,
        "data": router.encodeABI(fn_name="swapExactETHForTokensSupportingFeeOnTransferTokens", args=[min_out, path, os.getenv("WALLET_ADDRESS"), deadline])
    }
    tx = build_tx(tx)
    txh = sign_and_send(tx)
    send(f"Bought token {token_addr}\nTx: https://mumbai.polygonscan.com/tx/{txh}")
    return txh

def sell_all(token_addr):
    token = w3_http.eth.contract(address=token_addr, abi=ERC20_ABI)
    bal = token.functions.balanceOf(os.getenv("WALLET_ADDRESS")).call()
    if bal == 0:
        print("No balance to sell")
        return None
    # approve
    approve_if_needed(token_addr, bal)
    path = [token_addr, BASE_TOKEN]
    try:
        out = router.functions.getAmountsOut(bal, path).call()
    except Exception as e:
        print("sell estimate failed", e)
        return None
    min_out = int(out[-1] * (1 - SLIPPAGE/100))
    deadline = int(time.time()) + 60*5
    tx = router.functions.swapExactTokensForETHSupportingFeeOnTransferTokens(bal, min_out, path, os.getenv("WALLET_ADDRESS"), deadline).build_transaction({"from": os.getenv("WALLET_ADDRESS")})
    tx = build_tx(tx)
    txh = sign_and_send(tx)
    send(f"Sold token {token_addr}\nTx: https://mumbai.polygonscan.com/tx/{txh}")
    return txh

def handle_pair(pair_addr, token0, token1):
    # pick token that is not base
    token = token1 if token0 == BASE_TOKEN else token0
    print("Handling pair", pair_addr, "token:", token)
    ok, base_reserve = pair_liquidity_check(pair_addr)
    if not ok:
        print("Liquidity below threshold:", base_reserve)
        return
    if is_honeypot_sim(token):
        print("Detected honeypot")
        return
    # mark as sniped (prevent duplicates)
    mark_sniped(pair_addr, token0, token1)
    send(f"Sniping {token} on pair {pair_addr} (liquidity {base_reserve} MATIC)")
    buy_tx = buy(token, pair_addr)
    if not buy_tx:
        print("Buy failed")
        return
    # naive monitor loop for profit/stop
    start = time.time()
    while True:
        # crude price check using getAmountsOut
        try:
            path = [BASE_TOKEN, token]
            price = router.functions.getAmountsOut(to_wei(0.0001), path).call()[-1]
            # price is token amount per tiny base — derive relative change not exact
            # In practice you'd calculate token per base and compare to initial
            # For simplicity wait fixed time then attempt sell for profit.
        except Exception:
            pass
        # Wait some seconds before checking
        time.sleep(5)
        # For demo: after 30s attempt sell (real logic should use price thresholds)
        if time.time() - start > 30:
            sell_all(token)
            break

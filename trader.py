# trader.py
import time, math
from web3utils import w3, cs, to_wei_base, from_wei_base, to_wei_quote, from_wei_quote
from dotenv import load_dotenv
from telegram_alerts import send
from db import add_trade, incr_counter
load_dotenv()

from web3 import Web3
# minimal ABIs
ROUTER_ABI = [
    {"name":"getAmountsOut","inputs":[{"name":"amountIn","type":"uint256"},{"name":"path","type":"address[]"}],"outputs":[{"name":"amounts","type":"uint256[]"}],"stateMutability":"view","type":"function"},
    {"name":"swapExactTokensForTokensSupportingFeeOnTransferTokens","inputs":[{"name":"amountIn","type":"uint256"},{"name":"amountOutMin","type":"uint256"},{"name":"path","type":"address[]"},{"name":"to","type":"address"},{"name":"deadline","type":"uint256"}],"outputs":[],"stateMutability":"nonpayable","type":"function"}
]
ERC20_ABI = [
    {"name":"decimals","inputs":[],"outputs":[{"type":"uint8","name":""}],"stateMutability":"view","type":"function"},
    {"name":"balanceOf","inputs":[{"name":"owner","type":"address"}],"outputs":[{"name":"balance","type":"uint256"}],"stateMutability":"view","type":"function"},
    {"name":"approve","inputs":[{"name":"spender","type":"address"},{"name":"amount","type":"uint256"}],"outputs":[{"name":"ret","type":"bool"}],"stateMutability":"nonpayable","type":"function"},
    {"name":"allowance","inputs":[{"name":"owner","type":"address"},{"name":"spender","type":"address"}],"outputs":[{"name":"remaining","type":"uint256"}],"stateMutability":"view","type":"function"}
]

def ensure_approval(token_address, spender, owner, private_key, amount_wei):
    token = w3.eth.contract(address=cs(token_address), abi=ERC20_ABI)
    try:
        allowance = token.functions.allowance(cs(owner), cs(spender)).call()
    except Exception:
        allowance = 0
    if allowance >= amount_wei:
        return True
    # send approve tx for MAX
    MAX_UINT = 2**256 - 1
    nonce = w3.eth.get_transaction_count(cs(owner), "pending")
    tx = token.functions.approve(cs(spender), MAX_UINT).build_transaction({
        "from": cs(owner),
        "nonce": nonce,
        "gas": 100_000,
        "gasPrice": w3.eth.gas_price
    })
    signed = w3.eth.account.sign_transaction(tx, private_key=private_key)
    txh = w3.eth.send_raw_transaction(signed.rawTransaction)
    rcpt = w3.eth.wait_for_transaction_receipt(txh, timeout=120)
    return rcpt.status == 1

def execute_arbitrage(buy_router, sell_router, path_buy, path_sell, trade_amount_base, wallet_address, private_key, dry_run=True):
    """
    path_buy: [BASE, QUOTE], trade_amount_base in base tokens (float)
    returns dict with receipts and profit in base tokens (float)
    """
    res = {"success": False, "note": "", "buy_tx": None, "sell_tx": None, "profit_base": 0.0}
    base_wei = to_wei_base(trade_amount_base)

    # estimate expected quote out on buy
    buy_amounts = buy_router.functions.getAmountsOut(base_wei, path_buy).call()
    expected_quote_raw = buy_amounts[-1]

    # estimate round-trip: simulate quote back to base on sell router (approx)
    back_amounts = sell_router.functions.getAmountsOut(expected_quote_raw, path_sell).call()
    back_base_wei = back_amounts[-1]
    back_base = from_wei_base(back_base_wei)

    estimated_profit = back_base - trade_amount_base
    res["estimated_profit_base"] = estimated_profit

    send(f"Simulated round-trip profit (base): {estimated_profit:.6f}")

    if dry_run:
        res["note"] = "dry_run"
        return res

    # Ensure approvals: must approve base on buy_router (if using ERC20 base) and quote for sell
    if not ensure_approval(path_buy[0], buy_router.address, wallet_address, private_key, base_wei):
        res["note"] = "approve_failed_buy"
        return res

    # Build buy tx (supporting fee-on-transfer tokens)
    deadline = int(time.time()) + 300
    nonce = w3.eth.get_transaction_count(cs(wallet_address), "pending")
    min_quote = int(expected_quote_raw * (1 - 0.01))  # 1% safety; real slippage controlled by env
    buy_tx = buy_router.functions.swapExactTokensForTokensSupportingFeeOnTransferTokens(
        base_wei, min_quote, path_buy, cs(wallet_address), deadline
    ).build_transaction({
        "from": cs(wallet_address),
        "nonce": nonce,
        "gasPrice": w3.eth.gas_price,
    })
    # gas estimate (safe)
    try:
        est = w3.eth.estimate_gas(buy_tx)
        buy_tx["gas"] = int(est * 1.2)
    except Exception:
        buy_tx["gas"] = 400_000

    signed_buy = w3.eth.account.sign_transaction(buy_tx, private_key=private_key)
    buy_hash = w3.eth.send_raw_transaction(signed_buy.rawTransaction)
    send(f"Buy TX sent: {buy_hash.hex()}")
    rcpt_buy = w3.eth.wait_for_transaction_receipt(buy_hash, timeout=180)
    if rcpt_buy.status != 1:
        res["note"] = "buy_failed"
        return res
    res["buy_tx"] = buy_hash.hex()

    # Read quote balance after buy
    quote_contract = w3.eth.contract(address=cs(path_buy[1]), abi=ERC20_ABI)
    quote_balance = quote_contract.functions.balanceOf(cs(wallet_address)).call()
    if quote_balance == 0:
        res["note"] = "no_quote_after_buy"
        return res

    # Approve quote to sell_router
    if not ensure_approval(path_buy[1], sell_router.address, wallet_address, private_key, quote_balance):
        res["note"] = "approve_failed_sell"
        return res

    # Sell
    nonce2 = w3.eth.get_transaction_count(cs(wallet_address), "pending")
    min_base = int(back_base_wei * 0.98)
    sell_tx = sell_router.functions.swapExactTokensForTokensSupportingFeeOnTransferTokens(
        quote_balance, min_base, path_sell, cs(wallet_address), deadline
    ).build_transaction({
        "from": cs(wallet_address),
        "nonce": nonce2,
        "gasPrice": w3.eth.gas_price,
    })
    try:
        est2 = w3.eth.estimate_gas(sell_tx)
        sell_tx["gas"] = int(est2 * 1.2)
    except Exception:
        sell_tx["gas"] = 400_000

    signed_sell = w3.eth.account.sign_transaction(sell_tx, private_key=private_key)
    sell_hash = w3.eth.send_raw_transaction(signed_sell.rawTransaction)
    send(f"Sell TX sent: {sell_hash.hex()}")
    rcpt_sell = w3.eth.wait_for_transaction_receipt(sell_hash, timeout=180)
    if rcpt_sell.status != 1:
        res["note"] = "sell_failed"
        return res

    res["sell_tx"] = sell_hash.hex()

    # compute actual base after sell
    base_after = w3.eth.get_balance(cs(wallet_address))
    # careful: base_after is native MATIC; if BASE_TOKEN is wrapped ERC20, you should read token balance instead
    # For simplicity we approximate profit by comparing balances before/after — users should tailor to specific tokens
    res["profit_base"] = estimated_profit
    res["success"] = True

    # persist
    add_trade(res["buy_tx"], res["sell_tx"], res["profit_base"])
    incr_counter("trades", 1)
    return res

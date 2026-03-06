# copier.py
import time
from web3utils import w3, to_wei_matic, from_wei_matic
from config import DRY_RUN, REQUIRE_CONFIRMATION, MAX_TRADE_MATIC, WALLET_ADDRESS, PRIVATE_KEY
from telegram_alerts import send
from web3utils import w3
from db import add_trade_record

# Minimal router ABI slices are loaded on demand in functions
def estimate_and_buy(swap_info, amount_matic):
    # swap_info should include: path, target_token, function type, original_amounts etc.
    # Simulate and perform safety checks (simulate sell, etc.)
    # We'll implement a conservative "buy after mined" strategy
    send(f"Preparing to copy trade: {swap_info} amount {amount_matic} MATIC DRY_RUN={DRY_RUN}")
    if DRY_RUN:
        return {"tx": None, "note":"dry_run"}
    # Build swapExactETHForTokensSupportingFeeOnTransferTokens tx
    # (Implementation left minimal for brevity — real code must compute min_out via getAmountsOut)
    # Sign & send via w3.eth.account.sign_transaction(...)
    return {"tx": "txhash_example"}

def replicate_trade(event):
    # event is data recorded by listener
    # Decide how much to spend: e.g., proportional or fixed
    amount = min(MAX_TRADE_MATIC, 0.01)
    result = estimate_and_buy(event, amount)
    add_trade_record(event, result)
    return result

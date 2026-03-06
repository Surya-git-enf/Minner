# listener.py
import time, threading
from web3utils import w3, w3_ws, ensure_connected
from config import ROUTER_ADDRESSES, MIN_WHALE_MATIC, CHECK_INTERVAL_SECONDS
from decoder import decode_swap_input
from telegram_alerts import send
from db import record_event

def handle_tx(tx_hash, tx):
    # tx is dict returned by w3.eth.get_transaction
    # detect if from known whale address or value >= threshold
    value_matic = float(tx.get("value",0)) / 10**18
    from_addr = tx.get("from")
    # simple threshold: large native value OR looking for swap calls to known router addresses
    to_addr = tx.get("to")
    if to_addr and to_addr.lower() in [r.lower() for r in ROUTER_ADDRESSES] or value_matic >= MIN_WHALE_MATIC:
        # decode input
        info = decode_swap_input(tx.get("input",""))
        msg = f"Whale tx detected\nfrom: {from_addr}\nto: {to_addr}\nvalue(matic): {value_matic}\nfn: {info.get('type')}"
        send(msg + f"\nhttps://mumbai.polygonscan.com/tx/{tx_hash}")
        record_event({"tx":tx_hash,"from":from_addr,"value_matic":value_matic,"type":info.get("type")})
        # publish to copier or monitor (main app will handle further)
    # else ignore

def pending_listener():
    # low-latency: subscribe to pending txs (requires websocket provider)
    if not w3_ws:
        print("WSS not configured, pending listener disabled")
        return
    sub = w3_ws.eth.subscribe("newPendingTransactions")
    print("Subscribed to pending txs")
    for tx_hash in sub:
        try:
            tx = w3.eth.get_transaction(tx_hash)
            handle_tx(tx_hash, tx)
        except Exception:
            continue

def block_polling_listener(callback_on_tx):
    # fallback: poll recent blocks and scan transactions
    last_block = w3.eth.block_number
    while True:
        latest = w3.eth.block_number
        if latest > last_block:
            for b in range(last_block+1, latest+1):
                blk = w3.eth.get_block(b, full_transactions=True)
                for tx in blk.transactions:
                    # simple check
                    callback_on_tx(tx.hash.hex(), tx)
            last_block = latest
        time.sleep(CHECK_INTERVAL_SECONDS)

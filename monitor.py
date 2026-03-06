# monitor.py
from web3utils import ensure_connected, w3_ws
from db import init_db, record_event
from listener import block_polling_listener, pending_listener, handle_tx
from copier import replicate_trade
import threading

def start_all():
    ensure_connected()
    init_db()
    # start pending listener in thread if websocket available
    if w3_ws:
        t = threading.Thread(target=pending_listener, daemon=True)
        t.start()
    # block polling fallback
    t2 = threading.Thread(target=block_polling_listener, args=(handle_tx,), daemon=True)
    t2.start()
    print("Listeners started")

if __name__ == "__main__":
    start_all()
    import time
    while True:
        time.sleep(60)

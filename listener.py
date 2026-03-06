# listener.py
import os, time
from dotenv import load_dotenv
from web3utils import w3_wss, w3_http, check_connection
from web3 import Web3
from telegram_alerts import send
from db import is_sniped, mark_sniped

load_dotenv()
FACTORY_ADDRESS = Web3.to_checksum_address(os.getenv("FACTORY_ADDRESS"))
PAIR_CREATED_SIG = Web3.keccak(text="PairCreated(address,address,address,uint256)").hex()

def listen_pair_created(callback):
    # Poll logs if websocket isn't available
    if not w3_wss or not w3_wss.is_connected():
        print("WSS not connected — falling back to HTTP polling for new pairs.")
    print("Starting PairCreated listener...")
    from_block = w3_http.eth.block_number
    while True:
        try:
            latest = w3_http.eth.block_number
            logs = w3_http.eth.get_logs({
                "fromBlock": from_block,
                "toBlock": latest,
                "address": FACTORY_ADDRESS,
                "topics": [PAIR_CREATED_SIG]
            })
            for l in logs:
                topics = l["topics"]
                # tokens encoded in topics[1] and topics[2]
                token0 = Web3.to_checksum_address("0x"+topics[1].hex()[-40:])
                token1 = Web3.to_checksum_address("0x"+topics[2].hex()[-40:])
                # read pair from data (last 32 bytes)
                pair = Web3.to_checksum_address("0x"+l["data"][-64:])
                if is_sniped(pair):
                    continue
                print("New pair:", pair, token0, token1)
                send(f"New pair detected: {pair}\n{token0} / {token1}")
                callback(pair, token0, token1)
                mark_sniped(pair, token0, token1)
            from_block = latest + 1
        except Exception as e:
            print("Listener error:", e)
            time.sleep(2)

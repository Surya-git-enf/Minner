# listener.py
import os, json, time
from web3utils import w3_wss, w3_http, check_connection
from web3 import Web3
from telegram_alerts import send
from db import is_sniped, mark_sniped

FACTORY_ADDRESS = Web3.to_checksum_address(os.getenv("FACTORY_ADDRESS"))

PAIR_CREATED_SIG = Web3.keccak(text="PairCreated(address,address,address,uint256)").hex()

def listen_pair_created(callback):
    # If websocket connected, use logs subscription for PairCreated
    if not w3_wss or not w3_wss.is_connected():
        print("WSS not connected — pair listener disabled")
        return

    print("Listening for PairCreated events...")
    from_block = w3_http.eth.block_number
    while True:
        try:
            latest = w3_http.eth.block_number
            # filter logs for factory contract and PairCreated topic
            logs = w3_http.eth.get_logs({
                "fromBlock": from_block,
                "toBlock": latest,
                "address": FACTORY_ADDRESS,
                "topics": [PAIR_CREATED_SIG]
            })
            for l in logs:
                # decode topics (token0, token1, pair)
                topics = l["topics"]
                data = l["data"]
                # crude decode: token0 in topic1, token1 in topic2
                token0 = Web3.to_checksum_address("0x"+topics[1].hex()[-40:])
                token1 = Web3.to_checksum_address("0x"+topics[2].hex()[-40:])
                # pair address may be in data but easier: read from logs
                pair = Web3.to_checksum_address("0x"+data[-64:])
                if is_sniped(pair):
                    continue
                print("New pair:", pair, token0, token1)
                send(f"New pair detected: {pair}\n{token0} / {token1}")
                callback(pair, token0, token1)
            from_block = latest + 1
        except Exception as e:
            print("Pair listener error:", e)
            time.sleep(2)

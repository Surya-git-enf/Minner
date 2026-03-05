# web3utils.py
import os, time
from dotenv import load_dotenv
from web3 import Web3
from eth_account import Account

load_dotenv()

RPC_HTTP = os.getenv("RPC_HTTP")
RPC_WSS = os.getenv("RPC_WSS")
CHAIN_ID = int(os.getenv("CHAIN_ID", "80001"))
WALLET_ADDRESS = Web3.to_checksum_address(os.getenv("WALLET_ADDRESS"))
PRIVATE_KEY = os.getenv("PRIVATE_KEY")

w3_http = Web3(Web3.HTTPProvider(RPC_HTTP))
w3_wss = Web3(Web3.WebsocketProvider(RPC_WSS)) if RPC_WSS else None

def check_connection():
    if not w3_http.is_connected():
        raise RuntimeError("HTTP RPC not connected")
    if w3_wss and not w3_wss.is_connected():
        print("Warning: WSS not connected; pair listener may not run")

def build_tx(tx):
    tx.setdefault("chainId", CHAIN_ID)
    if "nonce" not in tx:
        tx["nonce"] = w3_http.eth.get_transaction_count(WALLET_ADDRESS)
    if "gas" not in tx:
        try:
            tx["gas"] = w3_http.eth.estimate_gas(tx)
        except Exception:
            tx["gas"] = int(os.getenv("MAX_TX_GAS", "500000"))
    if "gasPrice" not in tx:
        tx["gasPrice"] = w3_http.eth.gas_price
    return tx

def sign_and_send(tx):
    signed = w3_http.eth.account.sign_transaction(tx, PRIVATE_KEY)
    txhash = w3_http.eth.send_raw_transaction(signed.rawTransaction)
    return txhash.hex()

def to_wei(amount_decimal):
    return int(amount_decimal * 10**18)

def from_wei(value):
    return value / 10**18

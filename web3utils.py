# web3utils.py
import os
from dotenv import load_dotenv
from web3 import Web3

load_dotenv()

RPC_HTTP = os.getenv("RPC_HTTP")
RPC_WSS = os.getenv("RPC_WSS")
CHAIN_ID = int(os.getenv("CHAIN_ID", "80001"))

w3 = Web3(Web3.HTTPProvider(RPC_HTTP))
w3_ws = Web3(Web3.WebsocketProvider(RPC_WSS)) if RPC_WSS else None

def ensure_connected():
    if not w3.is_connected():
        raise RuntimeError("HTTP RPC not connected")
    if w3_ws and not w3_ws.is_connected():
        print("Warning: WSS not connected")

def to_wei_matic(x):
    return int(float(x) * 10**18)

def from_wei_matic(x):
    return float(x) / 10**18

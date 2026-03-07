# web3utils.py
import os
from dotenv import load_dotenv
from web3 import Web3
from web3.middleware import geth_poa_middleware

load_dotenv()

RPC_HTTP = os.getenv("RPC_HTTP")
RPC_CHAIN_ID = int(os.getenv("RPC_CHAIN_ID", "80001"))

w3 = Web3(Web3.HTTPProvider(RPC_HTTP, request_kwargs={"timeout": 30}))
w3.middleware_onion.inject(geth_poa_middleware, layer=0)

def cs(addr: str) -> str:
    return w3.to_checksum_address(addr)

def to_wei_base(amount: float) -> int:
    # base token decimals assumed 18 (WMATIC)
    return int(amount * 10**18)

def from_wei_base(raw: int) -> float:
    return float(raw) / 10**18

def to_wei_quote(amount: float, decimals: int) -> int:
    return int(amount * (10 ** decimals))

def from_wei_quote(raw: int, decimals: int) -> float:
    return float(raw) / (10 ** decimals)

# security.py
import os, time
from web3utils import w3, cs
import requests
from dotenv import load_dotenv
load_dotenv()

GOPLUS_KEY = os.getenv("GOPLUS_API_KEY")

def goplus_check(token_address, chain_id=137):
    if not GOPLUS_KEY:
        return {"ok": True, "reason": "no_api_key"}
    url = f"https://api.gopluslabs.io/api/v1/token_security/{chain_id}?contract_addresses={token_address}&apikey={GOPLUS_KEY}"
    try:
        r = requests.get(url, timeout=6).json()
        data = r.get("result", {}).get(token_address.lower(), {})
        is_honeypot = data.get("is_honeypot") == "1"
        if is_honeypot:
            return {"ok": False, "reason": "goplus_honeypot"}
        return {"ok": True, "reason": "goplus_ok", "meta": data}
    except Exception as e:
        return {"ok": False, "reason": "goplus_error", "error": str(e)}

def simulate_call(to_address, data):
    try:
        # eth_call simulates; if it reverts, exception thrown
        w3.eth.call({"to": cs(to_address), "data": data}, block_identifier="latest")
        return True
    except Exception as e:
        # call reverted — treat as failed
        return False

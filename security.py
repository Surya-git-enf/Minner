# security.py
import requests
import os
from web3utils import w3
from config import GOPLUS_API_KEY

# 1) Query external audit API (GoPlus as example)
def goplus_check(token_address, chain_id=137):
    if not GOPLUS_API_KEY:
        return {"ok": True, "reason": "no_api_key"}
    url = f"https://api.gopluslabs.io/api/v1/token_security/{chain_id}?contract_addresses={token_address}&apikey={GOPLUS_API_KEY}"
    try:
        r = requests.get(url, timeout=6).json()
        # interpret fields safely
        data = r.get("result", {}).get(token_address.lower(), {})
        is_honeypot = data.get("is_honeypot") == "1"
        buy_tax = float(data.get("buy_tax",0) or 0)
        sell_tax = float(data.get("sell_tax",0) or 0)
        if is_honeypot:
            return {"ok": False, "reason": "honeypot"}
        if buy_tax > 0.10 or sell_tax > 0.10:
            return {"ok": False, "reason": "high_tax", "buy_tax": buy_tax, "sell_tax": sell_tax}
        return {"ok": True, "reason":"goplus_ok"}
    except Exception as e:
        return {"ok": False, "reason": "goplus_error", "error": str(e)}

# 2) Simulate sell using eth_call
def simulate_sell(path, amount_in_wei, rpc_w3=None):
    # path: [token, base] or similar; we will call router.getAmountsOut via eth_call if deployed
    # For simplicity assume router ABI loaded in main app; caller will perform this call
    # Here, we just return True (caller must implement router call). Keep this function as placeholder.
    return True

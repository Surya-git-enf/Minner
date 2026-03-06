# config.py
import os
from dotenv import load_dotenv
load_dotenv()

ROUTER_ADDRESSES = [addr.strip() for addr in os.getenv("ROUTER_ADDRESSES","").split(",") if addr.strip()]
WALLET_ADDRESS = os.getenv("WALLET_ADDRESS")
PRIVATE_KEY = os.getenv("PRIVATE_KEY")
DRY_RUN = os.getenv("DRY_RUN","true").lower() == "true"
REQUIRE_CONFIRMATION = os.getenv("REQUIRE_CONFIRMATION","true").lower() == "true"
MAX_TRADE_MATIC = float(os.getenv("MAX_TRADE_MATIC","0.05"))
MIN_WHALE_MATIC = float(os.getenv("MIN_WHale_MATIC","1.0"))
MIN_LIQUIDITY_MATIC = float(os.getenv("MIN_LIQUIDITY_MATIC","0.5"))
GOPLUS_API_KEY = os.getenv("GOPLUS_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
SQLITE_PATH = os.getenv("SQLITE_PATH","whale_state.db")
CHECK_INTERVAL_SECONDS = int(os.getenv("CHECK_INTERVAL_SECONDS","2"))

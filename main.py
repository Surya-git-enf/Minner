# main.py
from fastapi import FastAPI
import threading, time
from listener import listen_pair_created
from sniper import handle_pair
from db import init_db
from web3utils import check_connection

app = FastAPI()

@app.get("/")
def root():
    return {"status":"sniper god running"}

def start_listener():
    check_connection()
    init_db()
    listen_pair_created(handle_pair)

if __name__ == "__main__":
    t = threading.Thread(target=start_listener, daemon=True)
    t.start()
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=10000)

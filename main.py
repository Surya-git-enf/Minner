# main.py
from fastapi import FastAPI
import threading
from monitor import start_all

app = FastAPI()

@app.on_event("startup")
def startup_event():
    t = threading.Thread(target=start_all, daemon=True)
    t.start()

@app.get("/")
def root():
    return {"status":"whale_tracker_running"}

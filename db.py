# db.py
import sqlite3
import time
from dotenv import load_dotenv
import os

load_dotenv()
DB_PATH = os.getenv("SQLITE_PATH", "crypto_knight_v2.db")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY,
                    ts INTEGER,
                    buy_tx TEXT,
                    sell_tx TEXT,
                    profit_base REAL
                 )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS counters (k TEXT PRIMARY KEY, v REAL)""")
    conn.commit()
    conn.close()

def add_trade(buy_tx, sell_tx, profit_base):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("INSERT INTO trades (ts, buy_tx, sell_tx, profit_base) VALUES (?, ?, ?, ?)",
                (int(time.time()), buy_tx, sell_tx, profit_base))
    conn.commit()
    conn.close()

def get_counter(k):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT v FROM counters WHERE k=?", (k,))
    r = cur.fetchone()
    conn.close()
    return float(r[0]) if r else 0.0

def incr_counter(k, inc=1.0):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO counters(k,v) VALUES(?,?)", (k, 0.0))
    cur.execute("UPDATE counters SET v = v + ? WHERE k=?", (inc, k))
    conn.commit()
    conn.close()

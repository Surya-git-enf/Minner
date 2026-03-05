# db.py
import os, sqlite3

DB = os.getenv("SQLITE_PATH", "sniper_state.db")

def init_db():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS sniped_pairs (
            pair_address TEXT PRIMARY KEY,
            token0 TEXT, token1 TEXT,
            timestamp INTEGER
        )""")
    conn.commit()
    conn.close()

def mark_sniped(pair_address, token0, token1):
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute("INSERT OR REPLACE INTO sniped_pairs(pair_address, token0, token1, timestamp) VALUES (?,?,?,?)",
                (pair_address, token0, token1, int(time.time())))
    conn.commit()
    conn.close()

def is_sniped(pair_address):
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM sniped_pairs WHERE pair_address = ?", (pair_address,))
    r = cur.fetchone()
    conn.close()
    return r is not None

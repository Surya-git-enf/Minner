# db.py
import os, sqlite3, time
DB = os.getenv("SQLITE_PATH", "sniper_state.db")

def init_db():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS sniped_pairs (
        pair_address TEXT PRIMARY KEY,
        token0 TEXT,
        token1 TEXT,
        timestamp INTEGER
    )""")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS stats (
        k TEXT PRIMARY KEY,
        v REAL
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

# stats helpers
def db_get(key, default=0.0):
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute("SELECT v FROM stats WHERE k=?", (key,))
    r = cur.fetchone()
    conn.close()
    return r[0] if r else default

def db_set(key, val):
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute("INSERT OR REPLACE INTO stats(k,v) VALUES(?,?)", (key, float(val)))
    conn.commit()
    conn.close()

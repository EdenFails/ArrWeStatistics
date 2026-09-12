import os
import sqlite3

DB_PATH = os.getenv("DB_PATH", "data/arrwestatistics.db")


def get_conn() -> sqlite3.Connection:
    folder = os.path.dirname(DB_PATH)
    if folder:
        try:
            os.makedirs(folder, exist_ok=True)
        except Exception:
            pass
        try:
            os.chmod(folder, 0o777)
        except Exception:
            pass

    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    conn.execute("PRAGMA cache_size = -2000;")
    conn.execute("PRAGMA temp_store = MEMORY;")
    return conn


def init_db() -> None:
    conn = get_conn()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS auth (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            password_hash TEXT NOT NULL,
            is_initialized INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS services (
            id INTEGER PRIMARY KEY AUTOINCREMENT, 
            name TEXT NOT NULL,
            service_type TEXT NOT NULL,
            base_url TEXT NOT NULL,
            apikey TEXT NULL,
            username TEXT NULL,
            password TEXT NULL,
            is_enabled INTEGER DEFAULT 1,
            display_order INTEGER DEFAULT 0,
            config_json TEXT NULL 
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS service_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT, 
            service_id INTEGER NOT NULL,
            last_poll_ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status TEXT NOT NULL,
            response_time_ms INTEGER NOT NULL,
            FOREIGN KEY (service_id) REFERENCES services(id) ON DELETE CASCADE
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS ui_preferences (
            preference_key VARCHAR(64) PRIMARY KEY,
            preference_val TEXT NOT NULL
        )
    """)

    c.execute("CREATE INDEX IF NOT EXISTS idx_service_metrics_service_id ON service_metrics(service_id);")
    c.execute("CREATE INDEX IF NOT EXISTS idx_services_display_order ON services(display_order);")

    conn.commit()
    conn.close()


def has_auth() -> bool:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT is_initialized FROM auth WHERE id = 1")
    row = c.fetchone()
    conn.close()
    return bool(row and row["is_initialized"] == 1)


def read_auth() -> dict | None:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT id, password_hash, is_initialized, created_at FROM auth WHERE id = 1")
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None


def set_initial_auth(hash_str: str) -> None:
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        INSERT INTO auth (id, password_hash, is_initialized)
        VALUES (1, ?, 1)
        ON CONFLICT(id) DO UPDATE SET
            password_hash = excluded.password_hash,
            is_initialized = 1
    """, (hash_str,))
    conn.commit()
    conn.close()


def set_auth_pw(hash_str: str) -> None:
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE auth SET password_hash = ? WHERE id = 1", (hash_str,))
    conn.commit()
    conn.close()


def redact_secrets(svc: dict) -> dict:
    row = dict(svc)
    if row.get("apikey"):
        row["apikey"] = "••••••••"
        row["has_apikey"] = True
    else:
        row["has_apikey"] = False

    if row.get("password"):
        row["password"] = "••••••••"
        row["has_password"] = True
    else:
        row["has_password"] = False
    return row


def insert_service(
    name: str,
    service_type: str,
    base_url: str,
    apikey: str | None = None,
    username: str | None = None,
    password: str | None = None,
    is_enabled: int = 1,
    display_order: int = 0,
    config_json: str | None = None,
) -> int:
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        """INSERT INTO services (
            name, service_type, base_url, apikey, username, password, is_enabled, display_order, config_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            name,
            service_type,
            base_url,
            apikey,
            username,
            password,
            is_enabled,
            display_order,
            config_json,
        ),
    )
    res = c.lastrowid
    conn.commit()
    conn.close()
    return res


def fetch_services(include_secrets: bool = False) -> list[dict]:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM services ORDER BY display_order ASC, id ASC")
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    if not include_secrets:
        return [redact_secrets(r) for r in rows]
    return rows


def fetch_service_by_id(sid: int, include_secrets: bool = False) -> dict | None:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM services WHERE id = ?", (sid,))
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    if not include_secrets:
        return redact_secrets(d)
    return d


def modify_service(
    sid: int,
    name: str,
    service_type: str,
    base_url: str,
    apikey: str | None,
    username: str | None,
    password: str | None,
    is_enabled: int,
    display_order: int,
    config_json: str | None,
) -> bool:
    conn = get_conn()
    c = conn.cursor()

    c.execute("SELECT apikey, password FROM services WHERE id = ?", (sid,))
    cur = c.fetchone()
    if not cur:
        conn.close()
        return False

    final_key = cur["apikey"] if apikey == "••••••••" else apikey
    final_pw = cur["password"] if password == "••••••••" else password

    c.execute(
        """UPDATE services SET 
            name = ?, service_type = ?, base_url = ?, apikey = ?, username = ?, 
            password = ?, is_enabled = ?, display_order = ?, config_json = ? 
        WHERE id = ?""",
        (
            name,
            service_type,
            base_url,
            final_key,
            username,
            final_pw,
            is_enabled,
            display_order,
            config_json,
            sid,
        ),
    )
    n = c.rowcount
    conn.commit()
    conn.close()
    return n > 0


def remove_service(sid: int) -> bool:
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM services WHERE id = ?", (sid,))
    n = c.rowcount
    conn.commit()
    conn.close()
    return n > 0


def insert_metric(sid: int, status: str, ms: int) -> int:
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "INSERT INTO service_metrics (service_id, status, response_time_ms) VALUES (?, ?, ?)",
        (sid, status, ms),
    )
    new_id = c.lastrowid
    conn.commit()
    conn.close()
    return new_id


def fetch_metrics(sid: int, limit: int = 50) -> list[dict]:
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        """SELECT id, service_id, last_poll_ts, status, response_time_ms 
           FROM service_metrics 
           WHERE service_id = ? 
           ORDER BY id DESC 
           LIMIT ?""",
        (sid, limit),
    )
    res = [dict(r) for r in c.fetchall()]
    conn.close()
    return res


def fetch_recent_metrics_grouped(limit_per_service: int = 10) -> dict[int, list[dict]]:
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        """SELECT sm.id, sm.service_id, sm.last_poll_ts, sm.status, sm.response_time_ms
           FROM service_metrics sm
           WHERE sm.id IN (
               SELECT id FROM service_metrics sm2 
               WHERE sm2.service_id = sm.service_id 
               ORDER BY id DESC 
               LIMIT ?
           )
           ORDER BY sm.service_id ASC, sm.id DESC""",
        (limit_per_service,),
    )
    out: dict[int, list[dict]] = {}
    for r in c.fetchall():
        item = dict(r)
        out.setdefault(item["service_id"], []).append(item)
    conn.close()
    return out


def purge_old_metrics(keep_per_service: int = 100) -> None:
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        DELETE FROM service_metrics 
        WHERE id NOT IN (
            SELECT id FROM (
                SELECT id, ROW_NUMBER() OVER (PARTITION BY service_id ORDER BY id DESC) as rn
                FROM service_metrics
            ) WHERE rn <= ?
        )
    """, (keep_per_service,))
    conn.commit()
    conn.close()


def fetch_preferences() -> dict[str, str]:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT preference_key, preference_val FROM ui_preferences")
    d = {r["preference_key"]: r["preference_val"] for r in c.fetchall()}
    conn.close()
    return d


def fetch_preference(key: str, default: str | None = None) -> str | None:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT preference_val FROM ui_preferences WHERE preference_key = ?", (key,))
    r = c.fetchone()
    conn.close()
    return r["preference_val"] if r else default


def upsert_preference(key: str, val: str) -> None:
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        INSERT INTO ui_preferences (preference_key, preference_val)
        VALUES (?, ?)
        ON CONFLICT(preference_key) DO UPDATE SET preference_val = excluded.preference_val
    """, (key, val))
    conn.commit()
    conn.close()


def remove_preference(key: str) -> bool:
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM ui_preferences WHERE preference_key = ?", (key,))
    n = c.rowcount
    conn.commit()
    conn.close()
    return n > 0


connect_db = get_conn
create_tables = init_db
is_auth_initialized = has_auth
get_auth = read_auth
init_auth = set_initial_auth
update_auth_password = set_auth_pw
mask_service_secrets = redact_secrets
add_service = insert_service
get_all_services = fetch_services
get_service = fetch_service_by_id
update_service = modify_service
delete_service = remove_service
add_service_metric = insert_metric
get_service_metrics = fetch_metrics
get_recent_metrics_all = fetch_recent_metrics_grouped
prune_old_metrics = purge_old_metrics
get_all_preferences = fetch_preferences
get_preference = fetch_preference
set_preference = upsert_preference
delete_preference = remove_preference
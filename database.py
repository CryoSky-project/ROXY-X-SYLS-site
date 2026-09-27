import sqlite3
import os
from datetime import datetime, timedelta

DATABASE_URL = os.getenv("DATABASE_URL")
_using_postgres = False

def get_connection():
    global _using_postgres
    if DATABASE_URL:
        try:
            import psycopg2
            conn = psycopg2.connect(DATABASE_URL)
            _using_postgres = True
            return conn
        except Exception as e:
            print(f"Warning: PostgreSQL connection failed ({e}). Falling back to local SQLite keys.db...")
            _using_postgres = False
            return sqlite3.connect("keys.db")
    else:
        _using_postgres = False
        return sqlite3.connect("keys.db")

def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    is_postgres = _using_postgres
    
    if is_postgres:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key VARCHAR(50) PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS patch_files (
                id SERIAL PRIMARY KEY,
                file_name VARCHAR(255) NOT NULL,
                file_data BYTEA NOT NULL,
                uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS license_keys (
                key VARCHAR(50) PRIMARY KEY,
                file_id INTEGER NOT NULL REFERENCES patch_files(id) ON DELETE CASCADE,
                duration_days INTEGER DEFAULT 3,
                max_devices INTEGER DEFAULT 1,
                is_disabled BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                activated_at TIMESTAMP,
                expires_at TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS active_users (
                id SERIAL PRIMARY KEY,
                key VARCHAR(50) NOT NULL REFERENCES license_keys(key) ON DELETE CASCADE,
                device_id VARCHAR(100) NOT NULL,
                activated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS banned_users (
                device_id VARCHAR(100) PRIMARY KEY,
                reason VARCHAR(255) DEFAULT 'Banned by admin',
                banned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS muted_users (
                device_id VARCHAR(100) PRIMARY KEY,
                muted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS chat_messages (
                id SERIAL PRIMARY KEY,
                device_id VARCHAR(100) NOT NULL,
                sender VARCHAR(50) NOT NULL,
                message TEXT NOT NULL,
                sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                username VARCHAR(50) PRIMARY KEY,
                password_hash VARCHAR(255) NOT NULL,
                balance NUMERIC(10, 2) DEFAULT 0.00,
                role VARCHAR(20) DEFAULT 'user',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        try:
            cursor.execute("ALTER TABLE license_keys ADD COLUMN IF NOT EXISTS is_disabled BOOLEAN DEFAULT FALSE;")
            cursor.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS balance NUMERIC(10, 2) DEFAULT 0.00;")
            cursor.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS device_id VARCHAR(255);")
            cursor.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS google_id VARCHAR(255);")
            cursor.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS email VARCHAR(255);")
            cursor.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS role VARCHAR(20) DEFAULT 'user';")
            cursor.execute("ALTER TABLE patch_files ADD COLUMN IF NOT EXISTS external_url TEXT DEFAULT NULL;")
            cursor.execute("ALTER TABLE patch_files ALTER COLUMN file_data DROP NOT NULL;")
        except Exception as e:
            print(f"PostgreSQL migration notice: {e}")
    else:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS patch_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_name TEXT NOT NULL,
                file_data BLOB,
                uploaded_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS license_keys (
                key TEXT PRIMARY KEY,
                file_id INTEGER NOT NULL,
                duration_days INTEGER DEFAULT 3,
                max_devices INTEGER DEFAULT 1,
                is_disabled INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                activated_at TEXT,
                expires_at TEXT,
                FOREIGN KEY (file_id) REFERENCES patch_files (id) ON DELETE CASCADE
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS active_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT NOT NULL,
                device_id TEXT NOT NULL,
                activated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (key) REFERENCES license_keys (key) ON DELETE CASCADE
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS banned_users (
                device_id TEXT PRIMARY KEY,
                reason TEXT DEFAULT 'Banned by admin',
                banned_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS muted_users (
                device_id TEXT PRIMARY KEY,
                muted_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                sender TEXT NOT NULL,
                message TEXT NOT NULL,
                sent_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL,
                balance REAL DEFAULT 0.00,
                role TEXT DEFAULT 'user',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        try:
            cursor.execute("ALTER TABLE license_keys ADD COLUMN is_disabled INTEGER DEFAULT 0;")
        except Exception:
            pass
        try:
            cursor.execute("ALTER TABLE users ADD COLUMN device_id TEXT;")
            cursor.execute("ALTER TABLE users ADD COLUMN google_id TEXT;")
            cursor.execute("ALTER TABLE users ADD COLUMN email TEXT;")
        except Exception:
            pass
        try:
            cursor.execute("ALTER TABLE users ADD COLUMN balance REAL DEFAULT 0.00;")
        except Exception:
            pass
        try:
            cursor.execute("ALTER TABLE patch_files ADD COLUMN external_url TEXT;")
        except Exception:
            pass
    conn.commit()
    conn.close()
import json

def get_app_update_settings():
    conn = get_connection()
    cursor = conn.cursor()
    is_postgres = _using_postgres
    try:
        if is_postgres:
            cursor.execute("SELECT value FROM settings WHERE key = %s", ("app_update",))
        else:
            cursor.execute("SELECT value FROM settings WHERE key = ?", ("app_update",))
        row = cursor.fetchone()
        conn.close()
        if row and row[0]:
            return json.loads(row[0])
        return {
            "force_update": False,
            "latest_version_code": 1,
            "latest_version_name": "1.0",
            "download_url": "",
            "release_notes": "Minor bug fixes."
        }
    except Exception as e:
        conn.close()
        print(f"Error getting app update settings: {e}")
        return {
            "force_update": False,
            "latest_version_code": 1,
            "latest_version_name": "1.0",
            "download_url": "",
            "release_notes": ""
        }

def set_app_update_settings(settings_dict):
    conn = get_connection()
    cursor = conn.cursor()
    is_postgres = _using_postgres
    val = json.dumps(settings_dict)
    try:
        if is_postgres:
            cursor.execute("""
                INSERT INTO settings (key, value) VALUES (%s, %s)
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
            """, ("app_update", val))
        else:
            cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", ("app_update", val))
        conn.commit()
        conn.close()
    except Exception as e:
        conn.close()
        print(f"Error setting app update settings: {e}")

def get_org_lib_url():
    conn = get_connection()
    cursor = conn.cursor()
    is_postgres = _using_postgres
    try:
        if is_postgres:
            cursor.execute("SELECT value FROM settings WHERE key = %s", ("org_lib_url",))
        else:
            cursor.execute("SELECT value FROM settings WHERE key = ?", ("org_lib_url",))
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else ""
    except Exception:
        conn.close()
        return ""

def set_org_lib_url(url: str):
    conn = get_connection()
    cursor = conn.cursor()
    is_postgres = _using_postgres
    try:
        if is_postgres:
            cursor.execute("""
                INSERT INTO settings (key, value) VALUES (%s, %s)
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
            """, ("org_lib_url", url))
        else:
            cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", ("org_lib_url", url))
        conn.commit()
        conn.close()
    except Exception as e:
        conn.close()

def clear_all_files():
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM patch_files")
        conn.commit()
        conn.close()
        set_org_lib_url("")
        return True
    except Exception as e:
        conn.close()
        return False

def add_version_history(version_data):
    conn = get_connection()
    cursor = conn.cursor()
    is_postgres = _using_postgres
    try:
        if is_postgres:
            cursor.execute("SELECT value FROM settings WHERE key = %s", ("app_versions_history",))
        else:
            cursor.execute("SELECT value FROM settings WHERE key = ?", ("app_versions_history",))
        row = cursor.fetchone()
        
        history = []
        if row and row[0]:
            history = json.loads(row[0])
            
        # Add timestamp
        version_data["saved_at"] = str(datetime.utcnow())
        history.insert(0, version_data)
        history = history[:20]  # Keep last 20
        
        val = json.dumps(history)
        if is_postgres:
            cursor.execute("""
                INSERT INTO settings (key, value) VALUES (%s, %s)
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
            """, ("app_versions_history", val))
        else:
            cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", ("app_versions_history", val))
        conn.commit()
        conn.close()
    except Exception as e:
        conn.close()

def get_version_history():
    conn = get_connection()
    cursor = conn.cursor()
    is_postgres = _using_postgres
    try:
        if is_postgres:
            cursor.execute("SELECT value FROM settings WHERE key = %s", ("app_versions_history",))
        else:
            cursor.execute("SELECT value FROM settings WHERE key = ?", ("app_versions_history",))
        row = cursor.fetchone()
        conn.close()
        if row and row[0]:
            return json.loads(row[0])
        return []
    except Exception:
        conn.close()
        return []

def get_admin_password():
    conn = get_connection()
    cursor = conn.cursor()
    is_postgres = DATABASE_URL is not None
    try:
        if is_postgres:
            cursor.execute("SELECT value FROM settings WHERE key = %s", ("admin_password",))
        else:
            cursor.execute("SELECT value FROM settings WHERE key = ?", ("admin_password",))
        row = cursor.fetchone()
        conn.close()
        if row and row[0]:
            return row[0]
    except Exception:
        conn.close()
    return os.getenv("ADMIN_PASSWORD", "ADMIN8X34Y719")

def set_admin_password(new_pass: str):
    conn = get_connection()
    cursor = conn.cursor()
    is_postgres = _using_postgres
    if is_postgres:
        cursor.execute("INSERT INTO settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", ("admin_password", new_pass))
    else:
        cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", ("admin_password", new_pass))
    conn.commit()
    conn.close()

def get_github_settings():
    conn = get_connection()
    cursor = conn.cursor()
    is_postgres = _using_postgres
    token = os.getenv("GITHUB_TOKEN", "")
    repo = os.getenv("GITHUB_REPO", "CryoSky-project/SKYLS-X-HACK-site")
    try:
        if is_postgres:
            cursor.execute("SELECT value FROM settings WHERE key = %s", ("github_token",))
        else:
            cursor.execute("SELECT value FROM settings WHERE key = ?", ("github_token",))
        row = cursor.fetchone()
        if row and row[0]:
            token = row[0]
            
        if is_postgres:
            cursor.execute("SELECT value FROM settings WHERE key = %s", ("github_repo",))
        else:
            cursor.execute("SELECT value FROM settings WHERE key = ?", ("github_repo",))
        row = cursor.fetchone()
        if row and row[0]:
            repo = row[0]
    except Exception:
        pass
    conn.close()
    return {"token": token, "repo": repo}

def set_github_settings(token: str, repo: str):
    # If user provided a full URL, extract owner/repo
    repo = repo.replace("https://github.com/", "").replace("http://github.com/", "")
    if repo.endswith(".git"):
        repo = repo[:-4]
    repo = repo.strip("/")
    conn = get_connection()
    cursor = conn.cursor()
    is_postgres = _using_postgres
    if is_postgres:
        cursor.execute("INSERT INTO settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", ("github_token", token))
        cursor.execute("INSERT INTO settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", ("github_repo", repo))
    else:
        cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", ("github_token", token))
        cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", ("github_repo", repo))
    conn.commit()
    conn.close()

# --- FILE OPERATIONS ---

def save_file(file_name: str, file_data: bytes = None, external_url: str = None):
    conn = get_connection()
    cursor = conn.cursor()
    is_postgres = _using_postgres
    now = datetime.utcnow()
    uploaded_at = now if is_postgres else now.isoformat()
    
    if is_postgres:
        cursor.execute(
            "INSERT INTO patch_files (file_name, file_data, external_url, uploaded_at) VALUES (%s, %s, %s, %s) RETURNING id",
            (file_name, file_data, external_url, uploaded_at)
        )
        file_id = cursor.fetchone()[0]
    else:
        cursor.execute(
            "INSERT INTO patch_files (file_name, file_data, external_url, uploaded_at) VALUES (?, ?, ?, ?)",
            (file_name, file_data, external_url, uploaded_at)
        )
        file_id = cursor.lastrowid
        
    conn.commit()
    conn.close()
    return file_id

def get_all_files():
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id, file_name, uploaded_at, external_url FROM patch_files ORDER BY uploaded_at DESC")
    except Exception:
        cursor.execute("SELECT id, file_name, uploaded_at, NULL as external_url FROM patch_files ORDER BY uploaded_at DESC")
    rows = cursor.fetchall()
    conn.close()
    return rows

def get_file_by_id(file_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    is_postgres = _using_postgres
    try:
        if is_postgres:
            cursor.execute("SELECT file_name, file_data, external_url FROM patch_files WHERE id = %s", (file_id,))
        else:
            cursor.execute("SELECT file_name, file_data, external_url FROM patch_files WHERE id = ?", (file_id,))
    except Exception:
        if is_postgres:
            cursor.execute("SELECT file_name, file_data, NULL as external_url FROM patch_files WHERE id = %s", (file_id,))
        else:
            cursor.execute("SELECT file_name, file_data, NULL as external_url FROM patch_files WHERE id = ?", (file_id,))
    row = cursor.fetchone()
    conn.close()
    return row

def delete_file(file_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    is_postgres = _using_postgres
    if is_postgres:
        cursor.execute("DELETE FROM license_keys WHERE file_id = %s", (file_id,))
        cursor.execute("DELETE FROM patch_files WHERE id = %s", (file_id,))
    else:
        cursor.execute("DELETE FROM license_keys WHERE file_id = ?", (file_id,))
        cursor.execute("DELETE FROM patch_files WHERE id = ?", (file_id,))
    conn.commit()
    conn.close()

# --- LICENSE KEY OPERATIONS ---

def create_key(key: str, file_id: int, duration_days: int = 3, max_devices: int = 1, expires_at=None):
    conn = get_connection()
    cursor = conn.cursor()
    is_postgres = DATABASE_URL is not None
    now = datetime.utcnow()
    created_at = now if is_postgres else now.isoformat()
    
    if is_postgres:
        cursor.execute(
            "INSERT INTO license_keys (key, file_id, duration_days, max_devices, created_at, expires_at) VALUES (%s, %s, %s, %s, %s, %s)",
            (key, file_id, duration_days, max_devices, created_at, expires_at)
        )
    else:
        cursor.execute(
            "INSERT INTO license_keys (key, file_id, duration_days, max_devices, created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?)",
            (key, file_id, duration_days, max_devices, created_at, expires_at)
        )
    conn.commit()
    conn.close()

def get_all_keys():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT k.key, k.file_id, k.duration_days, k.max_devices, k.created_at, k.activated_at, k.expires_at, f.file_name,
               (SELECT COUNT(*) FROM active_users u WHERE u.key = k.key) as active_devices_count,
               k.is_disabled
        FROM license_keys k
        LEFT JOIN patch_files f ON k.file_id = f.id
        ORDER BY k.created_at DESC
    """)
    rows = cursor.fetchall()
    conn.close()
    return rows

def is_device_banned(device_id: str) -> bool:
    conn = get_connection()
    cursor = conn.cursor()
    is_postgres = DATABASE_URL is not None
    if is_postgres:
        cursor.execute("SELECT device_id FROM banned_users WHERE device_id = %s", (device_id,))
    else:
        cursor.execute("SELECT device_id FROM banned_users WHERE device_id = ?", (device_id,))
    row = cursor.fetchone()
    conn.close()
    return row is not None

def ban_device(device_id: str, reason: str = "Banned by admin"):
    conn = get_connection()
    cursor = conn.cursor()
    is_postgres = DATABASE_URL is not None
    now = datetime.utcnow()
    banned_at = now if is_postgres else now.isoformat()
    if is_postgres:
        cursor.execute("INSERT INTO banned_users (device_id, reason, banned_at) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING", (device_id, reason, banned_at))
    else:
        cursor.execute("INSERT OR IGNORE INTO banned_users (device_id, reason, banned_at) VALUES (?, ?, ?)", (device_id, reason, banned_at))
    conn.commit()
    conn.close()

def unban_device(device_id: str):
    conn = get_connection()
    cursor = conn.cursor()
    is_postgres = DATABASE_URL is not None
    if is_postgres:
        cursor.execute("DELETE FROM banned_users WHERE device_id = %s", (device_id,))
    else:
        cursor.execute("DELETE FROM banned_users WHERE device_id = ?", (device_id,))
    conn.commit()
    conn.close()

def mute_device(device_id: str):
    conn = get_connection()
    cursor = conn.cursor()
    is_postgres = DATABASE_URL is not None
    now = datetime.utcnow()
    muted_at = now if is_postgres else now.isoformat()
    if is_postgres:
        cursor.execute("INSERT INTO muted_users (device_id, muted_at) VALUES (%s, %s) ON CONFLICT DO NOTHING", (device_id, muted_at))
    else:
        cursor.execute("INSERT OR IGNORE INTO muted_users (device_id, muted_at) VALUES (?, ?)", (device_id, muted_at))
    conn.commit()
    conn.close()

def unmute_device(device_id: str):
    conn = get_connection()
    cursor = conn.cursor()
    is_postgres = DATABASE_URL is not None
    if is_postgres:
        cursor.execute("DELETE FROM muted_users WHERE device_id = %s", (device_id,))
    else:
        cursor.execute("DELETE FROM muted_users WHERE device_id = ?", (device_id,))
    conn.commit()
    conn.close()

def set_key_disabled(key: str, disabled: bool):
    conn = get_connection()
    cursor = conn.cursor()
    is_postgres = DATABASE_URL is not None
    val = disabled if is_postgres else (1 if disabled else 0)
    if is_postgres:
        cursor.execute("UPDATE license_keys SET is_disabled = %s WHERE key = %s", (val, key))
    else:
        cursor.execute("UPDATE license_keys SET is_disabled = ? WHERE key = ?", (val, key))
    conn.commit()
    conn.close()

def add_days_to_key(key: str, extra_days: int):
    conn = get_connection()
    cursor = conn.cursor()
    is_postgres = DATABASE_URL is not None
    if is_postgres:
        cursor.execute("SELECT activated_at, expires_at, duration_days FROM license_keys WHERE key = %s", (key,))
    else:
        cursor.execute("SELECT activated_at, expires_at, duration_days FROM license_keys WHERE key = ?", (key,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return
    act, exp, dur = row
    new_dur = (dur or 0) + extra_days
    
    if exp:
        try:
            exp_dt = datetime.fromisoformat(str(exp).replace("Z", "+00:00").split(".")[0])
        except Exception:
            exp_dt = datetime.strptime(str(exp).split(".")[0], "%Y-%m-%d %H:%M:%S")
        new_exp = exp_dt + timedelta(days=extra_days)
        new_exp_str = new_exp if is_postgres else new_exp.isoformat()
        if is_postgres:
            cursor.execute("UPDATE license_keys SET duration_days = %s, expires_at = %s WHERE key = %s", (new_dur, new_exp_str, key))
        else:
            cursor.execute("UPDATE license_keys SET duration_days = ?, expires_at = ? WHERE key = ?", (new_dur, new_exp_str, key))
    else:
        if is_postgres:
            cursor.execute("UPDATE license_keys SET duration_days = %s WHERE key = %s", (new_dur, key))
        else:
            cursor.execute("UPDATE license_keys SET duration_days = ? WHERE key = ?", (new_dur, key))
    conn.commit()
    conn.close()

def verify_key(key: str, device_id: str):
    if is_device_banned(device_id):
        return {"status": "banned", "message": "Device is banned"}

    if key == "ADMIN8X34Y719" or key == get_admin_password():
        return {
            "status": "admin_success",
            "role": "admin",
            "expires_at": "2099-12-31T23:59:59Z",
            "file_id": 1,
            "message": "Welcome Admin"
        }

    conn = get_connection()
    cursor = conn.cursor()
    is_postgres = DATABASE_URL is not None
    
    if is_postgres:
        cursor.execute("SELECT file_id, duration_days, max_devices, activated_at, expires_at, is_disabled FROM license_keys WHERE key = %s", (key,))
    else:
        cursor.execute("SELECT file_id, duration_days, max_devices, activated_at, expires_at, is_disabled FROM license_keys WHERE key = ?", (key,))
        
    row = cursor.fetchone()
    if not row:
        conn.close()
        return {"status": "invalid", "message": "Key not found"}
        
    file_id, duration_days, max_devices, db_activated_at, db_expires_at, is_disabled = row

    if is_disabled:
        conn.close()
        return {"status": "disabled", "message": "Key has been disabled by admin"}

    now = datetime.utcnow()
    
    def parse_date(val):
        if not val:
            return None
        if isinstance(val, datetime):
            return val
        try:
            return datetime.fromisoformat(val)
        except Exception:
            return datetime.strptime(val.split('.')[0], "%Y-%m-%d %H:%M:%S")
            
    activated_at_dt = parse_date(db_activated_at)
    expires_at_dt = parse_date(db_expires_at)
    
    if is_postgres:
        cursor.execute("SELECT device_id FROM active_users WHERE key = %s", (key,))
    else:
        cursor.execute("SELECT device_id FROM active_users WHERE key = ?", (key,))
    registered_devices = [r[0] for r in cursor.fetchall()]
    
    if device_id in registered_devices:
        if expires_at_dt and now > expires_at_dt:
            conn.close()
            return {"status": "expired", "message": "Key has expired"}
        conn.close()
        return {
            "status": "success", 
            "expires_at": expires_at_dt.isoformat() if expires_at_dt else None,
            "file_id": file_id
        }
        
    if len(registered_devices) < max_devices:
        activated_at_str = now if is_postgres else now.isoformat()
        
        if not activated_at_dt:
            if not expires_at_dt:
                expires_at_dt = now + timedelta(days=duration_days)
            expires_at_str = expires_at_dt if is_postgres else expires_at_dt.isoformat()
            
            if is_postgres:
                cursor.execute(
                    "UPDATE license_keys SET activated_at = %s, expires_at = %s WHERE key = %s",
                    (activated_at_str, expires_at_str, key)
                )
            else:
                cursor.execute(
                    "UPDATE license_keys SET activated_at = ?, expires_at = ? WHERE key = ?",
                    (activated_at_str, expires_at_str, key)
                )
            
        if is_postgres:
            cursor.execute(
                "INSERT INTO active_users (key, device_id, activated_at) VALUES (%s, %s, %s)",
                (key, device_id, activated_at_str)
            )
        else:
            cursor.execute(
                "INSERT INTO active_users (key, device_id, activated_at) VALUES (?, ?, ?)",
                (key, device_id, activated_at_str)
            )
            
        conn.commit()
        conn.close()
        
        target_expiry = expires_at_dt or (now + timedelta(days=duration_days))
        return {
            "status": "success", 
            "expires_at": target_expiry.isoformat(),
            "file_id": file_id,
            "role": "user"
        }
    else:
        conn.close()
        return {"status": "device_mismatch", "message": "Key is bound to another device"}

def delete_key(key: str):
    conn = get_connection()
    cursor = conn.cursor()
    is_postgres = DATABASE_URL is not None
    if is_postgres:
        cursor.execute("DELETE FROM license_keys WHERE key = %s", (key,))
    else:
        cursor.execute("DELETE FROM license_keys WHERE key = ?", (key,))
    conn.commit()
    conn.close()

def get_active_devices():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT u.id, u.key, u.device_id, u.activated_at, k.expires_at, f.file_name,
               (SELECT COUNT(*) FROM banned_users b WHERE b.device_id = u.device_id) as is_banned,
               (SELECT COUNT(*) FROM muted_users m WHERE m.device_id = u.device_id) as is_muted
        FROM active_users u
        LEFT JOIN license_keys k ON u.key = k.key
        LEFT JOIN patch_files f ON k.file_id = f.id
        ORDER BY u.activated_at DESC
    """)
    rows = cursor.fetchall()
    conn.close()
    return rows

def send_chat_message(device_id: str, sender: str, message: str):
    conn = get_connection()
    cursor = conn.cursor()
    is_postgres = DATABASE_URL is not None
    now = datetime.utcnow()
    sent_at = now if is_postgres else now.isoformat()
    if is_postgres:
        cursor.execute("INSERT INTO chat_messages (device_id, sender, message, sent_at) VALUES (%s, %s, %s, %s)", (device_id, sender, message, sent_at))
    else:
        cursor.execute("INSERT INTO chat_messages (device_id, sender, message, sent_at) VALUES (?, ?, ?, ?)", (device_id, sender, message, sent_at))
    conn.commit()
    conn.close()

def get_chat_messages(device_id: str):
    conn = get_connection()
    cursor = conn.cursor()
    is_postgres = DATABASE_URL is not None
    if is_postgres:
        cursor.execute("SELECT id, device_id, sender, message, sent_at FROM chat_messages WHERE device_id = %s ORDER BY id ASC", (device_id,))
    else:
        cursor.execute("SELECT id, device_id, sender, message, sent_at FROM chat_messages WHERE device_id = ? ORDER BY id ASC", (device_id,))
    rows = cursor.fetchall()
    conn.close()
    return rows

def get_db_stats():
    import time
    start_time = time.time()
    conn = get_connection()
    cursor = conn.cursor()
    is_postgres = _using_postgres
    
    cursor.execute("SELECT 1")
    cursor.fetchone()
    ping_ms = round((time.time() - start_time) * 1000, 2)
    
    db_size_bytes = 0
    if is_postgres:
        try:
            cursor.execute("SELECT pg_database_size(current_database())")
            row = cursor.fetchone()
            if row and row[0]:
                db_size_bytes = row[0]
        except Exception:
            try:
                cursor.execute("""
                    SELECT SUM(pg_total_relation_size(quote_ident(schemaname) || '.' || quote_ident(tablename)))
                    FROM pg_tables WHERE schemaname = 'public'
                """)
                row = cursor.fetchone()
                if row and row[0]:
                    db_size_bytes = row[0]
            except Exception:
                db_size_bytes = 1.5 * 1024 * 1024
    else:
        if os.path.exists("keys.db"):
            db_size_bytes = os.path.getsize("keys.db")

    conn.close()
    db_size_mb = round(db_size_bytes / (1024 * 1024), 2)
    max_mb = 500.0
    used_percent = round((db_size_mb / max_mb) * 100, 1)

    return {
        "db_type": "PostgreSQL (Supabase)" if is_postgres else "SQLite",
        "ping_ms": ping_ms,
        "size_mb": db_size_mb,
        "max_mb": max_mb,
        "used_percent": used_percent
    }

# --- USER AUTH & BALANCE OPERATIONS ---

import hashlib

def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()

def register_user(username: str, password: str, device_id: str = "") -> dict:
    username = username.strip()
    if not username or not password:
        return {"status": "error", "message": "Username and password required"}
    
    conn = get_connection()
    cursor = conn.cursor()
    is_postgres = _using_postgres
    
    try:
        # Check if user exists
        if is_postgres:
            cursor.execute("SELECT username FROM users WHERE LOWER(username) = LOWER(%s)", (username,))
            if cursor.fetchone():
                return {"status": "error", "message": "Username already exists"}
            if device_id:
                cursor.execute("SELECT username FROM users WHERE device_id = %s", (device_id,))
                if cursor.fetchone():
                    return {"status": "error", "message": "This device is already registered to another account"}
        else:
            cursor.execute("SELECT username FROM users WHERE LOWER(username) = LOWER(?)", (username,))
            if cursor.fetchone():
                return {"status": "error", "message": "Username already exists"}
            if device_id:
                cursor.execute("SELECT username FROM users WHERE device_id = ?", (device_id,))
                if cursor.fetchone():
                    return {"status": "error", "message": "This device is already registered to another account"}
        
        pwd_hash = _hash_password(password)
        now = datetime.utcnow()
        created_at = now if is_postgres else now.isoformat()
        
        if is_postgres:
            cursor.execute("INSERT INTO users (username, password_hash, balance, role, created_at, device_id) VALUES (%s, %s, 0.00, 'user', %s, %s)", (username, pwd_hash, created_at, device_id))
        else:
            cursor.execute("INSERT INTO users (username, password_hash, balance, role, created_at, device_id) VALUES (?, ?, 0.00, 'user', ?, ?)", (username, pwd_hash, created_at, device_id))
        conn.commit()
        conn.close()
        return {"status": "success", "username": username, "balance": 0.00, "role": "user"}
    except Exception as e:
        conn.close()
        return {"status": "error", "message": str(e)}

def login_user(username: str, password: str, device_id: str = "") -> dict:
    username = username.strip()
    if not username or not password:
        return {"status": "error", "message": "Username and password required"}
        
    conn = get_connection()
    cursor = conn.cursor()
    is_postgres = _using_postgres
    pwd_hash = _hash_password(password)
    
    try:
        if is_postgres:
            cursor.execute("SELECT username, password_hash, balance, role, device_id FROM users WHERE LOWER(username) = LOWER(%s)", (username,))
        else:
            cursor.execute("SELECT username, password_hash, balance, role, device_id FROM users WHERE LOWER(username) = LOWER(?)", (username,))
        row = cursor.fetchone()
        
        if not row:
            conn.close()
            return {"status": "error", "message": "User not found"}
        
        u_name, u_hash, u_bal, u_role, u_device = row
        if device_id and u_device and u_device != device_id:
            conn.close()
            return {"status": "error", "message": "This account is bound to another device. You cannot login from this device."}
        
        if device_id and not u_device:
            if is_postgres:
                cursor.execute("UPDATE users SET device_id = %s WHERE username = %s", (device_id, u_name))
            else:
                cursor.execute("UPDATE users SET device_id = ? WHERE username = ?", (device_id, u_name))
            conn.commit()
            
        conn.close()
        if u_hash != pwd_hash:
            return {"status": "error", "message": "Incorrect password"}
            
        return {
            "status": "success",
            "username": u_name,
            "balance": float(u_bal or 0.0),
            "role": u_role or "user"
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

def get_user_info(username: str) -> dict:
    conn = get_connection()
    cursor = conn.cursor()
    is_postgres = _using_postgres
    try:
        if is_postgres:
            cursor.execute("SELECT username, balance, role, created_at FROM users WHERE LOWER(username) = LOWER(%s)", (username,))
        else:
            cursor.execute("SELECT username, balance, role, created_at FROM users WHERE LOWER(username) = LOWER(?)", (username,))
        row = cursor.fetchone()
        conn.close()
        if not row:
            return {"status": "error", "message": "User not found"}
        return {
            "status": "success",
            "username": row[0],
            "balance": float(row[1] or 0.0),
            "role": row[2] or "user",
            "created_at": str(row[3])
        }
    except Exception as e:
        conn.close()
        return {"status": "error", "message": str(e)}

def get_all_users() -> list:
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT username, balance, role, created_at FROM users ORDER BY created_at DESC")
        rows = cursor.fetchall()
        conn.close()
        result = []
        for r in rows:
            result.append({
                "username": r[0],
                "balance": float(r[1] or 0.0),
                "role": r[2] or "user",
                "created_at": str(r[3])
            })
        return result
    except Exception:
        conn.close()
        return []

def set_user_balance(username: str, amount: float, mode: str = "add") -> dict:
    conn = get_connection()
    cursor = conn.cursor()
    is_postgres = _using_postgres
    try:
        # First ensure user exists or get current balance
        if is_postgres:
            cursor.execute("SELECT username, balance FROM users WHERE LOWER(username) = LOWER(%s)", (username,))
        else:
            cursor.execute("SELECT username, balance FROM users WHERE LOWER(username) = LOWER(?)", (username,))
        row = cursor.fetchone()
        
        if not row:
            # Auto-create user if they don't exist yet
            pwd_hash = _hash_password("123456")
            now = datetime.utcnow()
            created_at = now if is_postgres else now.isoformat()
            new_bal = amount if mode == "set" or mode == "add" else 0.0
            if is_postgres:
                cursor.execute("INSERT INTO users (username, password_hash, balance, role, created_at) VALUES (%s, %s, %s, 'user', %s)", (username, pwd_hash, new_bal, created_at))
            else:
                cursor.execute("INSERT INTO users (username, password_hash, balance, role, created_at) VALUES (?, ?, ?, 'user', ?)", (username, pwd_hash, new_bal, created_at))
            conn.commit()
            conn.close()
            return {"status": "success", "username": username, "new_balance": float(new_bal)}
            
        real_username, current_bal = row
        current_bal = float(current_bal or 0.0)
        
        if mode == "add":
            new_bal = round(current_bal + amount, 2)
        else:
            new_bal = round(amount, 2)
            
        if new_bal < 0:
            new_bal = 0.0
            
        if is_postgres:
            cursor.execute("UPDATE users SET balance = %s WHERE username = %s", (new_bal, real_username))
        else:
            cursor.execute("UPDATE users SET balance = ? WHERE username = ?", (new_bal, real_username))
            
        conn.commit()
        conn.close()
        return {"status": "success", "username": real_username, "new_balance": new_bal}
    except Exception as e:
        conn.close()
        return {"status": "error", "message": str(e)}

def deduct_user_balance(username: str, cost: float) -> bool:
    conn = get_connection()
    cursor = conn.cursor()
    is_postgres = _using_postgres
    try:
        if is_postgres:
            cursor.execute("SELECT username, balance FROM users WHERE LOWER(username) = LOWER(%s)", (username,))
        else:
            cursor.execute("SELECT username, balance FROM users WHERE LOWER(username) = LOWER(?)", (username,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return False
            
        real_username, current_bal = row
        current_bal = float(current_bal or 0.0)
        if current_bal < cost:
            conn.close()
            return False
            
        new_bal = round(current_bal - cost, 2)
        if is_postgres:
            cursor.execute("UPDATE users SET balance = %s WHERE username = %s", (new_bal, real_username))
        else:
            cursor.execute("UPDATE users SET balance = ? WHERE username = ?", (new_bal, real_username))
        conn.commit()
        conn.close()
        return True
    except Exception:
        conn.close()
        return False


def change_user_password(username: str, old_password: str, new_password: str) -> dict:
    res = login_user(username, old_password, "")
    if res.get("status") == "error":
        return res
    conn = get_connection()
    cursor = conn.cursor()
    pwd_hash = _hash_password(new_password)
    try:
        if _using_postgres:
            cursor.execute("UPDATE users SET password_hash = %s WHERE username = %s", (pwd_hash, username))
        else:
            cursor.execute("UPDATE users SET password_hash = ? WHERE username = ?", (pwd_hash, username))
        conn.commit()
        conn.close()
        return {"status": "success"}
    except Exception as e:
        conn.close()
        return {"status": "error", "message": str(e)}

def google_auth_user(email: str, google_id: str, device_id: str) -> dict:
    if not email:
        return {"status": "error", "message": "Email is required for Google Sign-In"}
    username = email.split("@")[0]
    conn = get_connection()
    cursor = conn.cursor()
    is_postgres = _using_postgres
    try:
        if is_postgres:
            cursor.execute("SELECT username, balance, role, device_id FROM users WHERE google_id = %s OR email = %s", (google_id, email))
        else:
            cursor.execute("SELECT username, balance, role, device_id FROM users WHERE google_id = ? OR email = ?", (google_id, email))
        row = cursor.fetchone()
        
        if row:
            u_name, u_bal, u_role, u_device = row
            if device_id and u_device and u_device != device_id:
                return {"status": "error", "message": "Account bound to another device"}
            if device_id and not u_device:
                if is_postgres:
                    cursor.execute("UPDATE users SET device_id = %s WHERE username = %s", (device_id, u_name))
                else:
                    cursor.execute("UPDATE users SET device_id = ? WHERE username = ?", (device_id, u_name))
                conn.commit()
            return {"status": "success", "username": u_name, "balance": float(u_bal or 0.0), "role": u_role}
        
        # Register new
        if device_id:
            if is_postgres:
                cursor.execute("SELECT username FROM users WHERE device_id = %s", (device_id,))
            else:
                cursor.execute("SELECT username FROM users WHERE device_id = ?", (device_id,))
            if cursor.fetchone():
                return {"status": "error", "message": "This device is already registered"}
                
        now = datetime.utcnow()
        created_at = now if is_postgres else now.isoformat()
        pwd_hash = _hash_password(google_id) # Random fallback
        
        if is_postgres:
            cursor.execute("INSERT INTO users (username, password_hash, balance, role, created_at, device_id, google_id, email) VALUES (%s, %s, 0.00, 'user', %s, %s, %s, %s)", (username, pwd_hash, created_at, device_id, google_id, email))
        else:
            cursor.execute("INSERT INTO users (username, password_hash, balance, role, created_at, device_id, google_id, email) VALUES (?, ?, 0.00, 'user', ?, ?, ?, ?)", (username, pwd_hash, created_at, device_id, google_id, email))
        conn.commit()
        return {"status": "success", "username": username, "balance": 0.00, "role": "user"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        conn.close()


# auth.py — DB + usuarios + registro de módulos + tokens de login (magic link)
from __future__ import annotations
import os, sqlite3, json, base64, hashlib, hmac, time
from typing import Optional, Tuple, Dict, Any, List

DB_PATH = os.environ.get("SIRESET_DB_PATH", os.path.join(os.path.dirname(__file__), "sireset.db"))

def _connect():
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    """Crea tablas si no existen."""
    con = _connect(); cur = con.cursor()
    # Usuarios
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          email TEXT UNIQUE NOT NULL,
          name TEXT NOT NULL,
          role TEXT NOT NULL,
          pw_hash TEXT NOT NULL,
          active INTEGER NOT NULL DEFAULT 1,
          modules TEXT NOT NULL DEFAULT '[]'
        )
    """)
    # Módulos
    cur.execute("""
        CREATE TABLE IF NOT EXISTS modules (
          code TEXT PRIMARY KEY,
          title TEXT NOT NULL,
          file TEXT,
          func TEXT,
          enabled INTEGER NOT NULL DEFAULT 1
        )
    """)
    # Tokens de login persistente (URL ?tk=...)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS login_tokens (
          token_hash TEXT PRIMARY KEY,
          user_id INTEGER NOT NULL,
          expires INTEGER NOT NULL,
          active INTEGER NOT NULL DEFAULT 1,
          created_ts INTEGER NOT NULL,
          FOREIGN KEY(user_id) REFERENCES users(id)
        )
    """)
    con.commit(); con.close()

# ---------- Registro de módulos ----------
def ensure_builtin_modules():
    con = _connect(); cur = con.cursor()
    for code, title in [("Mougli", "Mougli"), ("Mapito", "Mapito")]:
        cur.execute("SELECT 1 FROM modules WHERE code=?", (code,))
        if cur.fetchone() is None:
            cur.execute(
                "INSERT INTO modules(code,title,file,func,enabled) VALUES(?,?,?,?,1)",
                (code, title, "", "",)
            )
    con.commit(); con.close()

def list_all_modules(enabled_only: bool=False) -> List[Dict[str, Any]]:
    con=_connect(); cur=con.cursor()
    if enabled_only:
        cur.execute("SELECT * FROM modules WHERE enabled=1 ORDER BY title")
    else:
        cur.execute("SELECT * FROM modules ORDER BY title")
    rows = cur.fetchall(); con.close()
    return [{
        "code": r["code"],
        "title": r["title"],
        "file": r["file"] or "",
        "func": r["func"] or "",
        "enabled": bool(r["enabled"]),
    } for r in rows]

def register_module(code: str, title: str, file: str, func: str="render", enabled: bool=True):
    code = code.strip()
    if not code or not title:
        raise ValueError("Código y título son obligatorios.")
    con=_connect(); cur=con.cursor()
    cur.execute("SELECT 1 FROM modules WHERE code=?", (code,))
    if cur.fetchone():
        raise ValueError("Ya existe un módulo con ese código.")
    cur.execute("""
        INSERT INTO modules(code,title,file,func,enabled)
        VALUES (?,?,?,?,?)
    """, (code, title, file, func, 1 if enabled else 0))
    con.commit(); con.close()

def update_module(code: str, *, title: Optional[str]=None, file: Optional[str]=None,
                  func: Optional[str]=None, enabled: Optional[bool]=None):
    con=_connect(); cur=con.cursor()
    sets=[]; vals=[]
    if title is not None: sets.append("title=?"); vals.append(title)
    if file  is not None: sets.append("file=?");  vals.append(file)
    if func  is not None: sets.append("func=?");  vals.append(func)
    if enabled is not None: sets.append("enabled=?"); vals.append(1 if enabled else 0)
    if not sets: 
        con.close(); return
    vals.append(code)
    cur.execute(f"UPDATE modules SET {', '.join(sets)} WHERE code=?", vals)
    con.commit(); con.close()

def delete_module(code: str):
    con=_connect(); cur=con.cursor()
    cur.execute("DELETE FROM modules WHERE code=?", (code,))
    con.commit(); con.close()

# ---------- Password hashing (PBKDF2-SHA256) ----------
_PBKDF2_ITERS = 240_000

def _hash_pw(password: str) -> str:
    if not isinstance(password, str):
        password = str(password)
    salt = os.urandom(16)
    import hashlib as _hl
    dk = _hl.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERS)
    return "pbkdf2${}${}${}".format(
        _PBKDF2_ITERS,
        base64.urlsafe_b64encode(salt).decode("ascii"),
        base64.urlsafe_b64encode(dk).decode("ascii"),
    )

def _verify_pw(password: str, stored: str) -> bool:
    try:
        scheme, iters, salt_b64, hash_b64 = stored.split("$", 3)
        if scheme != "pbkdf2":
            return False
        iters = int(iters)
        salt = base64.urlsafe_b64decode(salt_b64.encode("ascii"))
        target = base64.urlsafe_b64decode(hash_b64.encode("ascii"))
        import hashlib as _hl
        cand = _hl.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iters)
        return hmac.compare_digest(cand, target)
    except Exception:
        return False

# ---------- CRUD usuarios ----------
def admin_exists() -> bool:
    con=_connect(); cur=con.cursor()
    cur.execute("SELECT 1 FROM users WHERE role='admin' LIMIT 1")
    ok = cur.fetchone() is not None
    con.close()
    return ok

def _row_to_user(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "email": row["email"],
        "name": row["name"],
        "role": row["role"],
        "active": bool(row["active"]),
        "modules": json.loads(row["modules"] or "[]"),
    }

def find_user_by_email(email: str) -> Optional[Tuple[int, Dict[str, Any]]]:
    con=_connect(); cur=con.cursor()
    cur.execute("SELECT * FROM users WHERE email=?", (email.lower().strip(),))
    r = cur.fetchone(); con.close()
    if not r: return None
    return r["id"], _row_to_user(r)

def get_user(uid: int) -> Optional[Dict[str, Any]]:
    con=_connect(); cur=con.cursor()
    cur.execute("SELECT * FROM users WHERE id=?", (uid,))
    r=cur.fetchone(); con.close()
    return _row_to_user(r) if r else None

def list_users() -> list[Dict[str, Any]]:
    con=_connect(); cur=con.cursor()
    cur.execute("SELECT * FROM users ORDER BY id ASC")
    rows = cur.fetchall(); con.close()
    return [_row_to_user(r) for r in rows]

def _default_user_modules() -> list[str]:
    return [m["code"] for m in list_all_modules(enabled_only=True)]

def create_user(email: str, name: str, role: str, pwd: str, active: bool=True,
                modules: list[str] | None = None) -> int:
    modules = modules if modules is not None else _default_user_modules()
    pw_hash = _hash_pw(pwd)
    con=_connect(); cur=con.cursor()
    cur.execute("""
        INSERT INTO users(email,name,role,pw_hash,active,modules)
        VALUES (?,?,?,?,?,?)
    """, (email.lower().strip(), name.strip(), role.strip(), pw_hash, 1 if active else 0,
          json.dumps(modules)))
    con.commit()
    uid = cur.lastrowid
    con.close()
    return uid

def update_user(uid: int, *, name: Optional[str]=None, role: Optional[str]=None,
                pw_hash: Optional[str]=None, active: Optional[bool]=None,
                modules: Optional[list[str]]=None):
    con=_connect(); cur=con.cursor()
    sets=[]; vals=[]
    if name is not None: sets.append("name=?"); vals.append(name)
    if role is not None: sets.append("role=?"); vals.append(role)
    if pw_hash is not None: sets.append("pw_hash=?"); vals.append(pw_hash)
    if active is not None: sets.append("active=?"); vals.append(1 if active else 0)
    if modules is not None: sets.append("modules=?"); vals.append(json.dumps(modules))
    if not sets:
        con.close(); return
    vals.append(uid)
    cur.execute(f"UPDATE users SET {', '.join(sets)} WHERE id=?", vals)
    con.commit(); con.close()

def set_password(uid: int, new_pwd: str):
    update_user(uid, pw_hash=_hash_pw(new_pwd))

def authenticate(email: str, pwd: str) -> Optional[Dict[str, Any]]:
    con=_connect(); cur=con.cursor()
    cur.execute("SELECT * FROM users WHERE email=?", (email.lower().strip(),))
    r = cur.fetchone(); con.close()
    if not r: return None
    if not bool(r["active"]): return None
    if not _verify_pw(pwd, r["pw_hash"]): return None
    return _row_to_user(r)

# ---------- Tokens persistentes (magic link con ?tk=...) ----------
def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def create_login_token(user_id: int, days: int = 90) -> str:
    """Crea token aleatorio, lo guarda hasheado y retorna el token (para URL)."""
    raw = base64.urlsafe_b64encode(os.urandom(32)).decode("ascii").rstrip("=")
    token_hash = _sha256(raw)
    now = int(time.time())
    exp = now + days*24*60*60
    con=_connect(); cur=con.cursor()
    cur.execute("""
        INSERT OR REPLACE INTO login_tokens(token_hash,user_id,expires,active,created_ts)
        VALUES (?,?,?,?,?)
    """, (token_hash, user_id, exp, 1, now))
    con.commit(); con.close()
    return raw

def user_from_token(token: str) -> Optional[Dict[str, Any]]:
    if not token: return None
    token_hash = _sha256(token)
    now = int(time.time())
    con=_connect(); cur=con.cursor()
    cur.execute("""
        SELECT u.* FROM login_tokens t
        JOIN users u ON u.id=t.user_id
        WHERE t.token_hash=? AND t.active=1 AND t.expires>=?
    """, (token_hash, now))
    r = cur.fetchone()
    con.close()
    if not r: return None
    u = _row_to_user(r)
    if not u["active"]:
        return None
    return u

def revoke_token(token: str):
    token_hash = _sha256(token)
    con=_connect(); cur=con.cursor()
    cur.execute("UPDATE login_tokens SET active=0 WHERE token_hash=?", (token_hash,))
    con.commit(); con.close()

def revoke_all_tokens(user_id: int):
    con=_connect(); cur=con.cursor()
    cur.execute("UPDATE login_tokens SET active=0 WHERE user_id=?", (user_id,))
    con.commit(); con.close()

# al final de auth.py
login_form = sign_in   # o login, según cómo se llame en tu auth
login_ui   = login_form


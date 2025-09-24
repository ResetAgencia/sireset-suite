# auth.py — Autenticación + usuarios + registro de módulos + tokens persistentes
from __future__ import annotations  # <-- Debe ir primero

import os
import sqlite3
import json
import base64
import hashlib
import hmac
import time
import shutil
from typing import Optional, Tuple, Dict, Any, List

import streamlit as st

# --- Compatibilidad: si alguien llama experimental_rerun, usa st.rerun() ---
if not hasattr(st, "experimental_rerun"):
    def _compat_experimental_rerun():
        st.rerun()
    st.experimental_rerun = _compat_experimental_rerun


# =========================== Util: rerun compatible ===========================
def _safe_rerun():
    """Llama a st.rerun() y cae a experimental_rerun en versiones antiguas."""
    try:
        st.rerun()
    except Exception:
        try:
            st.experimental_rerun()  # fallback para Streamlit antiguos
        except Exception:
            pass


# =========================== Resolución de ruta de BD =========================
def _get_secret_or_env(key: str) -> Optional[str]:
    # 1) st.secrets, 2) os.environ, 3) None
    try:
        if key in st.secrets:
            val = st.secrets[key]
            if isinstance(val, str) and val.strip():
                return val.strip()
    except Exception:
        pass
    val = os.environ.get(key, "").strip()
    return val or None

def _default_persistent_db_path() -> str:
    # ~/.sireset/sireset.db (persistente por usuario)
    home = os.path.expanduser("~")
    base = os.path.join(home, ".sireset")
    return os.path.join(base, "sireset.db")

def _legacy_db_path_near_code() -> str:
    # Ruta anterior: junto al archivo auth.py
    return os.path.join(os.path.dirname(__file__), "sireset.db")

def _resolve_db_path() -> str:
    # Prioridad:
    # 1) SIRESET_DB_PATH en secrets o env
    # 2) ~/.sireset/sireset.db
    # Si existe BD legada junto al código y NO existe en el destino final, se migra.
    from_secrets_or_env = _get_secret_or_env("SIRESET_DB_PATH")
    target = from_secrets_or_env or _default_persistent_db_path()
    target_dir = os.path.dirname(target)
    os.makedirs(target_dir, exist_ok=True)

    legacy = _legacy_db_path_near_code()
    if os.path.isfile(legacy) and not os.path.isfile(target):
        try:
            shutil.copy2(legacy, target)
        except Exception:
            # Si falla la copia, seguimos usando target (se creará vacío)
            pass
    return target

DB_PATH = _resolve_db_path()

def db_path() -> str:
    """Ruta efectiva de la base de datos (para mostrar en UI si se desea)."""
    return DB_PATH


# =========================== Conexión y PRAGMAs ===============================
def _connect():
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    # PRAGMAs razonables para estabilidad de writes concurrentes
    try:
        con.execute("PRAGMA foreign_keys = ON;")
        con.execute("PRAGMA journal_mode = WAL;")
        con.execute("PRAGMA synchronous = NORMAL;")
    except Exception:
        pass
    return con

def init_db():
    """Crea tablas si no existen."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    con = _connect()
    cur = con.cursor()

    # Usuarios
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          email   TEXT UNIQUE NOT NULL,
          name    TEXT NOT NULL,
          role    TEXT NOT NULL,
          pw_hash TEXT NOT NULL,
          active  INTEGER NOT NULL DEFAULT 1,
          modules TEXT NOT NULL DEFAULT '[]'
        )
    """)

    # Módulos (Mougli/Mapito)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS modules (
          code    TEXT PRIMARY KEY,
          title   TEXT NOT NULL,
          file    TEXT,
          func    TEXT,
          enabled INTEGER NOT NULL DEFAULT 1
        )
    """)

    # Tokens de login persistente (?tk=...)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS login_tokens (
          token_hash TEXT PRIMARY KEY,
          user_id    INTEGER NOT NULL,
          expires    INTEGER NOT NULL,
          active     INTEGER NOT NULL DEFAULT 1,
          created_ts INTEGER NOT NULL,
          FOREIGN KEY(user_id) REFERENCES users(id)
        )
    """)

    con.commit()
    con.close()

def ensure_builtin_modules():
    """Registra Mougli y Mapito si no existen."""
    con = _connect()
    cur = con.cursor()
    for code, title in [("Mougli", "Mougli"), ("Mapito", "Mapito")]:
        cur.execute("SELECT 1 FROM modules WHERE code=?", (code,))
        if cur.fetchone() is None:
            cur.execute(
                "INSERT INTO modules(code,title,file,func,enabled) VALUES(?,?,?,?,1)",
                (code, title, "", ""),
            )
    con.commit()
    con.close()

def list_all_modules(enabled_only: bool = False) -> List[Dict[str, Any]]:
    con = _connect()
    cur = con.cursor()
    if enabled_only:
        cur.execute("SELECT * FROM modules WHERE enabled=1 ORDER BY title")
    else:
        cur.execute("SELECT * FROM modules ORDER BY title")
    rows = cur.fetchall()
    con.close()
    return [{
        "code":    r["code"],
        "title":   r["title"],
        "file":    r["file"] or "",
        "func":    r["func"] or "",
        "enabled": bool(r["enabled"]),
    } for r in rows]


# =========================== Password hashing ===========================
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


# =========================== CRUD de usuarios ===========================
def admin_exists() -> bool:
    con = _connect()
    cur = con.cursor()
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
    con = _connect()
    cur = con.cursor()
    cur.execute("SELECT * FROM users WHERE email=?", (email.lower().strip(),))
    r = cur.fetchone()
    con.close()
    if not r:
        return None
    return r["id"], _row_to_user(r)

def get_user(uid: int) -> Optional[Dict[str, Any]]:
    con = _connect()
    cur = con.cursor()
    cur.execute("SELECT * FROM users WHERE id=?", (uid,))
    r = cur.fetchone()
    con.close()
    return _row_to_user(r) if r else None

def list_users() -> List[Dict[str, Any]]:
    con = _connect()
    cur = con.cursor()
    cur.execute("SELECT * FROM users ORDER BY id ASC")
    rows = cur.fetchall()
    con.close()
    return [_row_to_user(r) for r in rows]

def _default_user_modules() -> List[str]:
    return [m["code"] for m in list_all_modules(enabled_only=True)]

def _backup_users_json():
    """Guarda un backup JSON de los usuarios por si algo sale mal (no bloquea flujo si falla)."""
    try:
        con = _connect()
        cur = con.cursor()
        cur.execute("SELECT * FROM users ORDER BY id ASC")
        rows = cur.fetchall()
        con.close()
        data = []
        for r in rows:
            data.append({
                "id": r["id"], "email": r["email"], "name": r["name"],
                "role": r["role"], "active": int(r["active"]),
                "modules": json.loads(r["modules"] or "[]")
            })
        backup_dir = os.path.join(os.path.dirname(DB_PATH), "backups")
        os.makedirs(backup_dir, exist_ok=True)
        ts = int(time.time())
        path = os.path.join(backup_dir, f"users_{ts}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass  # No interrumpir el flujo por fallas de backup

def create_user(email: str, name: str, role: str, pwd: str,
                active: bool = True, modules: Optional[List[str]] = None) -> int:
    modules = modules if modules is not None else _default_user_modules()
    pw_hash = _hash_pw(pwd)
    con = _connect()
    cur = con.cursor()
    cur.execute("""
        INSERT INTO users(email,name,role,pw_hash,active,modules)
        VALUES (?,?,?,?,?,?)
    """, (email.lower().strip(), name.strip(), role.strip(), pw_hash,
          1 if active else 0, json.dumps(modules)))
    con.commit()
    uid = cur.lastrowid
    con.close()
    _backup_users_json()
    return uid

def update_user(uid: int, *, name: Optional[str] = None, role: Optional[str] = None,
                pw_hash: Optional[str] = None, active: Optional[bool] = None,
                modules: Optional[List[str]] = None):
    con = _connect()
    cur = con.cursor()
    sets, vals = [], []
    if name    is not None: sets.append("name=?");    vals.append(name)
    if role    is not None: sets.append("role=?");    vals.append(role)
    if pw_hash is not None: sets.append("pw_hash=?"); vals.append(pw_hash)
    if active  is not None: sets.append("active=?");  vals.append(1 if active else 0)
    if modules is not None: sets.append("modules=?"); vals.append(json.dumps(modules))
    if not sets:
        con.close()
        return
    vals.append(uid)
    cur.execute(f"UPDATE users SET {', '.join(sets)} WHERE id=?", vals)
    con.commit()
    con.close()
    _backup_users_json()

def set_password(uid: int, new_pwd: str):
    update_user(uid, pw_hash=_hash_pw(new_pwd))

def authenticate(email: str, pwd: str) -> Optional[Dict[str, Any]]:
    con = _connect()
    cur = con.cursor()
    cur.execute("SELECT * FROM users WHERE email=?", (email.lower().strip(),))
    r = cur.fetchone()
    con.close()
    if not r:
        return None
    if not bool(r["active"]):
        return None
    if not _verify_pw(pwd, r["pw_hash"]):
        return None
    return _row_to_user(r)


# =========================== Tokens persistentes ===========================
def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def create_login_token(user_id: int, days: int = 90) -> str:
    raw = base64.urlsafe_b64encode(os.urandom(32)).decode("ascii").rstrip("=")
    token_hash = _sha256(raw)
    now = int(time.time())
    exp = now + days * 24 * 60 * 60
    con = _connect()
    cur = con.cursor()
    cur.execute("""
        INSERT OR REPLACE INTO login_tokens(token_hash,user_id,expires,active,created_ts)
        VALUES (?,?,?,?,?)
    """, (token_hash, user_id, exp, 1, now))
    con.commit()
    con.close()
    return raw

def user_from_token(token: str) -> Optional[Dict[str, Any]]:
    if not token:
        return None
    token_hash = _sha256(token)
    now = int(time.time())
    con = _connect()
    cur = con.cursor()
    cur.execute("""
        SELECT u.* FROM login_tokens t
        JOIN users u ON u.id=t.user_id
        WHERE t.token_hash=? AND t.active=1 AND t.expires>=?
    """, (token_hash, now))
    r = cur.fetchone()
    con.close()
    if not r:
        return None
    u = _row_to_user(r)
    if not u["active"]:
        return None
    return u

def revoke_token(token: str):
    token_hash = _sha256(token)
    con = _connect()
    cur = con.cursor()
    cur.execute("UPDATE login_tokens SET active=0 WHERE token_hash=?", (token_hash,))
    con.commit()
    con.close()

def revoke_all_tokens(user_id: int):
    con = _connect()
    cur = con.cursor()
    cur.execute("UPDATE login_tokens SET active=0 WHERE user_id=?", (user_id,))
    con.commit()
    con.close()


# =========================== Helpers de sesión/UI ===========================
def _get_query_params() -> Dict[str, Any]:
    try:
        # Streamlit 1.31+
        return dict(st.query_params)
    except Exception:
        # Compatibilidad con versiones anteriores
        return st.experimental_get_query_params()

def _set_query_params(**kwargs):
    try:
        st.query_params.clear()
        for k, v in kwargs.items():
            if v is None:
                continue
            st.query_params[k] = v
    except Exception:
        st.experimental_set_query_params(**{k: v for k, v in kwargs.items() if v is not None})

def _set_user(u: Optional[Dict[str, Any]]):
    st.session_state["user"] = u

def current_user() -> Optional[Dict[str, Any]]:
    return st.session_state.get("user")

def user_has_module(user: Optional[Dict[str, Any]], code: str) -> bool:
    if not user:
        return False
    if user.get("role") == "admin":
        return True
    return code in (user.get("modules") or [])


# =========================== UI pública ===========================
def _bootstrap_if_needed():
    """Crea el admin inicial si la BD está vacía y registra módulos base."""
    init_db()
    ensure_builtin_modules()
    if not admin_exists():
        st.info("No existe un administrador. Crea el primero para iniciar el sistema.")
        with st.form("create_admin", clear_on_submit=False):
            email = st.text_input("Email (admin)")
            name  = st.text_input("Nombre")
            pwd   = st.text_input("Contraseña", type="password")
            ok = st.form_submit_button("Crear administrador")
        if ok:
            if not email or not name or not pwd:
                st.error("Completa todos los campos.")
            else:
                create_user(email=email, name=name, role="admin", pwd=pwd, active=True)
                st.success("Administrador creado. Ahora puedes iniciar sesión.")
        st.stop()

def login_ui():
    """Dibuja el formulario de login y resuelve token persistente en URL."""
    _bootstrap_if_needed()

    # Auto-login por token ?tk=...
    q = _get_query_params()
    token = q.get("tk") or q.get("token")
    if isinstance(token, list):
        token = token[0] if token else None
    if token and not current_user():
        u = user_from_token(token)
        if u:
            _set_user(u)
            st.success(f"Autenticado como {u['name']}")
            return

    u = current_user()
    if u:
        st.success(f"Sesión iniciada: {u['name']} ({u['email']}) — rol: {u['role']}")
        return

    st.subheader("Iniciar sesión")
    with st.form("login_form", clear_on_submit=False):
        col1, col2 = st.columns(2)
        with col1:
            email = st.text_input("Email")
        with col2:
            pwd = st.text_input("Contraseña", type="password")
        remember = st.checkbox("Recordarme (guardar enlace con token)")
        submit = st.form_submit_button("Entrar")

    if submit:
        if not email or not pwd:
            st.error("Ingresa email y contraseña.")
            return
        authu = authenticate(email, pwd)
        if not authu:
            st.error("Credenciales inválidas o usuario inactivo.")
            return

        _set_user(authu)
        st.success(f"Bienvenido, {authu['name']}")

        if remember:
            res = find_user_by_email(email)
            if res:
                uid, _ = res
                raw = create_login_token(uid)
                _set_query_params(tk=raw)
                st.info("Se añadió ?tk=... en la URL. Guarda el enlace como marcador.")

def logout_button(label: str = "Cerrar sesión"):
    """Botón de cierre de sesión (si hay usuario)."""
    u = current_user()
    if not u:
        return
    if st.button(label):
        _set_user(None)
        _set_query_params()   # limpia parámetros (como tk)
        _safe_rerun()

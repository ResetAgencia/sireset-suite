# app.py — Suite SiReset con “Recordarme” por enlace (?tk=...) y rol Programador
import os, json, importlib.util
from pathlib import Path
import streamlit as st
import auth

# Núcleos internos
try:
    from core.mougli_core import procesar_monitor_outview
except Exception:
    procesar_monitor_outview = None
try:
    from core.mapito_core import build_map, export_png
except Exception:
    build_map = None
    export_png = None

st.set_page_config(page_title="SiReset Suite", layout="wide")
PURPLE = "#5f48c6"
BASE_DIR = Path(__file__).parent
ASSETS = BASE_DIR / "assets"; ASSETS.mkdir(exist_ok=True)
HEADER = ASSETS / "Encabezado.png"
if HEADER.exists():
    st.image(str(HEADER))
else:
    st.markdown(f"<h1 style='color:{PURPLE};margin:0'>SiReset</h1>", unsafe_allow_html=True)

MODULES_DIR = BASE_DIR / "modules"; MODULES_DIR.mkdir(exist_ok=True)

if "user" not in st.session_state: st.session_state["user"] = None
if "open_admin" not in st.session_state: st.session_state["open_admin"] = False
if "open_prog" not in st.session_state: st.session_state["open_prog"] = False

def ok(msg): st.success(msg, icon="✅")
def err(msg): st.error(msg, icon="🛑")

# ---------------- Utilidad URL params (compatibilidad versiones) ----------------
def _set_query_params(**params):
    try:
        # Streamlit >= 1.30
        st.query_params.update(params)
    except Exception:
        # Legacy
        st.experimental_set_query_params(**params)

def _get_query_param(name: str) -> str | None:
    try:
        val = st.query_params.get(name)
        if isinstance(val, list): 
            return val[0] if val else None
        return val
    except Exception:
        q = st.experimental_get_query_params()
        v = q.get(name)
        if not v: return None
        return v[0] if isinstance(v, list) else v

# ---------------- Pantallas ----------------
def first_admin_screen():
    st.subheader("Crear administrador inicial")
    with st.form("first_admin"):
        name = st.text_input("Nombre completo")
        email = st.text_input("Email")
        pwd1 = st.text_input("Contraseña", type="password")
        pwd2 = st.text_input("Confirmar contraseña", type="password")
        okb = st.form_submit_button("Crear admin", use_container_width=True)
    if okb:
        if not name or not email or not pwd1:
            err("Completa todos los campos."); return
        if pwd1 != pwd2:
            err("Las contraseñas no coinciden."); return
        try:
            auth.create_user(email=email, name=name, role="admin", pwd=pwd1,
                             active=True, modules=None)
            ok("Administrador creado. Inicia sesión.")
            st.rerun()
        except Exception as e:
            err(str(e))

def login_screen():
    st.subheader("Iniciar sesión")
    with st.form("login"):
        email = st.text_input("Email")
        pwd   = st.text_input("Contraseña", type="password")
        remember = st.checkbox("Recordarme en este equipo (enlace)", value=True)
        okb = st.form_submit_button("Entrar")
    if okb:
        u = auth.authenticate(email, pwd)
        if not u:
            err("Credenciales inválidas o usuario inactivo.")
        else:
            st.session_state.user = u
            ok(f"¡Bienvenido, {u['name']}!")

            # Recordarme: generamos token y lo colocamos en la URL para que lo guardes.
            if remember:
                token = auth.create_login_token(u["id"], days=90)
                current = _get_query_param("tk")
                if current != token:
                    _set_query_params(tk=token)
                st.info("Se generó un enlace directo. **Guarda esta página en Favoritos** para entrar sin contraseña.")
            st.rerun()

def sidebar_userbox():
    u = st.session_state.user
    if not u: return
    st.sidebar.write(f"**Usuario:** {u['name']}")
    st.sidebar.write("Rol:", u["role"])
    st.sidebar.markdown("---")
    # Enlace directo del usuario actual
    if st.sidebar.button("Generar enlace directo (Recordarme)"):
        token = auth.create_login_token(u["id"], days=90)
        _set_query_params(tk=token)
        st.sidebar.success("¡Listo! Guarda esta URL en favoritos.")
    # Cerrar sesión (no revoca el token, para que el enlace siga funcionando si lo guardaste)
    if st.sidebar.button("Cerrar sesión", use_container_width=True):
        st.session_state.user = None
        st.rerun()

# ---------- Panel de usuarios (admin) ----------
def panel_usuarios():
    st.markdown("### Panel de usuarios")
    users = auth.list_users()
    all_mods = auth.list_all_modules()
    mod_codes = [m["code"] for m in all_mods]
    mod_titles = {m["code"]: m["title"] for m in all_mods}
    if not users:
        st.info("No hay usuarios."); return
    for u in users:
        with st.expander(f"#{u['id']} · {u['email']}"):
            c1, c2, c3 = st.columns([2,1.2,1])
            with c1:
                name = st.text_input("Nombre", u["name"], key=f"un{u['id']}")
            with c2:
                role = st.selectbox("Rol", ["user","programmer","admin"],
                                    index=["user","programmer","admin"].index(u["role"]) if u["role"] in ["user","programmer","admin"] else 0,
                                    key=f"ur{u['id']}")
            with c3:
                active = st.checkbox("Activo", value=u["active"], key=f"ua{u['id']}")

            st.write("**Módulos:**")
            cols = st.columns(3)
            chosen = set(u["modules"] or [])
            newmods = []
            for i, code in enumerate(mod_codes):
                with cols[i % 3]:
                    chk = st.checkbox(mod_titles.get(code, code),
                                      value=(code in chosen),
                                      key=f"um{u['id']}:{code}")
                    if chk: newmods.append(code)

            newpass = st.text_input("Nueva contraseña", type="password", key=f"up{u['id']}")
            if st.button("Guardar", key=f"ug{u['id']}"):
                try:
                    auth.update_user(u["id"], name=name, role=role, active=active, modules=newmods)
                    if newpass:
                        auth.set_password(u["id"], newpass)
                    ok("Guardado.")
                    st.rerun()
                except Exception as e:
                    err(str(e))

    st.markdown("---")
    st.markdown("#### Crear usuario")
    enabled_mods = auth.list_all_modules(enabled_only=True)
    with st.form("create_user"):
        name  = st.text_input("Nombre completo")
        email = st.text_input("Email")
        role  = st.selectbox("Rol", ["user","programmer","admin"])
        pwd   = st.text_input("Contraseña", type="password")
        st.write("**Accesos a módulos**")
        cols = st.columns(3)
        mods_sel = []
        for i, m in enumerate(enabled_mods):
            with cols[i % 3]:
                if st.checkbox(m["title"], value=True, key=f"cm{m['code']}"):
                    mods_sel.append(m["code"])
        okb = st.form_submit_button("Crear")
    if okb:
        try:
            auth.create_user(email=email, name=name or email, role=role, pwd=pwd or "Cambiar123",
                             active=True, modules=mods_sel)
            ok("Usuario creado.")
            st.rerun()
        except Exception as e:
            err(str(e))

# ---------- Panel de módulos (programmer/admin) ----------
def _render_plugin_preview(code: str):
    mods = {m["code"]: m for m in auth.list_all_modules()}
    meta = mods.get(code)
    if not meta:
        err("Módulo no encontrado."); return
    if code == "Mougli":
        st.info("Vista previa de Mougli no interactiva.")
        st.code("ui_mougli()", language="python"); return
    if code == "Mapito":
        st.info("Vista previa de Mapito no interactiva.")
        st.code("ui_mapito()", language="python"); return
    file_path = meta["file"]; func_name = meta["func"] or "render"
    if not file_path or not Path(file_path).exists():
        err("El archivo del módulo no existe."); return
    try:
        spec = importlib.util.spec_from_file_location(f"plugin_{code}", file_path)
        mod = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(mod)
        fn = getattr(mod, func_name)
        try:
            fn(st, {"user": st.session_state.user})
        except TypeError:
            fn()
    except Exception as e:
        err(f"Error al ejecutar el módulo: {e}")

def panel_modulos():
    st.markdown("### Panel de módulos (Programador)")
    st.caption("Sube un .py con una función pública (por defecto **render**) y se añadirá al menú.")

    with st.form("reg_mod"):
        code = st.text_input("Código (único, sin espacios. Ej: Ventas2025)")
        title = st.text_input("Título visible")
        func = st.text_input("Nombre de la función pública", value="render")
        py = st.file_uploader("Archivo .py del módulo", type=["py"])
        enabled = st.checkbox("Habilitado", value=True)
        okb = st.form_submit_button("Registrar módulo")
    if okb:
        try:
            if not code or not title or not py:
                raise ValueError("Completa código, título y archivo.")
            dest = (MODULES_DIR / f"{code}.py").resolve()
            with open(dest, "wb") as f:
                f.write(py.read())
            auth.register_module(code=code.strip(), title=title.strip(),
                                 file=str(dest), func=func.strip() or "render",
                                 enabled=enabled)
            ok("Módulo registrado.")
            st.rerun()
        except Exception as e:
            err(str(e))

    st.markdown("---")
    st.markdown("#### Módulos instalados")
    mods = auth.list_all_modules()
    for m in mods:
        with st.expander(f"{m['code']} · {m['title']}"):
            c1,c2,c3 = st.columns([2,1,1])
            with c1:
                new_title = st.text_input("Título", value=m["title"], key=f"mt{m['code']}")
                new_func  = st.text_input("Función", value=m["func"] or "render", key=f"mf{m['code']}")
                new_file  = st.text_input("Ruta archivo (.py)", value=m["file"], key=f"mfpath{m['code']}")
            with c2:
                new_enabled = st.checkbox("Habilitado", value=m["enabled"], key=f"me{m['code']}")
                repl = st.file_uploader("Reemplazar .py", type=["py"], key=f"rep{m['code']}")
            with c3:
                if st.button("Previsualizar", key=f"pv{m['code']}"):
                    _render_plugin_preview(m["code"])
            if st.button("Guardar cambios", key=f"mg{m['code']}"):
                try:
                    if repl is not None:
                        dest = (MODULES_DIR / f"{m['code']}.py").resolve()
                        with open(dest, "wb") as f:
                            f.write(repl.read())
                        new_file = str(dest)
                    auth.update_module(m["code"], title=new_title, func=new_func, file=new_file,
                                       enabled=new_enabled)
                    ok("Cambios guardados.")
                    st.rerun()
                except Exception as e:
                    err(str(e))
            if m["code"] not in ("Mougli","Mapito"):
                if st.button("Eliminar módulo", key=f"mdel{m['code']}"):
                    try:
                        auth.delete_module(m["code"])
                        ok("Módulo eliminado.")
                        st.rerun()
                    except Exception as e:
                        err(str(e))
            else:
                st.caption("Módulo interno de la suite.")

# ---------------- UIs internos ----------------
def ui_mougli():
    st.markdown("### Mougli – Monitor & OutView")
    if not procesar_monitor_outview:
        st.info("El núcleo de Mougli no está disponible."); return
    up_monitor = st.file_uploader("Monitor (.txt)", type=["txt"], accept_multiple_files=True)
    up_out     = st.file_uploader("OutView (.csv/.xlsx)", type=["csv","xlsx"], accept_multiple_files=True)
    if st.button("Procesar Mougli", type="primary"):
        try:
            resumen, ruta_excel = procesar_monitor_outview(up_monitor or [], up_out or [])
            ok("¡Listo!")
            if ruta_excel:
                st.download_button("Descargar Excel", data=open(ruta_excel,"rb"),
                                   file_name=os.path.basename(ruta_excel))
            st.json(resumen)
        except Exception as e:
            err(str(e))

def ui_mapito():
    st.markdown("### Mapito – Perú")
    if not build_map:
        st.info("El núcleo de Mapito no está disponible."); return
    color = st.color_picker("Color general", value=PURPLE)
    show_borders = st.checkbox("Mostrar bordes", value=True)
    if st.button("Generar mapa"):
        try:
            html, _sel = build_map(BASE_DIR/"data", "regiones", color, filtros=None, show_borders=show_borders)
            st.components.v1.html(html, height=600, scrolling=True)
        except Exception as e:
            err(str(e))

# ---------------- Router ----------------
def run_module(code: str):
    if code == "Mougli": ui_mougli(); return
    if code == "Mapito": ui_mapito(); return
    mods = {m["code"]: m for m in auth.list_all_modules()}
    meta = mods.get(code)
    if not meta:
        st.warning("Módulo no encontrado."); return
    file_path = meta["file"]; func_name = meta["func"] or "render"
    if not file_path or not Path(file_path).exists():
        st.warning("Archivo del módulo no disponible."); return
    try:
        spec = importlib.util.spec_from_file_location(f"plugin_{code}", file_path)
        mod = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(mod)
        fn = getattr(mod, func_name)
        try:
            fn(st, {"user": st.session_state.user})
        except TypeError:
            fn()
    except Exception as e:
        err(f"Error al ejecutar el módulo: {e}")

# ---------------- MAIN ----------------
def main():
    auth.init_db()
    auth.ensure_builtin_modules()

    # Auto-login por token en URL (?tk=...)
    if not st.session_state.user:
        tk = _get_query_param("tk")
        if tk:
            u = auth.user_from_token(tk)
            if u:
                st.session_state.user = u

    if not auth.admin_exists():
        first_admin_screen(); return

    if not st.session_state.user:
        login_screen(); return

    # App autenticada
    sidebar_userbox()
    user = st.session_state.user

    st.sidebar.markdown("---")
    if user["role"] in ("admin",):
        if st.sidebar.button("Panel de usuarios", use_container_width=True):
            st.session_state.open_admin = True
    if user["role"] in ("admin","programmer"):
        if st.sidebar.button("Panel de módulos (Programador)", use_container_width=True):
            st.session_state.open_prog = True

    if st.session_state.open_admin and user["role"] in ("admin",):
        panel_usuarios(); return
    if st.session_state.open_prog and user["role"] in ("admin","programmer"):
        panel_modulos(); return

    enabled = {m["code"]: m for m in auth.list_all_modules(enabled_only=True)}
    allowed = [code for code in (user["modules"] or []) if code in enabled]
    if not allowed:
        st.warning("No tienes módulos habilitados. Pide a un admin/programador que te asigne acceso.")
        return
    titles = {m["code"]: m["title"] for m in enabled.values()}
    choice = st.sidebar.radio("Elige aplicación", allowed, format_func=lambda c: titles.get(c, c))
    run_module(choice)

if __name__ == "__main__":
    main()

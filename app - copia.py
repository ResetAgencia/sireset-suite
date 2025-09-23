# app.py — Autenticación con roles + remember me + emails
import os, json
import streamlit as st
from streamlit_cookies_manager import EncryptedCookieManager

import auth
import mailer

from core.mougli_core import procesar_monitor_outview
from core.mapito_core import build_map, export_png

auth.init_db()

# ================== Cookies (para "Recordarme") ==================
COOKIES_SECRET = os.getenv("SIRESET_COOKIE_SECRET", "change-me-please")  # cambia esto en producción
cookies = EncryptedCookieManager(prefix="sireset_", password=COOKIES_SECRET)
if not cookies.ready():
    st.stop()

REMEMBER_COOKIE = "auth"   # sireset_auth

# ================== UI base ==================
st.set_page_config(page_title="SiReset", layout="wide")
st.markdown("""
<style>
:root { --sr-primary:#5f48c6; }
.block-container { padding-top: .5rem; }
header[data-testid="stHeader"] { background: transparent; }

.stButton > button[kind="primary"],
.stDownloadButton > button[kind="primary"],
button[kind="primary"]{ background:var(--sr-primary)!important; border-color:var(--sr-primary)!important;}
.stButton > button:hover[kind="primary"], .stDownloadButton > button:hover[kind="primary"]{ filter:brightness(0.95); }
[data-testid="stRadio"] input[type="radio"], [data-testid="stCheckbox"] input[type="checkbox"]{ accent-color:var(--sr-primary); }
[data-testid="stRadio"] label[aria-checked="true"]{ color:var(--sr-primary)!important; font-weight:600; }
.stTabs button[aria-selected="true"]{ border-bottom:3px solid var(--sr-primary)!important; color:var(--sr-primary)!important; font-weight:700; }
[data-testid="stSlider"] [role="slider"]{ background:var(--sr-primary)!important; border:2px solid var(--sr-primary)!important; }
[data-testid="stSlider"] .st-b9{ background:var(--sr-primary)!important; }
[data-testid="stSlider"] input[type="range"]{ accent-color:var(--sr-primary); }

.card{ border:1px solid #e3e6ef;border-radius:10px;background:#fff;box-shadow:0 1px 2px rgba(16,24,40,.04); }
.card .card-head{ background:#f5f6fa;border-bottom:1px solid #e9edf5;padding:10px 14px;font-weight:700;color:#1f2330;border-top-left-radius:10px;border-top-right-radius:10px;}
.card .card-body{ padding:14px;color:#1f2330;}
.card .row{ display:grid;grid-template-columns:220px 1fr;gap:16px;padding:6px 0;border-bottom:1px dashed #eef2f7;}
.card .row:last-child{ border-bottom:0;}
.kpi{ color:var(--sr-primary); font-weight:700;}
.badge{ display:inline-block;padding:2px 8px;border-radius:999px;background:#efeaff;color:#4b34bd;font-weight:600;font-size:.8rem;}
</style>
""", unsafe_allow_html=True)

BANNER = os.path.join("assets", "Encabezado.png")
if os.path.exists(BANNER):
    st.image(BANNER, use_container_width=True)

# ================== Módulos ==================
def render_mougli():
    st.subheader("Mougli – Monitor & OutView")
    st.markdown("Sube **Monitor (.txt)** y/o **OutView (.csv / .xlsx)**, ajusta factores y presiona **Procesar**.")
    st.sidebar.header("Factores (Monitor)")
    factores = {
        "TV":      st.sidebar.number_input("TV",      value=0.255,  key="fact_tv"),
        "CABLE":   st.sidebar.number_input("CABLE",   value=0.425,  key="fact_cable"),
        "RADIO":   st.sidebar.number_input("RADIO",   value=0.425,  key="fact_radio"),
        "REVISTA": st.sidebar.number_input("REVISTA", value=0.14875,key="fact_revista"),
        "DIARIOS": st.sidebar.number_input("DIARIOS", value=0.14875,key="fact_diarios"),
    }
    c1, c2 = st.columns(2)
    with c1:
        monitor_files = st.file_uploader("Sube Monitor (.txt)", type=["txt"], accept_multiple_files=True, key="upl_monitor")
    with c2:
        outview_files = st.file_uploader("Sube OutView (.csv / .xlsx)", type=["csv","xlsx"], accept_multiple_files=True, key="upl_outview")

    if st.button("Procesar Mougli", type="primary", key="btn_proc_mougli"):
        if not monitor_files and not outview_files:
            st.warning("Sube al menos un archivo Monitor o OutView.")
        else:
            with st.spinner("Procesando…"):
                xls_bytes, det = procesar_monitor_outview(monitor_files, outview_files, factores)
            st.success("¡Listo! ✅")
            st.download_button("Descargar Excel", data=xls_bytes, file_name="Mougli_resultado.xlsx",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                               key="dl_mougli_xlsx")
            st.markdown("### Resumen")
            c1, c2 = st.columns(2)
            dm, do = det.get("monitor",{}), det.get("outview",{})
            def tarjeta(titulo, d):
                st.markdown(f"""
                <div class="card"><div class="card-head">{titulo}</div>
                <div class="card-body">
                  <div class="row"><div>Filas</div><div class="kpi">{d.get('rows',0):,}</div></div>
                  <div class="row"><div>Rango de fechas</div><div>{d.get('date_min','—')} - {d.get('date_max','—')}</div></div>
                  <div class="row"><div>Marcas / Anunciantes</div><div class="kpi">{d.get('brands',0)}</div></div>
                </div></div>""", unsafe_allow_html=True)
            with c1: tarjeta("Monitor", dm)
            with c2: tarjeta("OutView", do)

def render_mapito():
    st.subheader("Mapito – Perú")
    DATA_DIR = "data"
    st.sidebar.header("Estilos del mapa")
    general_fill  = st.sidebar.color_picker("Color general",     "#dddddd", key="mp_general")
    selected_fill = st.sidebar.color_picker("Color seleccionado","#5f48c6", key="mp_selected")
    border_color  = st.sidebar.color_picker("Color de borde",    "#000000", key="mp_border")
    border_width  = st.sidebar.slider("Grosor de borde", 0.1, 6.0, 0.8, 0.1, key="mp_border_w")
    show_borders  = st.sidebar.checkbox("Mostrar bordes", True, key="mp_border_on")
    show_tiles    = st.sidebar.checkbox("Mostrar mapa base (OSM) en vista interactiva", False, key="mp_tiles")
    bg_transparent= st.sidebar.checkbox("PNG sin fondo (transparente)", False, key="mp_png_transp")
    bg_color      = st.sidebar.color_picker("Color de fondo del PNG", "#ffffff", key="mp_png_bg", disabled=bg_transparent)
    style = {"general_fill":general_fill,"selected_fill":selected_fill,"border_color":border_color,
             "border_width":border_width,"show_borders":show_borders,"show_tiles":show_tiles,
             "background_color":bg_color,"transparent_png":bg_transparent}

    tabs = st.tabs(["Regiones","Provincias","Distritos","Lima/Callao"])

    with tabs[0]:
        gj1 = json.load(open(os.path.join(DATA_DIR, "gadm41_PER_1.json"), encoding="utf-8"))
        regiones = sorted({ft["properties"].get("NAME_1","") for ft in gj1["features"]})
        sel_regs = st.multiselect("Elige una o más regiones (opcional)", regiones, key="regiones_multi")
        filtros = {"regiones": set(sel_regs)}
        html, _ = build_map(DATA_DIR, "regiones", style, filtros=filtros)
        st.components.v1.html(html, height=600, scrolling=False)
        cA,cB = st.columns(2)
        with cA:
            st.download_button("⬇ PNG (SIN fondo)",
                               data=export_png(DATA_DIR,"regiones",style|{"transparent_png":True},filtros=filtros),
                               file_name="regiones_transparente.png", mime="image/png", key="png_reg_t")
        with cB:
            st.download_button("⬇ PNG (CON fondo)",
                               data=export_png(DATA_DIR,"regiones",style|{"transparent_png":False},filtros=filtros),
                               file_name="regiones_fondo.png", mime="image/png", key="png_reg_s")

    with tabs[1]:
        gj2 = json.load(open(os.path.join(DATA_DIR, "gadm41_PER_2.json"), encoding="utf-8"))
        regs2 = sorted({ft["properties"].get("NAME_1","") for ft in gj2["features"]})
        r = st.selectbox("Región (para base)", ["(Todas)"]+regs2, key="prov_region")
        provs = sorted({ft["properties"].get("NAME_2","") for ft in gj2["features"]
                        if r=="(Todas)" or ft["properties"].get("NAME_1","")==r})
        p = st.selectbox("Provincia a resaltar (opcional)", ["(Todas)"]+provs, key="prov_provincia")
        filtros = {"regiones": set() if r=="(Todas)" else {r}, "provincia": None if p=="(Todas)" else p}
        html, _ = build_map(DATA_DIR, "provincias", style, filtros=filtros)
        st.components.v1.html(html, height=600, scrolling=False)
        cA,cB = st.columns(2)
        with cA:
            st.download_button("⬇ PNG (SIN fondo)",
                               data=export_png(DATA_DIR,"provincias",style|{"transparent_png":True},filtros=filtros),
                               file_name="provincias_transparente.png", mime="image/png", key="png_prov_t")
        with cB:
            st.download_button("⬇ PNG (CON fondo)",
                               data=export_png(DATA_DIR,"provincias",style|{"transparent_png":False},filtros=filtros),
                               file_name="provincias_fondo.png", mime="image/png", key="png_prov_s")

    with tabs[2]:
        gj3 = json.load(open(os.path.join(DATA_DIR, "gadm41_PER_3.json"), encoding="utf-8"))
        regs3 = sorted({ft["properties"].get("NAME_1","") for ft in gj3["features"]})
        r3 = st.selectbox("Región", ["(Todas)"]+regs3, key="dist_region")
        provs3 = sorted({ft["properties"].get("NAME_2","") for ft in gj3["features"]
                         if r3=="(Todas)" or ft["properties"].get("NAME_1","")==r3})
        p3 = st.selectbox("Provincia", ["(Todas)"]+provs3, key="dist_provincia")
        dists = sorted({ft["properties"].get("NAME_3","") for ft in gj3["features"]
                        if (r3=="(Todas)" or ft["properties"].get("NAME_1","")==r3)
                        and (p3=="(Todas)" or ft["properties"].get("NAME_2","")==p3)})
        sel_d = st.multiselect("Distritos a resaltar (multi)", dists, key="dist_multi")
        filtros = {"regiones": set() if r3=="(Todas)" else {r3}, "provincia": None if p3=="(Todas)" else p3,
                   "distritos": set(sel_d) if sel_d else set()}
        html, _ = build_map(DATA_DIR, "distritos", style, filtros=filtros)
        st.components.v1.html(html, height=600, scrolling=False)
        cA,cB = st.columns(2)
        with cA:
            st.download_button("⬇ PNG (SIN fondo)",
                               data=export_png(DATA_DIR,"distritos",style|{"transparent_png":True},filtros=filtros),
                               file_name="distritos_transparente.png", mime="image/png", key="png_dist_t")
        with cB:
            st.download_button("⬇ PNG (CON fondo)",
                               data=export_png(DATA_DIR,"distritos",style|{"transparent_png":False},filtros=filtros),
                               file_name="distritos_fondo.png", mime="image/png", key="png_dist_s")

    with tabs[3]:
        LIMA_GROUPS = {
            "LimaNorte": ["Ancon","SantaRosa","Carabayllo","PuentePiedra","Comas","Independencia","LosOlivos","SanMartindePorres"],
            "LimaEste": ["SanJuandeLurigancho","Lurigancho","Chaclacayo","Ate","SantaAnita","ElAgustino","LaMolina","Cieneguilla"],
            "LimaCentro": ["Lima","Breña","Rimac","LaVictoria","JesusMaria","Lince","PuebloLibre","SanIsidro","Miraflores","Surquillo","Barranco","SantiagodeSurco","SanBorja","MagdalenadelMar"],
            "LimaSur": ["Chorrillos","SanJuandeMiraflores","VillaMariadelTriunfo","VillaElSalvador","Pachacamac","Lurin","PuntaHermosa","PuntaNegra","SanBartolo","SantaMariadelMar","Pucusana"],
            "Callao": ["Callao","LaPunta","LaPerla","Bellavista","CarmendelaLegua","MiPeru","Ventanilla"]
        }
        grupos = st.multiselect("Grupos a resaltar", list(LIMA_GROUPS.keys()), key="lc_grupos")
        filtros = {"grupos": grupos}
        html, _ = build_map("data", "lima_callao", style, filtros=filtros, lima_groups=LIMA_GROUPS)
        st.components.v1.html(html, height=600, scrolling=False)
        cA,cB = st.columns(2)
        with cA:
            st.download_button("⬇ PNG (SIN fondo)",
                               data=export_png("data","lima_callao",style|{"transparent_png":True},filtros=filtros,lima_groups=LIMA_GROUPS),
                               file_name="lima_callao_transparente.png", mime="image/png", key="png_lc_t")
        with cB:
            st.download_button("⬇ PNG (CON fondo)",
                               data=export_png("data","lima_callao",style|{"transparent_png":False},filtros=filtros,lima_groups=LIMA_GROUPS),
                               file_name="lima_callao_fondo.png", mime="image/png", key="png_lc_s")

MODULES = {
    "mougli": {"title":"Mougli", "render": render_mougli},
    "mapito": {"title":"Mapito", "render": render_mapito},
}

# ================== Helpers sesión ==================
def _current_user():
    return st.session_state.get("user")

def _do_login(u, remember=False):
    st.session_state["user"] = u
    if remember:
        token = auth.create_remember_token(u["id"], days=30)
        cookies.set(REMEMBER_COOKIE, token, max_age=60*60*24*30, secure=False, httponly=True, samesite="Lax")
        cookies.save()

def _logout():
    # opcional: revocar token de cookie actual
    tok = cookies.get(REMEMBER_COOKIE)
    if tok:
        auth.revoke_remember_token(tok)
        cookies.delete(REMEMBER_COOKIE)
        cookies.save()
    st.session_state.pop("user", None)

def _login_screen():
    st.subheader("Iniciar sesión")
    with st.form("login"):
        email = st.text_input("Email")
        pwd = st.text_input("Contraseña", type="password")
        remember = st.checkbox("Recordarme en este equipo", value=True)
        ok = st.form_submit_button("Entrar", type="primary")
    if ok:
        u = auth.authenticate(email, pwd)
        if u:
            _do_login(u, remember=remember)
            st.rerun()
        else:
            st.error("Credenciales inválidas o usuario inactivo.")

def _first_admin_screen():
    st.subheader("Configurar administrador")
    st.info("No hay usuarios aún. Crea el **primer administrador**.")
    with st.form("first_admin"):
        name = st.text_input("Nombre")
        email = st.text_input("Email")
        pwd = st.text_input("Contraseña", type="password")
        ok = st.form_submit_button("Crear admin", type="primary")
    if ok:
        uid = auth.create_user(email, name, "admin", pwd, active=True)
        auth.ensure_module_access_for_admin(uid, MODULES.keys())
        st.success("Administrador creado. Inicia sesión.")
        st.rerun()

def _admin_panel(user):
    st.markdown(f"<h3>Panel de administración  ·  <span class='badge'>admin</span></h3>", unsafe_allow_html=True)

    users = auth.list_users()
    cols = st.columns([2,2,1,1,2])
    cols[0].markdown("**Email**")
    cols[1].markdown("**Nombre**")
    cols[2].markdown("**Rol**")
    cols[3].markdown("**Activo**")
    cols[4].markdown("**Acciones**")
    for u in users:
        c0,c1,c2,c3,c4 = st.columns([2,2,1,1,2])
        c0.write(u["email"]); c1.write(u["name"])
        new_role = c2.selectbox(f"rol_{u['id']}", ["admin","programmer","user"], index=["admin","programmer","user"].index(u["role"]))
        new_active = c3.checkbox(f"act_{u['id']}", value=u["active"])
        if c4.button("Guardar", key=f"save_{u['id']}"):
            auth.set_user_role(u["id"], new_role)
            auth.set_user_active(u["id"], new_active)
            if new_role=="admin":
                auth.ensure_module_access_for_admin(u["id"], MODULES.keys())
            st.success("Actualizado")

        if u["role"] != "admin":
            st.caption(f"Módulos visibles para **{u['email']}**")
            allowed = set(auth.modules_for_user(u["id"]))
            new_allowed = set()
            for k,v in MODULES.items():
                if st.checkbox(f"{v['title']} ({k})", key=f"m_{u['id']}_{k}", value=(k in allowed)):
                    new_allowed.add(k)
            if st.button("Guardar módulos", key=f"mods_{u['id']}"):
                auth.set_modules_for_user(u["id"], new_allowed)
                st.success("Accesos actualizados")

        cA,cB,cC,cD = st.columns(4)
        if cA.button("Magic link", key=f"ml_{u['id']}"):
            link = auth.generate_magic_link(u["id"])
            st.code(link, language="text")
        if cB.button("Reset pass→'cambiar123'", key=f"rp_{u['id']}"):
            auth.set_user_password(u["id"], "cambiar123")
            st.success("Contraseña: cambiar123")
        if u["id"]!=user["id"]:
            if cD.button("Eliminar usuario", key=f"del_{u['id']}"):
                auth.delete_user(u["id"])
                st.warning("Usuario eliminado")
                st.rerun()
        st.markdown("---")

    # ---------- CREAR USUARIO (con módulos + email) ----------
    st.markdown("### Crear usuario")
    with st.form("crear_user"):
        name = st.text_input("Nombre completo")
        email = st.text_input("Email nuevo")
        role = st.selectbox("Rol", ["user","programmer","admin"], index=0)
        pwd = st.text_input("Contraseña", type="password")

        st.markdown("**Accesos a módulos**")
        selected_modules = set()
        if role != "admin":
            cols = st.columns(3); i=0
            for key, meta in MODULES.items():
                with cols[i%3]:
                    if st.checkbox(f"{meta['title']} ({key})", key=f"new_{key}", value=True):
                        selected_modules.add(key)
                i+=1
        else:
            st.info("Rol **admin** tendrá acceso a todos los módulos automáticamente.")

        ok = st.form_submit_button("Crear", type="primary")

    if ok:
        uid = auth.create_user(email, name, role, pwd, active=True)
        if role == "admin":
            auth.ensure_module_access_for_admin(uid, MODULES.keys())
            mods_for_mail = list(MODULES.keys())
        else:
            auth.set_modules_for_user(uid, selected_modules)
            mods_for_mail = sorted(selected_modules)

        # Prepara magic link (para el correo)
        base = st.request.url if hasattr(st, "request") else "http://localhost:8501/"
        magic_link = auth.generate_magic_link(uid, base_url=base)

        # Envía email (si SMTP configurado)
        sent = mailer.send_new_user_email(email, name, role, mods_for_mail, pwd, magic_link)
        msg = " (correo enviado)" if sent else " (SMTP no configurado)"
        st.success(f"Usuario creado.{msg}")

def _programmer_panel():
    st.markdown(f"<h3>Panel de programador  ·  <span class='badge'>programmer</span></h3>", unsafe_allow_html=True)
    st.markdown("""
- Agrega módulos creando un archivo `.py` dentro de `modules/` que exponga `register()` → {"key","title","render"}.
- Luego presiona **Recargar módulos** para detectarlos (los embebidos ya están activos).
""")
    if st.button("Recargar módulos", type="primary"):
        st.success("Recarga realizada.")

def _render_modules_home(user):
    role = user["role"]
    if role == "admin":
        allowed = list(MODULES.keys())
    else:
        allowed = list(auth.modules_for_user(user["id"]))
    if not allowed:
        st.info("No tienes módulos asignados. Contacta a un administrador.")
        return
    options = [f"{MODULES[k]['title']} ({k})" for k in allowed]
    pick = st.selectbox("Elige módulo", options)
    key = pick.split("(")[-1].strip(")")
    MODULES[key]["render"]()

# ================== Magic link ==================
qs = st.query_params
if "token" in qs and "user" not in st.session_state:
    u = auth.consume_token(qs["token"])
    if u:
        _do_login(u, remember=True)  # opcionalmente recordar si llega por magic link
        st.query_params.clear()
        st.rerun()

# ================== Auto-login desde cookie ==================
if "user" not in st.session_state:
    tok = cookies.get(REMEMBER_COOKIE)
    if tok:
        u = auth.user_from_remember_token(tok)
        if u:
            st.session_state["user"] = u

# ================== Flujo ==================
user = _current_user()

if not auth.admin_exists():
    _first_admin_screen()
elif not user:
    _login_screen()
else:
    with st.sidebar:
        st.markdown(f"**Usuario:** {user['name']}  \n**Rol:** `{user['role']}`")
        if st.button("Cerrar sesión"):
            _logout()
            st.rerun()

    if user["role"] == "admin":
        _admin_panel(user)
        st.markdown("---")
        _render_modules_home(user)
    elif user["role"] == "programmer":
        _programmer_panel()
        st.markdown("---")
        _render_modules_home(user)
    else:
        _render_modules_home(user)

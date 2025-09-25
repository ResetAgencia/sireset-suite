# app.py — SiReset (Streamlit) con worker a prueba de fallos
from __future__ import annotations

import os
import sys
import json
import uuid
import shutil
from pathlib import Path
from io import BytesIO
from typing import Optional, List, Dict

import pandas as pd
import streamlit as st
from subprocess import Popen

# ─────────────────────────── Config general ───────────────────────────
st.set_page_config(page_title="SiReset", layout="wide")
try:
    st.image("assets/Encabezado.png", width="stretch")
except Exception:
    pass

APP_ROOT = Path(__file__).parent.resolve()
for p in (APP_ROOT, APP_ROOT / "core"):
    sp = str(p)
    if sp not in sys.path:
        sys.path.insert(0, sp)

# Asegura que core sea paquete (para import -m)
CORE_DIR = APP_ROOT / "core"
try:
    if CORE_DIR.exists():
        init_py = CORE_DIR / "__init__.py"
        if not init_py.exists():
            init_py.write_text("# auto-created to mark 'core' as a package\n", encoding="utf-8")
except Exception:
    pass

# ───────────────────── Imports de auth y core robustos ───────────────────────
def _import_mougli_core():
    # 1) core.mougli_core
    try:
        import core.mougli_core as mc
        return mc, "pkg"
    except Exception as e1:
        err1 = f"core.mougli_core: {e1}"
    # 2) mougli_core (si core/ está en sys.path)
    try:
        import mougli_core as mc
        return mc, "flat"
    except Exception as e2:
        err2 = f"mougli_core: {e2}"
    # 3) Carga por ruta
    try:
        from importlib.machinery import SourceFileLoader
        mod_path = CORE_DIR / "mougli_core.py"
        if not mod_path.exists():
            mod_path = APP_ROOT / "mougli_core.py"
        mc = SourceFileLoader("mougli_core", str(mod_path)).load_module()
        return mc, "path"
    except Exception as e3:
        st.error(
            "No pude importar *mougli_core* por ninguna ruta.\n\n"
            f"- {err1}\n- {err2}\n- loader: {e3}\n\n"
            f"Busqué en: {CORE_DIR}/mougli_core.py y {APP_ROOT}/mougli_core.py"
        )
        st.stop()

mc, _mc_mode = _import_mougli_core()

try:
    from auth import (
        login_ui, current_user, logout_button,
        list_users, create_user, update_user, set_password, list_all_modules,
        _connect as _db_connect
    )
    def _db_path():
        try:
            con = _db_connect()
            row = con.execute("PRAGMA database_list;").fetchone()
            try:
                con.close()
            except Exception:
                pass
            return row["file"] if row else "(desconocida)"
        except Exception:
            return "(ruta no disponible)"
except Exception as e:
    st.error(f"No pude importar el módulo de autenticación (auth.py): {e}")
    st.stop()

# Resolver funciones/exportaciones del core
def require_any(preferido: str, *alternativos: str):
    candidatos = (preferido, *alternativos)
    for name in candidatos:
        fn = getattr(mc, name, None)
        if callable(fn):
            return fn
    exports = sorted([x for x in dir(mc) if not x.startswith("_")])
    st.error(
        f"No encontré la función *{preferido}* en mougli_core.\n"
        f"Funciones visibles: {', '.join(exports) or '—'}"
    )
    st.stop()

procesar_monitor_outview = require_any("procesar_monitor_outview")
resumen_mougli = require_any("resumen_mougli")
_read_monitor_txt = require_any("_read_monitor_txt")
_read_out_robusto = require_any("_read_out_robusto")
load_monitor_factors = require_any("load_monitor_factors")
save_monitor_factors = require_any("save_monitor_factors")
load_outview_factor = require_any("load_outview_factor")
save_outview_factor = require_any("save_outview_factor")

# ───────────────────────── Helpers y constantes ──────────────────────────────
JOBS_DIR = APP_ROOT / "jobs"
JOBS_DIR.mkdir(exist_ok=True)

BAD_TIPOS = {
    "INSERT", "INTERNACIONAL", "OBITUARIO", "POLITICO",
    "AUTOAVISO", "PROMOCION CON AUSPICIO", "PROMOCION SIN AUSPICIO"
}

HIDE_OUT_PREVIEW = {
    "Código único","Denominador","Código +1 pieza","Tarifa × Superficie",
    "Semana en Mes por Código","NB_EXTRAE_6_7","Fecha_AB","Proveedor_AC",
    "TipoElemento_AD","Distrito_AE","Avenida_AF","NroCalleCuadra_AG","OrientacionVia_AH",
    "Marca_AI","Conteo_AB_AI","Conteo_Z_AB_AI","TarifaS_div3","TarifaS_div3_sobre_Conteo",
    "Suma_AM_Z_AB_AI","TopeTipo_AQ","Suma_AM_Topada_Tipo","SumaTopada_div_ConteoZ",
    "K_UNICO","K_PIEZA"
}

def _unique_list_str(series, max_items=50):
    if series is None:
        return "—"
    vals = (
        series.astype(str)
        .str.strip()
        .replace({"nan": ""})
        .dropna()
        .loc[lambda s: s.str.len() > 0]
        .unique()
        .tolist()
    )
    if not vals:
        return "—"
    vals = sorted(set(vals))
    if len(vals) > max_items:
        return ", ".join(vals[:max_items]) + f" … (+{len(vals)-max_items} más)"
    return ", ".join(vals)

def _web_resumen_enriquecido(df: Optional[pd.DataFrame], *, es_monitor: bool) -> pd.DataFrame:
    base = resumen_mougli(df, es_monitor=es_monitor) if df is not None else None
    if base is None or base.empty:
        base = pd.DataFrame([{"Filas": 0, "Rango de fechas": "—", "Marcas / Anunciantes": 0}])
    base_vertical = pd.DataFrame({"Descripción": base.columns, "Valor": base.iloc[0].tolist()})

    cat_col = "CATEGORIA" if es_monitor else ("Categoría" if (df is not None and "Categoría" in df.columns) else None)
    reg_col = "REGION/ÁMBITO" if es_monitor else ("Región" if (df is not None and "Región" in df.columns) else None)
    tipo_cols = ["TIPO ELEMENTO", "TIPO", "Tipo Elemento"]
    tipo_col = next((c for c in tipo_cols if (df is not None and c in df.columns)), None)

    extras_rows = []
    if df is not None and not df.empty:
        if cat_col:
            extras_rows.append({"Descripción": "Categorías (únicas)", "Valor": _unique_list_str(df[cat_col])})
        if reg_col:
            extras_rows.append({"Descripción": "Regiones (únicas)", "Valor": _unique_list_str(df[reg_col])})
        if tipo_col:
            extras_rows.append({"Descripción": "Tipos de elemento (únicos)", "Valor": _unique_list_str(df[tipo_col])})

    if extras_rows:
        base_vertical = pd.concat([base_vertical, pd.DataFrame(extras_rows)], ignore_index=True)

    return base_vertical

def _preview_df(df: Optional[pd.DataFrame]) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    normalized_hide = {c.strip().lower() for c in HIDE_OUT_PREVIEW}
    cols_to_drop = [c for c in df.columns if c and c.strip().lower() in normalized_hide]
    return df.drop(columns=cols_to_drop, errors="ignore").copy()

# ──────────────────────────── Worker management ───────────────────────────────
def _save_upload_to(job_dir: Path, files, subdir: str) -> List[Path]:
    outdir = job_dir / "uploads" / subdir
    outdir.mkdir(parents=True, exist_ok=True)
    paths = []
    for f in files or []:
        name = getattr(f, "name", f"file-{uuid.uuid4().hex}")
        dest = outdir / name
        with dest.open("wb") as w:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                if not chunk:
                    break
                w.write(chunk)
        try:
            f.seek(0)
        except Exception:
            pass
        paths.append(dest)
    return paths

def _start_worker(job_dir: Path, mon_paths: List[Path], out_paths: List[Path],
                  factores: Dict[str, float], out_factor: float):
    progress = job_dir / "progress.json"
    logf = job_dir / "job.log"
    outxlsx = job_dir / "SiReset_Mougli.xlsx"

    # ¿Podemos usar -m core.mougli_core? (solo si core/ es paquete)
    core_pkg_ok = (CORE_DIR / "__init__.py").exists() and (CORE_DIR / "mougli_core.py").exists()
    if core_pkg_ok:
        base_cmd = [sys.executable, "-m", "core.mougli_core"]
    else:
        script_path = CORE_DIR / "mougli_core.py"
        if not script_path.exists():
            script_path = APP_ROOT / "mougli_core.py"
        base_cmd = [sys.executable, str(script_path)]

    args = base_cmd + [
        "--as-worker",
        "--out-xlsx", str(outxlsx),
        "--progress", str(progress),
        "--log", str(logf),
        "--job-dir", str(job_dir),
        "--factores-json", json.dumps(factores),
        "--outview-factor", str(out_factor),
    ]
    for p in mon_paths:
        args.extend(["--monitor", str(p)])
    for p in out_paths:
        args.extend(["--outview", str(p)])

    Popen(args, cwd=str(APP_ROOT))

    progress.write_text(json.dumps({"status": "running", "step": 0, "total": 6, "message": "Inicializando…"}), encoding="utf-8")

def _read_progress(job_dir: Path) -> Dict:
    pj = job_dir / "progress.json"
    if pj.exists():
        try:
            return json.loads(pj.read_text(encoding="utf-8"))
        except Exception:
            return {"status": "unknown", "message": "progress.json corrupto"}
    return {"status": "unknown", "message": "sin progreso"}

def _read_log_tail(job_dir: Path, lines: int = 200) -> str:
    logf = job_dir / "job.log"
    if not logf.exists():
        return ""
    try:
        data = logf.read_text(encoding="utf-8", errors="ignore").splitlines()
        return "\n".join(data[-lines:])
    except Exception:
        return ""

def _clear_job(job_id: str):
    job_dir = JOBS_DIR / job_id
    if job_dir.exists():
        shutil.rmtree(job_dir, ignore_errors=True)
    if "job_id" in st.session_state:
        del st.session_state["job_id"]

# ─────────────────────────────── LOGIN obligatorio ───────────────────────────
user = current_user()
if not user:
    login_ui()
    st.stop()

# Sidebar: saludo + logout
with st.sidebar:
    st.markdown(f"**Usuario:** {user.get('name') or user.get('email', '—')}")
    st.markdown(f"**Rol:** {user.get('role', '—')}")
    logout_button()

# ------------------- Apps permitidas por usuario -------------------
mods = [str(m).lower() for m in (user.get("modules") or [])]
allowed: List[str] = []
if "mougli" in mods:
    allowed.append("Mougli")
if "mapito" in mods:
    allowed.append("Mapito")
is_admin = (user.get("role") == "admin")
if is_admin:
    allowed.append("Admin")

if not allowed:
    st.warning("Tu usuario no tiene módulos habilitados. Pide acceso a un administrador.")
    st.stop()

# ---------- Sidebar: selector de app ----------
app = st.sidebar.radio("Elige aplicación", allowed, index=0)

# ---------- Factores SOLO visibles en Mougli ----------
if app == "Mougli":
    st.sidebar.markdown("### Factores")
    persist_m = load_monitor_factors()
    persist_o = load_outview_factor()
    col1, col2 = st.sidebar.columns(2)
    with col1:
        f_tv = st.number_input("TV", min_value=0.0, step=0.01, value=float(persist_m.get("TV", 0.255)))
        f_cable = st.number_input("CABLE", min_value=0.0, step=0.01, value=float(persist_m.get("CABLE", 0.425)))
        f_radio = st.number_input("RADIO", min_value=0.0, step=0.01, value=float(persist_m.get("RADIO", 0.425)))
    with col2:
        f_revista = st.number_input("REVISTA", min_value=0.0, step=0.01, value=float(persist_m.get("REVISTA", 0.14875)))
        f_diarios = st.number_input("DIARIOS", min_value=0.0, step=0.01, value=float(persist_m.get("DIARIOS", 0.14875)))
        out_factor = st.number_input("OutView ×Superficie", min_value=0.0, step=0.05, value=float(persist_o))
    factores = {"TV": f_tv, "CABLE": f_cable, "RADIO": f_radio, "REVISTA": f_revista, "DIARIOS": f_diarios}
    if st.sidebar.button("💾 Guardar factores"):
        save_monitor_factors(factores)
        save_outview_factor(out_factor)
        st.sidebar.success("Factores guardados.")

# =============== M O U G L I (con worker) ===============
if app == "Mougli":
    import gc

    st.markdown("## Mougli – Monitor & OutView (seguro)")

    # ---------- Estado de worker en curso ----------
    job_id = st.session_state.get("job_id")
    if job_id:
        job_dir = JOBS_DIR / job_id
        prog = _read_progress(job_dir)
        st.info(f"Trabajo en curso: `{job_id}`")
        colP, colBtns = st.columns([3,1])
        with colP:
            step = int(prog.get("step", 0))
            total = int(prog.get("total", 6) or 6)
            st.progress(min(step, total) / max(total, 1), text=prog.get("message", "Procesando…"))
        with colBtns:
            if st.button("↻ Actualizar"):
                st.rerun()
            if st.button("Cancelar / Limpiar"):
                _clear_job(job_id)
                st.rerun()

        with st.expander("Ver registro (log)"):
            st.code(_read_log_tail(job_dir), language="text")

        if prog.get("status") == "done":
            outxlsx = job_dir / "SiReset_Mougli.xlsx"
            if outxlsx.exists():
                st.success("¡Listo! ✅ Descarga tu Excel.")
                st.download_button(
                    "Descargar Excel",
                    data=outxlsx.read_bytes(),
                    file_name="SiReset_Mougli.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            else:
                st.warning("El proceso terminó pero no encontré el archivo de salida.")
        elif prog.get("status") == "error":
            st.error(f"El worker reportó un error: {prog.get('message')}")
        st.stop()

    # ---------- Staging: subir → volcar a disco inmediatamente ----------
    MAX_PREVIEW_BYTES = 15 * 1024 * 1024  # 15 MB

    def _ensure_pending_job():
        jid = st.session_state.get("pending_job_id")
        if not jid:
            jid = uuid.uuid4().hex[:12]
            st.session_state["pending_job_id"] = jid
        job_dir = JOBS_DIR / jid
        job_dir.mkdir(parents=True, exist_ok=True)
        return jid, job_dir

    def _stage_files(kind: str, files):
        if not files:
            return []
        jid, job_dir = _ensure_pending_job()
        paths = _save_upload_to(job_dir, files, kind)
        # Limpia los bytes del uploader para liberar RAM
        key = "m_txt_multi" if kind == "monitor" else "o_multi"
        try:
            st.session_state[key] = None
        except Exception:
            pass
        del files
        gc.collect()
        return paths

    def _on_upload_monitor():
        files = st.session_state.get("m_txt_multi") or []
        _stage_files("monitor", files)

    def _on_upload_out():
        files = st.session_state.get("o_multi") or []
        _stage_files("outview", files)

    # ---------- Carga con callbacks (stream to disk) ----------
    colL, colR = st.columns(2)
    with colL:
        st.caption("Sube Monitor (.txt) — puedes subir varios (se guardan inmediatamente)")
        st.file_uploader(
            "Arrastra y suelta aquí",
            type=["txt"],
            key="m_txt_multi",
            label_visibility="collapsed",
            accept_multiple_files=True,
            on_change=_on_upload_monitor,
        )
    with colR:
        st.caption("Sube OutView (.csv / .xlsx) — puedes subir varios (se guardan inmediatamente)")
        st.file_uploader(
            "Arrastra y suelta aquí",
            type=["csv", "xlsx"],
            key="o_multi",
            label_visibility="collapsed",
            accept_multiple_files=True,
            on_change=_on_upload_out,
        )

    # ---------- Mostrar bandeja de archivos ya volcados a disco ----------
    jid = st.session_state.get("pending_job_id")
    mon_paths = []
    out_paths = []
    if jid:
        job_dir = JOBS_DIR / jid
        mon_paths = sorted((job_dir / "uploads" / "monitor").glob("*"))
        out_paths = sorted((job_dir / "uploads" / "outview").glob("*"))

    def _fmt_size(p: Path) -> str:
        try:
            b = p.stat().st_size
        except Exception:
            b = 0
        mb = b / (1024*1024)
        return f"{mb:.1f} MB"

    st.markdown("#### Archivos preparados")
    colA, colB = st.columns(2)
    with colA:
        st.write("**Monitor**")
        if mon_paths:
            for p in mon_paths:
                st.write(f"• {p.name} — {_fmt_size(p)}")
        else:
            st.caption("— vacío —")
    with colB:
        st.write("**OutView**")
        if out_paths:
            for p in out_paths:
                st.write(f"• {p.name} — {_fmt_size(p)}")
        else:
            st.caption("— vacío —")

    colBtns1, colBtns2 = st.columns(2)
    with colBtns1:
        if st.button("🗑️ Vaciar bandeja"):
            if jid:
                _clear_job(jid)
                st.session_state.pop("pending_job_id", None)
                gc.collect()
                st.rerun()
    with colBtns2:
        if st.button("🚀 Procesar (seguro, en background)", type="primary"):
            if not (mon_paths or out_paths):
                st.warning("Primero sube algún archivo; se guardan al seleccionarlos.")
            else:
                try:
                    _start_worker(JOBS_DIR / jid, mon_paths, out_paths, factores, out_factor)
                    st.session_state["job_id"] = jid
                    st.session_state.pop("pending_job_id", None)
                    gc.collect()
                    st.success("Trabajo lanzado. Puedes seguir usando la app.")
                    st.rerun()
                except Exception as e:
                    _clear_job(jid)
                    st.error(f"No se pudo iniciar el procesamiento: {e}")

    # ---------- Vistazo rápido (protegido) ----------
    st.markdown("---")
    st.markdown("### ¿Solo quieres un vistazo rápido sin procesar todo?")
    st.caption("Esto carga y muestra **solo resúmenes** para validar archivos (no genera Excel).")

    colPrevA, colPrevB = st.columns(2)
    with colPrevA:
        if mon_paths:
            total_mb = sum((p.stat().st_size for p in mon_paths if p.exists()), 0) / (1024*1024)
            if total_mb > 15:
                st.info("Monitor en bandeja es pesado: se omite preview para evitar cuelgues.")
            else:
                try:
                    buf = BytesIO()
                    for i, p in enumerate(mon_paths):
                        with p.open("rb") as f:
                            if i > 0:
                                buf.write(b"\n")
                            buf.write(f.read())
                    buf.seek(0); setattr(buf, "name", "monitor_preview.txt")
                    df_m = _read_monitor_txt(buf)
                    st.dataframe(_web_resumen_enriquecido(df_m, es_monitor=True), width="stretch")
                except MemoryError:
                    st.warning("Preview de Monitor omitido por tamaño (protección de memoria).")
                except Exception as e:
                    st.error(f"No se pudo leer Monitor: {e}")

    with colPrevB:
        if out_paths:
            try:
                f0 = out_paths[0]
                if f0.stat().st_size > MAX_PREVIEW_BYTES:
                    st.info("OutView en bandeja es pesado: se omite preview para evitar cuelgues.")
                else:
                    with f0.open("rb") as fh:
                        setattr(fh, "name", f0.name)
                        df_o = _read_out_robusto(fh)
                    st.dataframe(_web_resumen_enriquecido(df_o, es_monitor=False), width="stretch")
            except MemoryError:
                st.warning("Preview de OutView omitido por tamaño (protección de memoria).")
            except Exception as e:
                st.error(f"No se pudo leer OutView: {e}")

# =============== M A P I T O ===============
elif app == "Mapito":
    st.markdown("## Mapito – Perú")
    try:
        from core.mapito_core import build_map
    except Exception:
        build_map = None

    if build_map is None:
        st.info("Mapito no está disponible en este entorno.")
    else:
        st.sidebar.markdown("### Estilos del mapa")
        color_general = st.sidebar.color_picker("Color general", "#713030")
        color_sel = st.sidebar.color_picker("Color seleccionado", "#5F48C6")
        color_borde = st.sidebar.color_picker("Color de borde", "#000000")
        grosor = st.sidebar.slider("Grosor de borde", 0.1, 2.0, 0.8, 0.05)
        show_borders = st.sidebar.checkbox("Mostrar bordes", value=True)
        show_basemap = st.sidebar.checkbox("Mostrar mapa base (OSM) en vista interactiva", value=True)

        DATA_DIR = Path("data")
        try:
            html, seleccion = build_map(
                data_dir=DATA_DIR,
                nivel="regiones",
                colores={"fill": color_general, "selected": color_sel, "border": color_borde},
                style={"weight": grosor, "show_borders": show_borders, "show_basemap": show_basemap},
            )
            st.components.v1.html(html, height=700, scrolling=False)
            if seleccion:
                st.caption(f"Elementos mostrados: {len(seleccion)}")
        except Exception as e:
            st.error(f"No se pudo construir el mapa: {e}")

# =============== A D M I N ===============
elif app == "Admin" and is_admin:
    st.header("Administración de usuarios")
    st.caption(f"📦 Base de datos: `{_db_path()}`")

    all_mods = [m["code"] for m in list_all_modules(enabled_only=False)]
    users = list_users()

    # Listado y selección
    st.subheader("Usuarios")
    if not users:
        st.info("No hay usuarios registrados.")
    emails = [u["email"] for u in users]
    idx = st.selectbox("Selecciona un usuario para editar", options=["(nuevo)…"] + emails, index=0)

    colA, colB = st.columns(2)

    # ---- Crear nuevo ----
    with colA:
        st.markdown("### Crear usuario")
        with st.form("create_user_form"):
            c_email = st.text_input("Email")
            c_name  = st.text_input("Nombre")
            c_role  = st.selectbox("Rol", options=["admin", "programmer", "user"], index=2)
            c_active = st.checkbox("Activo", value=True)
            c_modules = st.multiselect("Módulos permitidos", all_mods, default=all_mods)
            c_pwd   = st.text_input("Contraseña", type="password")
            ok_new = st.form_submit_button("Crear")
        if ok_new:
            if not (c_email and c_name and c_pwd):
                st.error("Completa email, nombre y contraseña.")
            else:
                try:
                    create_user(
                        email=c_email, name=c_name, role=c_role, pwd=c_pwd,
                        active=c_active, modules=c_modules
                    )
                    st.success("Usuario creado.")
                    st.rerun()
                except Exception as e:
                    st.error(f"No se pudo crear: {e}")

    # ---- Editar existente ----
    with colB:
        st.markdown("### Editar usuario")
        if idx != "(nuevo)…":
            u = next((x for x in users if x["email"] == idx), None)
            if u:
                with st.form("edit_user_form"):
                    e_name  = st.text_input("Nombre", value=u["name"])
                    e_role  = st.selectbox("Rol", options=["admin", "programmer", "user"],
                                           index=["admin","programmer","user"].index(u["role"]))
                    e_active = st.checkbox("Activo", value=u["active"])
                    e_modules = st.multiselect("Módulos permitidos", all_mods, default=u["modules"])
                    e_newpwd = st.text_input("Nueva contraseña (opcional)", type="password")
                    ok_edit = st.form_submit_button("Guardar cambios")
                if ok_edit:
                    try:
                        update_user(
                            u["id"],
                            name=e_name,
                            role=e_role,
                            active=e_active,
                            modules=e_modules,
                        )
                        if e_newpwd:
                            set_password(u["id"], e_newpwd)
                        st.success("Cambios guardados.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"No se pudo actualizar: {e}")
            else:
                st.info("Selecciona un usuario del listado para editar.")

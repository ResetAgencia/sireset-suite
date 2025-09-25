# app.py — SiReset (Streamlit) con procesamiento SEGURO (worker + logs + fallbacks)
# Copiar y reemplazar.
import os
import sys
import json
import time
import uuid
import shutil
import inspect
import traceback
from io import BytesIO
from pathlib import Path
from typing import Tuple, Optional, List, Dict

import pandas as pd
import streamlit as st
from subprocess import Popen

# ---- Compat: experimental_rerun -> rerun ----
if not hasattr(st, "experimental_rerun"):
    def experimental_rerun():
        st.rerun()
    st.experimental_rerun = experimental_rerun  # type: ignore

# ───────────────────── Panic-guard: muestra traza si algo truena al arrancar ──
st.set_option('client.showErrorDetails', True)
def _excepthook(exc_type, exc, tb):
    try:
        st.set_page_config(page_title="SiReset", layout="wide")
    except Exception:
        pass
    st.error("Fallo crítico al iniciar la app.")
    st.code("".join(traceback.format_exception(exc_type, exc, tb)))
    try:
        st.stop()
    except Exception:
        pass
sys.excepthook = _excepthook

# ───────────────────── PATHS ─────────────────────
APP_ROOT = Path(__file__).parent.resolve()
for p in (APP_ROOT, APP_ROOT / "core"):
    sp = str(p)
    if sp not in sys.path:
        sys.path.insert(0, sp)

# ───────────────────── Imports del core/auth ─────────────────────
try:
    import core.mougli_core as mc
except Exception as e:
    st.error("No pude importar core.mougli_core:\n\n" + str(e))
    st.stop()

try:
    from auth import (
        login_ui, current_user, logout_button,
        list_users, create_user, update_user, set_password, list_all_modules,
        _connect as _db_connect  # para probar ruta de DB
    )
    def _db_path():
        try:
            con = _db_connect()
            return con.execute("PRAGMA database_list;").fetchone()["file"]
        except Exception:
            return "(ruta no disponible)"
finally:
    pass

# ───────────────────── Config general ─────────────────────
st.set_page_config(page_title="SiReset", layout="wide")
try:
    st.image("assets/Encabezado.png", use_container_width=True)
except Exception:
    pass

# ───────────────────── Resolver funciones del core ─────────────────────
def require_any(preferido: str, *alternativos: str):
    candidatos = (preferido, *alternativos)
    for name in candidatos:
        fn = getattr(mc, name, None)
        if callable(fn):
            if name != preferido:
                st.info(f"Usando {name}() como alias de {preferido}().")
            return fn
    exports = sorted([x for x in dir(mc) if not x.startswith("_")])
    st.error(
        f"No encontré la función *{preferido}* en core/mougli_core.py.\n\n"
        f"Alias probados: {', '.join(alternativos) or '—'}\n\n"
        f"Funciones visibles en el módulo: {', '.join(exports) or '—'}"
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

# ───────────────────── Helpers UI ─────────────────────
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

def _scan_alertas(df: Optional[pd.DataFrame], *, es_monitor: bool) -> List[str]:
    if df is None or df.empty:
        return []
    alerts = []
    BAD_TIPOS = {
        "INSERT", "INTERNACIONAL", "OBITUARIO", "POLITICO",
        "AUTOAVISO", "PROMOCION CON AUSPICIO", "PROMOCION SIN AUSPICIO"
    }
    tipo_cols = ["TIPO ELEMENTO", "TIPO", "Tipo Elemento"]
    tipo_col = next((c for c in tipo_cols if c in df.columns), None)
    if tipo_col:
        tipos = df[tipo_col].astype(str).str.upper().str.strip().replace({"NAN": ""}).dropna()
        malos = sorted(set([t for t in tipos.unique() if t in BAD_TIPOS]))
        if malos:
            alerts.append("Se detectaron valores en TIPO ELEMENTO: " + ", ".join(malos))
    reg_col = "REGION/ÁMBITO" if es_monitor else ("Región" if ("Región" in df.columns) else None)
    if reg_col and reg_col in df.columns:
        regiones = df[reg_col].astype(str).str.upper().str.strip().replace({"NAN": ""}).dropna()
        fuera = sorted(set([r for r in regiones.unique() if r and r != "LIMA"]))
        if fuera:
            alerts.append("Regiones distintas de LIMA detectadas: " + ", ".join(fuera))
    return alerts

def llamar_procesar_monitor_outview(monitor_file, out_file, factores, outview_factor):
    try:
        sig = inspect.signature(procesar_monitor_outview).parameters
        if "outview_factor" in sig:
            return procesar_monitor_outview(monitor_file, out_file, factores=factores, outview_factor=outview_factor)
        else:
            return procesar_monitor_outview(monitor_file, out_file, factores=factores)
    except TypeError:
        try:
            return procesar_monitor_outview(monitor_file, out_file, factores, outview_factor)
        except TypeError:
            return procesar_monitor_outview(monitor_file, out_file, factores)

# ───────────────────── Job Manager (subproceso + archivos) ────────────────────
JOBS_DIR = Path(os.environ.get("SIRESET_JOBS_DIR", "/tmp/sireset_jobs")).resolve()
JOBS_DIR.mkdir(parents=True, exist_ok=True)

def _new_job_dir() -> Path:
    jid = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8]
    d = JOBS_DIR / jid
    d.mkdir(parents=True, exist_ok=True)
    return d

def _save_upload(upload, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        f.write(upload.getvalue())

def _start_worker(job_dir: Path, monitor_file, out_file, factores: Dict[str, float], out_factor: float):
    progress = job_dir / "progress.json"
    logf = job_dir / "job.log"
    outxlsx = job_dir / "SiReset_Mougli.xlsx"
    args = [
        sys.executable, "-m", "core.mougli_core", "--as-worker",
        "--out-xlsx", str(outxlsx),
        "--progress", str(progress),
        "--log", str(logf),
        "--factores-json", json.dumps(factores),
        "--outview-factor", str(out_factor)
    ]
    if monitor_file:
        args.extend(["--monitor", str(monitor_file)])
    if out_file:
        args.extend(["--outview", str(out_file)])
    # Lanzar subproceso en background
    Popen(args, cwd=str(APP_ROOT))

def _read_json_safe(p: Path) -> Dict:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}

def _job_status(job_dir: Path) -> Dict:
    return _read_json_safe(job_dir / "progress.json")

def _job_log(job_dir: Path, tail:int = 120) -> str:
    p = job_dir / "job.log"
    if not p.exists():
        return ""
    txt = p.read_text(encoding="utf-8", errors="ignore").splitlines()
    return "\n".join(txt[-tail:])

# ───────────────────── LOGIN obligatorio ─────────────────────
user = current_user()
if not user:
    login_ui()
    st.stop()

with st.sidebar:
    st.markdown(f"**Usuario:** {user.get('name') or user.get('email', '—')}")
    st.markdown(f"**Rol:** {user.get('role', '—')}")
    logout_button()

# ───────────────────── Apps permitidas ─────────────────────
mods = [str(m).lower() for m in (user.get("modules") or [])]
allowed: List[str] = []
if "mougli" in mods: allowed.append("Mougli")
if "mapito"  in mods: allowed.append("Mapito")
is_admin = (user.get("role") == "admin")
if is_admin: allowed.append("Admin")
if not allowed:
    st.warning("Tu usuario no tiene módulos habilitados. Pide acceso a un administrador.")
    st.stop()

# ───────────────────── Sidebar: selector ─────────────────────
app = st.sidebar.radio("Elige aplicación", allowed, index=0)

# ───────────────────── Factores (solo Mougli) ─────────────────────
if app == "Mougli":
    st.sidebar.markdown("### Factores")
    persist_m = load_monitor_factors()
    persist_o = load_outview_factor()
    col1, col2 = st.sidebar.columns(2)
    with col1:
        f_tv = st.number_input("TV", min_value=0.0, step=0.01, value=float(persist_m.get("TV", 0.26)))
        f_cable = st.number_input("CABLE", min_value=0.0, step=0.01, value=float(persist_m.get("CABLE", 0.42)))
        f_radio = st.number_input("RADIO", min_value=0.0, step=0.01, value=float(persist_m.get("RADIO", 0.42)))
    with col2:
        f_revista = st.number_input("REVISTA", min_value=0.0, step=0.01, value=float(persist_m.get("REVISTA", 0.15)))
        f_diarios = st.number_input("DIARIOS", min_value=0.0, step=0.01, value=float(persist_m.get("DIARIOS", 0.15)))
        out_factor = st.number_input("OutView ×Superficie", min_value=0.0, step=0.05, value=float(persist_o))
    factores = {"TV": f_tv, "CABLE": f_cable, "RADIO": f_radio, "REVISTA": f_revista, "DIARIOS": f_diarios}
    if st.sidebar.button("💾 Guardar factores"):
        save_monitor_factors(factores)
        save_outview_factor(out_factor)
        st.sidebar.success("Factores guardados.")

# ───────────────────── M O U G L I ─────────────────────
if app == "Mougli":
    st.markdown("## Mougli — modo seguro (worker)")

    # --- Cargar archivos (se guardan en disco del job) ---
    colL, colR = st.columns(2)
    with colL:
        st.caption("Sube Monitor (.txt) — opcional (varios)")
        up_monitor_multi = st.file_uploader(
            "Arrastra y suelta aquí", type=["txt"], key="m_txt_multi",
            label_visibility="collapsed", accept_multiple_files=True
        )
    with colR:
        st.caption("Sube OutView (.csv / .xlsx) — opcional (varios)")
        up_out_multi = st.file_uploader(
            "Arrastra y suelta aquí", type=["csv", "xlsx"], key="o_multi",
            label_visibility="collapsed", accept_multiple_files=True
        )

    # Estado actual del job
    if "job_dir" not in st.session_state:
        st.session_state["job_dir"] = None

    st.write("")
    start = st.button("Procesar en modo SEGURO", type="primary")

    if start:
        if not up_monitor_multi and not up_out_multi:
            st.error("Sube al menos un archivo.")
            st.stop()

        job_dir = _new_job_dir()
        mon_path, out_path = None, None

        # Combinar y guardar Monitor
        if up_monitor_multi:
            mon_path = job_dir / "monitor_combined.txt"
            with open(mon_path, "wb") as f:
                for i, upl in enumerate(up_monitor_multi):
                    if i > 0:
                        f.write(b"\n")
                    f.write(upl.getvalue())

        # Combinar y guardar OutView
        if up_out_multi:
            # Si vienen varios, los concateno a CSV (si .xlsx convierte a CSV básico)
            out_path = job_dir / "outview_combined.csv"
            first = True
            with open(out_path, "wb") as fout:
                for upl in up_out_multi:
                    name = (upl.name or "").lower()
                    if name.endswith(".csv"):
                        fout.write(upl.getvalue() if first else upl.getvalue().split(b"\n",1)[-1])
                        first = False
                    else:
                        # XLSX -> DataFrame -> CSV (sólo esta hoja)
                        try:
                            df_x = pd.read_excel(BytesIO(upl.getvalue()))
                            if first:
                                df_x.to_csv(fout, index=False, encoding="utf-8")
                                first = False
                            else:
                                df_x.to_csv(fout, index=False, header=False, encoding="utf-8")
                        except Exception:
                            # Si no se puede, lo guardo aparte y paso esa ruta al worker
                            out_path = job_dir / (Path(upl.name).stem + ".xlsx")
                            _save_upload(upl, out_path)

        _start_worker(job_dir, mon_path, out_path, factores, out_factor)
        st.session_state["job_dir"] = str(job_dir)
        st.success(f"Trabajo iniciado: {job_dir.name}")
        st.experimental_rerun()

    # Mostrar estado del job si existe
    if st.session_state.get("job_dir"):
        job_dir = Path(st.session_state["job_dir"])
        st.info(f"Job actual: `{job_dir.name}`")
        st.caption(f"Carpeta: {job_dir}")

        status = _job_status(job_dir)
        logtxt = _job_log(job_dir)

        colA, colB = st.columns(2)
        with colA:
            st.markdown("#### Estado")
            if not status:
                st.write("⏳ Esperando progreso…")
            else:
                st.json(status)
            st.button("Actualizar estado", on_click=lambda: st.experimental_rerun())
        with colB:
            st.markdown("#### Log")
            st.code(logtxt or "(sin log por ahora)")

        if status.get("status") == "ok":
            result_name = status.get("result")
            result_type = status.get("result_type", "excel")
            artifact = job_dir / result_name
            if artifact.exists():
                if result_type == "excel":
                    with open(artifact, "rb") as f:
                        st.download_button(
                            "⬇️ Descargar Excel",
                            data=f.read(),
                            file_name=result_name,
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            key="dl_excel"
                        )
                else:
                    with open(artifact, "rb") as f:
                        st.download_button(
                            "⬇️ Descargar ZIP (CSV)",
                            data=f.read(),
                            file_name=result_name,
                            mime="application/zip",
                            key="dl_zip"
                        )
                # Vista previa (si cabe)
                try:
                    # Si el worker guardó parquet — opcional
                    pv = job_dir / "preview.parquet"
                    if pv.exists():
                        import pyarrow.parquet as pq
                        df_prev = pq.read_table(pv).to_pandas()
                        st.markdown("### Vista previa")
                        st.dataframe(df_prev.head(100), use_container_width=True)
                except Exception:
                    pass

        elif status.get("status") == "error":
            st.error("El procesamiento falló en el worker.")
            if status.get("error"):
                st.code(status["error"])

        # Limpieza
        st.divider()
        if st.button("🧹 Cerrar y limpiar este job"):
            try:
                shutil.rmtree(job_dir, ignore_errors=True)
            except Exception:
                pass
            st.session_state["job_dir"] = None
            st.experimental_rerun()

# ───────────────────── M A P I T O ─────────────────────
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

# ───────────────────── A D M I N ─────────────────────
elif app == "Admin" and is_admin:
    st.header("Administración de usuarios")
    try:
        st.caption(f"📦 Base de datos: `{_db_path()}`")
    except Exception:
        pass

    all_mods = [m["code"] for m in list_all_modules(enabled_only=False)]
    users = list_users()

    st.subheader("Usuarios")
    if not users:
        st.info("No hay usuarios registrados.")
    emails = [u["email"] for u in users]
    idx = st.selectbox("Selecciona un usuario para editar", options=["(nuevo)…"] + emails, index=0)

    colA, colB = st.columns(2)

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
                    st.experimental_rerun()
                except Exception as e:
                    st.error(f"No se pudo crear: {e}")

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
                        update_user(u["id"], name=e_name, role=e_role, active=e_active, modules=e_modules)
                        if e_newpwd:
                            set_password(u["id"], e_newpwd)
                        st.success("Cambios guardados.")
                        st.experimental_rerun()
                    except Exception as e:
                        st.error(f"No se pudo actualizar: {e}")
        else:
            st.info("Selecciona un usuario del listado para editar.")

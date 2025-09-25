# app.py — SiReset (Streamlit)
# ✅ “A prueba de balas”: preview ligera; escritura Excel por trozos; errores visibles.

import gc
from io import BytesIO
from pathlib import Path
import sys
from typing import Tuple, Optional, List

import pandas as pd
import streamlit as st

# Mostrar detalles de error en la UI
st.set_option('client.showErrorDetails', True)

# --- Compatibilidad: experimental_rerun -> rerun ---
if not hasattr(st, "experimental_rerun"):
    def experimental_rerun():
        st.rerun()
    st.experimental_rerun = experimental_rerun  # type: ignore

# ---- auth imports ----
try:
    from auth import (
        login_ui, current_user, logout_button,
        list_users, create_user, update_user, set_password, list_all_modules,
        DB_PATH as AUTH_DB_PATH,
    )
except Exception as e:
    st.error(f"No pude importar el módulo de autenticación (auth.py): {e}")
    st.stop()

# ---------- Config general ----------
st.set_page_config(page_title="SiReset", layout="wide")
try:
    st.image("assets/Encabezado.png", use_container_width=True)
except Exception:
    pass

# --- asegurar import de 'core'
APP_ROOT = Path(__file__).parent.resolve()
for p in (APP_ROOT, APP_ROOT / "core"):
    sp = str(p)
    if sp not in sys.path:
        sys.path.insert(0, sp)

# --- Importar mougli_core (módulo completo) y resolver símbolos
try:
    import core.mougli_core as mc
except Exception as e:
    st.error(
        "No pude importar core.mougli_core. Verifica que exista la carpeta *core/* al lado de app.py "
        "y que dentro esté mougli_core.py.\n\n"
        f"Detalle técnico: {e}"
    )
    st.stop()


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


# Resolver funciones/exportaciones de mougli_core
procesar_monitor_outview = require_any("procesar_monitor_outview", "procesar_monitor_outview_v2", "procesar_outview_monitor")
resumen_mougli = require_any("resumen_mougli")
_read_monitor_txt = require_any("_read_monitor_txt")
_read_out_robusto = require_any("_read_out_robusto")
load_monitor_factors = require_any("load_monitor_factors")
save_monitor_factors = require_any("save_monitor_factors")
load_outview_factor = require_any("load_outview_factor")
save_outview_factor = require_any("save_outview_factor")

# --------- Helpers y constantes ---------
BAD_TIPOS = {"INSERT", "INTERNACIONAL", "OBITUARIO", "POLITICO",
             "AUTOAVISO", "PROMOCION CON AUSPICIO", "PROMOCION SIN AUSPICIO"}

HIDE_OUT_PREVIEW = {
    "Código único","Denominador","Código +1 pieza","Tarifa × Superficie",
    "Semana en Mes por Código","NB_EXTRAE_6_7","Fecha_AB","Proveedor_AC","TipoElemento_AD",
    "Distrito_AE","Avenida_AF","NroCalleCuadra_AG","OrientacionVia_AH","Marca_AI",
    "Conteo_AB_AI","Conteo_Z_AB_AI","TarifaS_div3","TarifaS_div3_sobre_Conteo",
    "Suma_AM_Z_AB_AI","TopeTipo_AQ","Suma_AM_Topada_Tipo","SumaTopada_div_ConteoZ",
}

HEAVY_BYTES = 180 * 1024 * 1024
HEAVY_ROWS_PREVIEW = 300_000
MAX_PREVIEW_ROWS = 1_000


def _unique_list_str(series, max_items=50):
    if series is None:
        return "—"
    vals = (
        series.astype(str).str.strip().replace({"nan": ""}).dropna()
        .loc[lambda s: s.str.len() > 0].unique().tolist()
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


def _read_out_file_to_df(upload) -> pd.DataFrame:
    name = (getattr(upload, "name", "") or "").lower()
    try:
        upload.seek(0)
    except Exception:
        pass
    try:
        if name.endswith(".csv"):
            try:
                return pd.read_csv(upload)
            except UnicodeDecodeError:
                upload.seek(0)
                return pd.read_csv(upload, sep=";", encoding="latin-1")
        return pd.read_excel(upload)
    except Exception:
        try:
            upload.seek(0)
            return pd.read_csv(upload, sep=";", encoding="latin-1")
        except Exception:
            return pd.DataFrame()


def combinar_monitor_txt(files) -> Tuple[Optional[BytesIO], Optional[pd.DataFrame]]:
    if not files:
        return None, None
    buf = BytesIO()
    for i, f in enumerate(files):
        data = f.getvalue()
        if i > 0:
            buf.write(b"\n")
        buf.write(data)
    buf.seek(0)
    try:
        setattr(buf, "name", "monitor_combined.txt")
    except Exception:
        pass
    df_m = None
    try:
        buf.seek(0)
        df_m = _read_monitor_txt(buf)
        buf.seek(0)
    except Exception:
        df_m = None
    return buf, df_m


def combinar_outview(files) -> Tuple[Optional[BytesIO], Optional[pd.DataFrame]]:
    if not files:
        return None, None
    dfs = []
    for f in files:
        df = _read_out_file_to_df(f)
        if df is not None and not df.empty:
            dfs.append(df)
    if not dfs:
        return None, None
    dfc = pd.concat(dfs, ignore_index=True)
    out = BytesIO()
    dfc.to_csv(out, index=False)
    out.seek(0)
    try:
        setattr(out, "name", "outview_combined.csv")
    except Exception:
        pass
    return out, dfc


def _preview_df(df: Optional[pd.DataFrame]) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    normalized_hide = {c.strip().lower() for c in HIDE_OUT_PREVIEW}
    cols_to_drop = [c for c in df.columns if c and c.strip().lower() in normalized_hide]
    if cols_to_drop:
        return df.drop(columns=cols_to_drop, errors="ignore").copy()
    return df.copy()


def _size_of_uploads(files) -> int:
    total = 0
    for f in files or []:
        try:
            total += getattr(f, "size", 0) or len(f.getvalue())
        except Exception:
            pass
    return total


# ------------------- LOGIN (obligatorio) -------------------
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

# =============== M O U G L I ===============
if app == "Mougli":
    st.markdown("## Mougli – Monitor & OutView")

    colL, colR = st.columns(2)
    with colL:
        st.caption("Sube Monitor (.txt) — puedes subir varios")
        up_monitor_multi = st.file_uploader(
            "Arrastra y suelta aquí", type=["txt"], key="m_txt_multi",
            label_visibility="collapsed", accept_multiple_files=True
        )
    with colR:
        st.caption("Sube OutView (.csv / .xlsx) — puedes subir varios")
        up_out_multi = st.file_uploader(
            "Arrastra y suelta aquí", type=["csv", "xlsx"], key="o_multi",
            label_visibility="collapsed", accept_multiple_files=True
        )

    total_bytes = _size_of_uploads(up_monitor_multi) + _size_of_uploads(up_out_multi)
    heavy_upload = total_bytes > HEAVY_BYTES
    if heavy_upload:
        st.info("⚙️ Modo seguro activado por tamaño de archivos. La vista previa será limitada y la exportación optimizada.")

    st.write("")
    if st.button("Procesar Mougli", type="primary"):
        try:
            with st.spinner("Procesando archivos..."):
                mon_proc, df_m_res = combinar_monitor_txt(up_monitor_multi or [])
                out_proc, df_o_res = combinar_outview(up_out_multi or [])

                df_result, xlsx = mc.procesar_monitor_outview(
                    mon_proc, out_proc, factores=factores, outview_factor=out_factor
                )

            st.success("¡Listo! ✅")

            colA, colB = st.columns(2)
            with colA:
                st.markdown("#### Monitor")
                if df_m_res is None and mon_proc is not None:
                    try:
                        mon_proc.seek(0)
                        df_m_res = _read_monitor_txt(mon_proc)
                        mon_proc.seek(0)
                    except Exception:
                        df_m_res = None
                st.dataframe(_web_resumen_enriquecido(df_m_res, es_monitor=True), use_container_width=True)

            with colB:
                st.markdown("#### OutView")
                if df_o_res is None and out_proc is not None:
                    try:
                        out_proc.seek(0)
                        df_o_res = _read_out_robusto(out_proc)
                        out_proc.seek(0)
                    except Exception:
                        df_o_res = None
                st.dataframe(_web_resumen_enriquecido(df_o_res, es_monitor=False), use_container_width=True)

            issues: List[str] = []
            issues += _scan_alertas(df_m_res, es_monitor=True)
            issues += _scan_alertas(df_o_res, es_monitor=False)
            if issues:
                st.warning("⚠️ **Revisión sugerida antes de exportar**:\n\n- " + "\n- ".join(issues))

            c1, c2 = st.columns(2)
            with c1:
                st.download_button(
                    "Descargar Excel (seguro)",
                    data=xlsx.getvalue(),
                    file_name="SiReset_Mougli.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            with c2:
                try:
                    csv_data = (df_result or pd.DataFrame()).to_csv(index=False).encode("utf-8")
                except Exception:
                    csv_data = b""
                st.download_button(
                    "Descargar CSV (rápido)",
                    data=csv_data,
                    file_name="SiReset_Mougli.csv",
                    mime="text/csv",
                )

            st.markdown("### Vista previa")
            rows = len(df_result) if df_result is not None else 0
            if heavy_upload or rows > HEAVY_ROWS_PREVIEW:
                st.info(f"Vista previa limitada por tamaño (filas totales: {rows:,}). Se muestran las primeras {MAX_PREVIEW_ROWS:,} filas.")
                prev = _preview_df(df_result).head(MAX_PREVIEW_ROWS)
            else:
                prev = _preview_df(df_result).head(MAX_PREVIEW_ROWS)
            st.dataframe(prev, use_container_width=True)

            del prev, df_result, df_m_res, df_o_res
            gc.collect()

        except Exception as e:
            st.error(f"Ocurrió un error procesando: {e}")
            st.exception(e)
            gc.collect()

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
            st.exception(e)

# =============== A D M I N ===============
elif app == "Admin" and is_admin:
    st.header("Administración de usuarios")
    try:
        st.caption(f"📦 Base de datos: `{AUTH_DB_PATH}`")
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
                    st.exception(e)

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
                        st.experimental_rerun()
                    except Exception as e:
                        st.error(f"No se pudo actualizar: {e}")
                        st.exception(e)
            else:
                st.info("Selecciona un usuario del listado para editar.")


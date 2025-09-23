# app.py
import sys
from pathlib import Path
from io import BytesIO
import inspect

import streamlit as st
import pandas as pd

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
    """Devuelve la primera función disponible entre preferido y alias."""
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
procesar_monitor_outview = require_any(
    "procesar_monitor_outview",
    "procesar_monitor_outview_v2",
    "procesar_outview_monitor",
)
resumen_mougli = require_any("resumen_mougli")
_read_monitor_txt = require_any("_read_monitor_txt")
_read_out_robusto = require_any("_read_out_robusto")
load_monitor_factors = require_any("load_monitor_factors")
save_monitor_factors = require_any("save_monitor_factors")
load_outview_factor = require_any("load_outview_factor")
save_outview_factor = require_any("save_outview_factor")


def llamar_procesar_monitor_outview(monitor_file, out_file, factores, outview_factor):
    """Llama a procesar_monitor_outview tolerando firmas distintas."""
    try:
        sig = inspect.signature(procesar_monitor_outview).parameters
        if "outview_factor" in sig:
            return procesar_monitor_outview(
                monitor_file, out_file, factores=factores, outview_factor=outview_factor
            )
        else:
            return procesar_monitor_outview(monitor_file, out_file, factores=factores)
    except TypeError:
        try:
            return procesar_monitor_outview(monitor_file, out_file, factores, outview_factor)
        except TypeError:
            return procesar_monitor_outview(monitor_file, out_file, factores)


# Mapito (opcional)
try:
    from core.mapito_core import build_map
except Exception:
    build_map = None

# ---------- Config ----------
st.set_page_config(page_title="SiReset", layout="wide")
DATA_DIR = Path("data")

# ---------- Encabezado ----------
st.image("assets/Encabezado.png", use_container_width=True)

# ---------- Sidebar ----------
apps = ["Mougli"]
if build_map is not None:
    apps.append("Mapito")
app = st.sidebar.radio("Elige aplicación", apps, index=0)

st.sidebar.markdown("### Factores")
persist_m = load_monitor_factors()
persist_o = load_outview_factor()

col1, col2 = st.sidebar.columns(2)
with col1:
    f_tv = st.number_input(
        "TV", min_value=0.0, step=0.01, value=float(persist_m.get("TV", 0.26))
    )
    f_cable = st.number_input(
        "CABLE", min_value=0.0, step=0.01, value=float(persist_m.get("CABLE", 0.42))
    )
    f_radio = st.number_input(
        "RADIO", min_value=0.0, step=0.01, value=float(persist_m.get("RADIO", 0.42))
    )
with col2:
    f_revista = st.number_input(
        "REVISTA", min_value=0.0, step=0.01, value=float(persist_m.get("REVISTA", 0.15))
    )
    f_diarios = st.number_input(
        "DIARIOS", min_value=0.0, step=0.01, value=float(persist_m.get("DIARIOS", 0.15))
    )
    out_factor = st.number_input(
        "OutView ×Superficie", min_value=0.0, step=0.05, value=float(persist_o)
    )

factores = {
    "TV": f_tv,
    "CABLE": f_cable,
    "RADIO": f_radio,
    "REVISTA": f_revista,
    "DIARIOS": f_diarios,
}

if st.sidebar.button("💾 Guardar factores"):
    save_monitor_factors(factores)
    save_outview_factor(out_factor)
    st.sidebar.success("Factores guardados.")


# ---------- Helpers UI ----------
BAD_TIPOS = {
    "INSERT",
    "INTERNACIONAL",
    "OBITUARIO",
    "POLITICO",
    "AUTOAVISO",
    "PROMOCION CON AUSPICIO",
    "PROMOCION SIN AUSPICIO",
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


def _web_resumen_enriquecido(df, *, es_monitor: bool) -> pd.DataFrame:
    base = resumen_mougli(df, es_monitor=es_monitor)
    if base is None or base.empty:
        base = pd.DataFrame(
            [{"Filas": 0, "Rango de fechas": "—", "Marcas / Anunciantes": 0}]
        )
    base_vertical = pd.DataFrame(
        {"Descripción": base.columns, "Valor": base.iloc[0].tolist()}
    )

    cat_col = "CATEGORIA" if es_monitor else (
        "Categoría" if (df is not None and "Categoría" in df.columns) else None
    )
    reg_col = "REGION/ÁMBITO" if es_monitor else (
        "Región" if (df is not None and "Región" in df.columns) else None
    )
    tipo_cols = ["TIPO ELEMENTO", "TIPO", "Tipo Elemento"]
    tipo_col = next((c for c in tipo_cols if (df is not None and c in df.columns)), None)

    extras_rows = []
    if df is not None and not df.empty:
        if cat_col:
            extras_rows.append(
                {"Descripción": "Categorías (únicas)", "Valor": _unique_list_str(df[cat_col])}
            )
        if reg_col:
            extras_rows.append(
                {"Descripción": "Regiones (únicas)", "Valor": _unique_list_str(df[reg_col])}
            )
        if tipo_col:
            extras_rows.append(
                {"Descripción": "Tipos de elemento (únicos)", "Valor": _unique_list_str(df[tipo_col])}
            )

    if extras_rows:
        base_vertical = pd.concat([base_vertical, pd.DataFrame(extras_rows)], ignore_index=True)

    return base_vertical


def _scan_alertas(df, *, es_monitor: bool):
    if df is None or df.empty:
        return []
    alerts = []
    tipo_cols = ["TIPO ELEMENTO", "TIPO", "Tipo Elemento"]
    tipo_col = next((c for c in tipo_cols if c in df.columns), None)
    if tipo_col:
        tipos = (
            df[tipo_col]
            .astype(str)
            .str.upper()
            .str.strip()
            .replace({"NAN": ""})
            .dropna()
        )
        malos = sorted(set([t for t in tipos.unique() if t in BAD_TIPOS]))
        if malos:
            alerts.append("Se detectaron valores en TIPO ELEMENTO: " + ", ".join(malos))
    reg_col = "REGION/ÁMBITO" if es_monitor else (
        "Región" if (df is not None and "Región" in df.columns) else None
    )
    if reg_col and reg_col in df.columns:
        regiones = (
            df[reg_col].astype(str).str.upper().str.strip().replace({"NAN": ""}).dropna()
        )
        fuera = sorted(set([r for r in regiones.unique() if r and r != "LIMA"]))
        if fuera:
            alerts.append("Regiones distintas de LIMA detectadas: " + ", ".join(fuera))
    return alerts


def _clone_for_processing_and_summary(upfile):
    """Duplica el UploadedFile en dos BytesIO (para procesar y para resumen)."""
    if upfile is None:
        return None, None
    data = upfile.getvalue()
    a = BytesIO(data)
    b = BytesIO(data)
    name = getattr(upfile, "name", "")
    try:
        setattr(a, "name", name)
        setattr(b, "name", name)
    except Exception:
        pass
    return a, b


# --------- NUEVOS helpers: combinar múltiples archivos ---------
def _read_out_file_to_df(upload) -> pd.DataFrame:
    """Lee un archivo de OutView (csv/xlsx) a DataFrame con tolerancia."""
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
        # XLSX
        return pd.read_excel(upload)
    except Exception:
        # último intento como CSV latin-1
        try:
            upload.seek(0)
            return pd.read_csv(upload, sep=";", encoding="latin-1")
        except Exception:
            return pd.DataFrame()


def combinar_monitor_txt(files) -> tuple[BytesIO | None, pd.DataFrame | None]:
    """Une varios TXT de Monitor en un único buffer y devuelve además un df de resumen."""
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

    # Intentar df de resumen
    df_m = None
    try:
        buf.seek(0)
        df_m = _read_monitor_txt(buf)
        buf.seek(0)
    except Exception:
        df_m = None
    return buf, df_m


def combinar_outview(files) -> tuple[BytesIO | None, pd.DataFrame | None]:
    """Concatena varios CSV/XLSX de OutView en un único CSV en memoria y df para resumen."""
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


# =============== M O U G L I ===============
if app == "Mougli":
    st.markdown("## Mougli – Monitor & OutView")

    colL, colR = st.columns(2)
    with colL:
        st.caption("Sube Monitor (.txt) — puedes subir varios")
        up_monitor_multi = st.file_uploader(
            "Arrastra y suelta aquí",
            type=["txt"],
            key="m_txt_multi",
            label_visibility="collapsed",
            accept_multiple_files=True,
        )
    with colR:
        st.caption("Sube OutView (.csv / .xlsx) — puedes subir varios")
        up_out_multi = st.file_uploader(
            "Arrastra y suelta aquí",
            type=["csv", "xlsx"],
            key="o_multi",
            label_visibility="collapsed",
            accept_multiple_files=True,
        )

    st.write("")
    if st.button("Procesar Mougli", type="primary"):
        try:
            # Combinar entradas
            mon_proc, df_m_res = combinar_monitor_txt(up_monitor_multi or [])
            out_proc, df_o_res = combinar_outview(up_out_multi or [])

            # Procesamiento principal (usa tu core tal cual)
            df_result, xlsx = llamar_procesar_monitor_outview(
                mon_proc, out_proc, factores=factores, outview_factor=out_factor
            )

            st.success("¡Listo! ✅")

            # Resúmenes enriquecidos (pantalla)
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
                st.dataframe(
                    _web_resumen_enriquecido(df_m_res, es_monitor=True),
                    use_container_width=True,
                )

            with colB:
                st.markdown("#### OutView")
                if df_o_res is None and out_proc is not None:
                    try:
                        out_proc.seek(0)
                        df_o_res = _read_out_robusto(out_proc)
                        out_proc.seek(0)
                    except Exception:
                        df_o_res = None
                st.dataframe(
                    _web_resumen_enriquecido(df_o_res, es_monitor=False),
                    use_container_width=True,
                )

            # Alertas
            issues = []
            issues += _scan_alertas(df_m_res, es_monitor=True)
            issues += _scan_alertas(df_o_res, es_monitor=False)
            if issues:
                st.warning("⚠️ **Revisión sugerida antes de exportar**:\n\n- " + "\n- ".join(issues))

            # Descarga Excel
            st.download_button(
                "Descargar Excel",
                data=xlsx.getvalue(),
                file_name="SiReset_Mougli.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

            # Vista previa
            st.markdown("### Vista previa")
            st.dataframe(df_result.head(100), use_container_width=True)

        except Exception as e:
            st.error(f"Ocurrió un error procesando: {e}")

# =============== M A P I T O ===============
elif app == "Mapito" and build_map is not None:
    st.markdown("## Mapito – Perú")

    st.sidebar.markdown("### Estilos del mapa")
    color_general = st.sidebar.color_picker("Color general", "#713030")
    color_sel = st.sidebar.color_picker("Color seleccionado", "#5F48C6")
    color_borde = st.sidebar.color_picker("Color de borde", "#000000")
    grosor = st.sidebar.slider("Grosor de borde", 0.1, 2.0, 0.8, 0.05)
    show_borders = st.sidebar.checkbox("Mostrar bordes", value=True)
    show_basemap = st.sidebar.checkbox("Mostrar mapa base (OSM) en vista interactiva", value=True)

    try:
        html, seleccion = build_map(
            data_dir=DATA_DIR,
            nivel="regiones",
            colores={"fill": color_general, "selected": color_sel, "border": color_borde},
            style={
                "weight": grosor,
                "show_borders": show_borders,
                "show_basemap": show_basemap,
            },
        )
        st.components.v1.html(html, height=700, scrolling=False)
        if seleccion:
            st.caption(f"Elementos mostrados: {len(seleccion)}")
    except Exception as e:
        st.error(f"No se pudo construir el mapa: {e}")
else:
    if build_map is None and app == "Mapito":
        st.info("Mapito no está disponible en este entorno.")

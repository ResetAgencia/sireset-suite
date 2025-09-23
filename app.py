# app.py
# ─────────────────────────────────────────────────────────────────────────────
# SiReset Suite - App principal (Mougli + Mapito)
# Robusta ante rutas/imports y compatible con tus módulos actuales.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import os
import sys
import inspect
from io import BytesIO
from pathlib import Path

import streamlit as st
import pandas as pd

# ───────────────────────── Bootstrap de imports (robusto) ────────────────────
try:
    APP_ROOT = Path(__file__).resolve().parent
except NameError:
    # (por si algún entorno ejecuta sin __file__)
    APP_ROOT = Path(os.getcwd()).resolve()

for p in (APP_ROOT, APP_ROOT / "core"):
    sp = str(p)
    if sp not in sys.path:
        sys.path.insert(0, sp)

# Asegura que core sea paquete (no es estrictamente necesario, pero ayuda)
init_file = APP_ROOT / "core" / "__init__.py"
try:
    if (APP_ROOT / "core").exists() and not init_file.exists():
        init_file.write_text("", encoding="utf-8")
except Exception:
    pass

# ───────────────────────────── Config general UI ─────────────────────────────
st.set_page_config(page_title="SiReset", layout="wide")
DATA_DIR = Path("data")

# Encabezado
st.image("assets/Encabezado.png", use_container_width=True)

# ─────────────────────────── Carga de mougli_core ────────────────────────────
try:
    import core.mougli_core as mc
except Exception as e:
    st.error(
        "No pude importar **core.mougli_core**.\n\n"
        "Verifica que exista la carpeta **core/** junto a `app.py` y que dentro esté "
        "**mougli_core.py** (y opcionalmente **mapito_core.py**).\n\n"
        f"Detalle técnico: {type(e).__name__}: {e}"
    )
    st.stop()


def require_any(preferido: str, *alternativos: str):
    """
    Devuelve la primera función disponible entre 'preferido' y sus aliases.
    Muestra un error claro si no se encuentra.
    """
    for name in (preferido, *alternativos):
        fn = getattr(mc, name, None)
        if callable(fn):
            # Nota informativa si se usó un alias (silencioso para no estorbar UI)
            return fn

    exports = sorted([x for x in dir(mc) if not x.startswith("_")])
    st.error(
        f"No encontré la función **{preferido}** en `core/mougli_core.py`.\n\n"
        f"Aliases probados: {', '.join(alternativos) or '—'}\n\n"
        f"Funciones visibles en el módulo: {', '.join(exports) or '—'}"
    )
    st.stop()


# Resolver funciones/exportaciones de mougli_core (sin tocar tu lógica)
procesar_monitor_outview = require_any(
    "procesar_monitor_outview",
    "procesar_monitor_outview_v2",
    "procesar_outview_monitor",
)
resumen_mougli        = require_any("resumen_mougli")
_read_monitor_txt     = require_any("_read_monitor_txt")
_read_out_robusto     = require_any("_read_out_robusto")
load_monitor_factors  = require_any("load_monitor_factors")
save_monitor_factors  = require_any("save_monitor_factors")
load_outview_factor   = require_any("load_outview_factor")
save_outview_factor   = require_any("save_outview_factor")


def llamar_procesar_monitor_outview(monitor_file, out_file, factores, outview_factor):
    """
    Llama a procesar_monitor_outview tolerando firmas distintas (con o sin
    parámetro 'outview_factor' y con/ sin kwargs).
    """
    try:
        sig = inspect.signature(procesar_monitor_outview).parameters
        if "outview_factor" in sig:
            return procesar_monitor_outview(
                monitor_file, out_file, factores=factores, outview_factor=outview_factor
            )
        else:
            return procesar_monitor_outview(monitor_file, out_file, factores=factores)
    except TypeError:
        # fallback a llamadas posicionales
        try:
            return procesar_monitor_outview(monitor_file, out_file, factores, outview_factor)
        except TypeError:
            return procesar_monitor_outview(monitor_file, out_file, factores)


# ───────────────────────────── Carga de Mapito ───────────────────────────────
# Si mapito_core o build_map no existen, Mapito no se muestra y no rompe Mougli.
try:
    from core.mapito_core import build_map
    MAPITO_OK = True
except Exception:
    build_map = None
    MAPITO_OK = False

# ───────────────────────────── Sidebar / App picker ──────────────────────────
apps = ["Mougli"]
if MAPITO_OK:
    apps.append("Mapito")
app = st.sidebar.radio("Elige aplicación", apps, index=0)

# ───────────────────────── Helpers UI de Mougli (sin tocar lógicas) ──────────
BAD_TIPOS = {
    "INSERT", "INTERNACIONAL", "OBITUARIO", "POLITICO",
    "AUTOAVISO", "PROMOCION CON AUSPICIO", "PROMOCION SIN AUSPICIO"
}


def _unique_list_str(series: pd.Series | None, max_items=50) -> str:
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


def _web_resumen_enriquecido(df: pd.DataFrame | None, *, es_monitor: bool) -> pd.DataFrame:
    base = resumen_mougli(df, es_monitor=es_monitor)
    if base is None or base.empty:
        base = pd.DataFrame([{"Filas": 0, "Rango de fechas": "—", "Marcas / Anunciantes": 0}])

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
            extras_rows.append({"Descripción": "Categorías (únicas)", "Valor": _unique_list_str(df[cat_col])})
        if reg_col:
            extras_rows.append({"Descripción": "Regiones (únicas)", "Valor": _unique_list_str(df[reg_col])})
        if tipo_col:
            extras_rows.append({"Descripción": "Tipos de elemento (únicos)", "Valor": _unique_list_str(df[tipo_col])})

    if extras_rows:
        base_vertical = pd.concat([base_vertical, pd.DataFrame(extras_rows)], ignore_index=True)

    return base_vertical


def _scan_alertas(df: pd.DataFrame | None, *, es_monitor: bool):
    if df is None or df.empty:
        return []
    alerts = []

    tipo_cols = ["TIPO ELEMENTO", "TIPO", "Tipo Elemento"]
    tipo_col = next((c for c in tipo_cols if c in df.columns), None)
    if tipo_col:
        tipos = (
            df[tipo_col].astype(str).str.upper().str.strip()
            .replace({"NAN": ""}).dropna()
        )
        malos = sorted(set([t for t in tipos.unique() if t in BAD_TIPOS]))
        if malos:
            alerts.append("Se detectaron valores en TIPO ELEMENTO: " + ", ".join(malos))

    reg_col = "REGION/ÁMBITO" if es_monitor else ("Región" if (df is not None and "Región" in df.columns) else None)
    if reg_col and reg_col in df.columns:
        regiones = (
            df[reg_col].astype(str).str.upper().str.strip()
            .replace({"NAN": ""}).dropna()
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


# ─────────────────────────────────── M O U G L I ─────────────────────────────
if app == "Mougli":
    st.markdown("## Mougli – Monitor & OutView")

    # Factores SOLO en Mougli (como pediste)
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

    factores = {
        "TV": f_tv, "CABLE": f_cable, "RADIO": f_radio,
        "REVISTA": f_revista, "DIARIOS": f_diarios
    }

    if st.sidebar.button("💾 Guardar factores"):
        save_monitor_factors(factores)
        save_outview_factor(out_factor)
        st.sidebar.success("Factores guardados.")

    colL, colR = st.columns(2)
    with colL:
        st.caption("Sube Monitor (.txt)")
        up_monitor = st.file_uploader(
            "Drag and drop file here", type=["txt"], key="m_txt", label_visibility="collapsed"
        )
    with colR:
        st.caption("Sube OutView (.csv / .xlsx)")
        up_out = st.file_uploader(
            "Drag and drop file here", type=["csv", "xlsx"], key="o_csv", label_visibility="collapsed"
        )

    st.write("")
    if st.button("Procesar Mougli", type="primary"):
        try:
            # Clonar archivos para no perder el puntero
            mon_proc, mon_sum = _clone_for_processing_and_summary(up_monitor)
            out_proc, out_sum = _clone_for_processing_and_summary(up_out)

            # Procesamiento principal (firma tolerante)
            df_result, xlsx = llamar_procesar_monitor_outview(
                mon_proc, out_proc, factores=factores, outview_factor=out_factor
            )

            st.success("¡Listo! ✅")

            # Resúmenes enriquecidos (en pantalla)
            colA, colB = st.columns(2)
            with colA:
                st.markdown("#### Monitor")
                df_m = None
                if mon_sum is not None:
                    try:
                        mon_sum.seek(0)
                        df_m = _read_monitor_txt(mon_sum)
                    except Exception:
                        df_m = None
                st.dataframe(_web_resumen_enriquecido(df_m, es_monitor=True), use_container_width=True)

            with colB:
                st.markdown("#### OutView")
                df_o = None
                if out_sum is not None:
                    try:
                        out_sum.seek(0)
                        df_o = _read_out_robusto(out_sum)
                    except Exception:
                        df_o = None
                st.dataframe(_web_resumen_enriquecido(df_o, es_monitor=False), use_container_width=True)

            # Alertas
            issues = []
            issues += _scan_alertas(df_m, es_monitor=True)
            issues += _scan_alertas(df_o, es_monitor=False)
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

# ─────────────────────────────────── M A P I T O ─────────────────────────────
elif app == "Mapito" and MAPITO_OK:
    st.markdown("## Mapito – Perú")

    # Estilos de mapa (en la barra lateral)
    st.sidebar.markdown("### Estilos del mapa")
    color_general = st.sidebar.color_picker("Color general", "#713030")
    color_sel     = st.sidebar.color_picker("Color seleccionado", "#5F48C6")
    color_borde   = st.sidebar.color_picker("Color de borde", "#000000")
    grosor        = st.sidebar.slider("Grosor de borde", 0.1, 2.0, 0.8, 0.05)
    show_borders  = st.sidebar.checkbox("Mostrar bordes", value=True)
    show_basemap  = st.sidebar.checkbox("Mostrar mapa base (OSM) en vista interactiva", value=True)

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

else:
    if app == "Mapito" and not MAPITO_OK:
        st.info("Mapito no está disponible en este entorno (no se encontró `core/mapito_core.py`).")

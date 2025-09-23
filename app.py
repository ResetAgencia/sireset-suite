# app.py
# SiReset Suite – Menú, Mougli y Mapito (estable)
import io
import json
import pathlib
from typing import Optional, Dict

import pandas as pd
import streamlit as st

from core.mougli_core import procesar_monitor_outview
from core.mapito_core import build_map

APP_TITLE = "SiReset"

# ----- CONFIG GENERAL -----
st.set_page_config(page_title=APP_TITLE, page_icon="🟪", layout="wide")

ASSETS_DIR = pathlib.Path(__file__).parent / "assets"
DATA_DIR = pathlib.Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True, parents=True)

# ----- ENCABEZADO -----
col_l, col_c, col_r = st.columns([1, 6, 1])
with col_c:
    # Muestra tu imagen de encabezado si existe, si no, solo escribe el título
    header_img = ASSETS_DIR / "Encabezado.png"
    if header_img.exists():
        st.image(str(header_img), use_container_width=True)
    else:
        st.title("SiReset")

# ----- SIDEBAR: MENÚ + ESTADO GLOBAL -----
st.sidebar.markdown("### Elige aplicación")
app = st.sidebar.radio("",
                       ["Mougli", "Mapito"],
                       label_visibility="collapsed",
                       key="app_choice")

# Factores por defecto (también usados si la función se llama sin factores)
DEFAULT_FACTORES = {
    "tv": 0.26,
    "cable": 0.42,
    "radio": 0.42,
    "revista": 0.15,
    "diarios": 0.15,
}

def _sidebar_factores() -> Dict[str, float]:
    st.sidebar.markdown("### Factores (Monitor)")
    tv = st.sidebar.number_input("TV", min_value=0.0, max_value=2.0, value=DEFAULT_FACTORES["tv"], step=0.01)
    cable = st.sidebar.number_input("CABLE", min_value=0.0, max_value=2.0, value=DEFAULT_FACTORES["cable"], step=0.01)
    radio = st.sidebar.number_input("RADIO", min_value=0.0, max_value=2.0, value=DEFAULT_FACTORES["radio"], step=0.01)
    revista = st.sidebar.number_input("REVISTA", min_value=0.0, max_value=2.0, value=DEFAULT_FACTORES["revista"], step=0.01)
    diarios = st.sidebar.number_input("DIARIOS", min_value=0.0, max_value=2.0, value=DEFAULT_FACTORES["diarios"], step=0.01)
    return {"tv": tv, "cable": cable, "radio": radio, "revista": revista, "diarios": diarios}

# Guardamos factores en session_state (así están disponibles para cualquier llamada)
if "factores" not in st.session_state:
    st.session_state["factores"] = DEFAULT_FACTORES.copy()
st.session_state["factores"] = _sidebar_factores()

# ----- APP: MOUGLI -----
def ui_mougli():
    st.header("Mougli – Monitor & OutView")

    col1, col2 = st.columns(2)
    with col1:
        st.caption("Sube Monitor (.txt)")
        up_m = st.file_uploader("",
                                type=["txt"],
                                label_visibility="collapsed",
                                key="up_monitor")
    with col2:
        st.caption("Sube OutView (.csv / .xlsx)")
        up_o = st.file_uploader("",
                                type=["csv", "xlsx"],
                                label_visibility="collapsed",
                                key="up_outview")

    run = st.button("Procesar Mougli", type="primary")
    if run:
        if not up_m:
            st.error("Sube el archivo **Monitor (.txt)**.")
            return

        # Leemos OutView si existe
        out_df: Optional[pd.DataFrame] = None
        if up_o is not None:
            if up_o.name.lower().endswith(".csv"):
                out_df = pd.read_csv(up_o)
            else:
                out_df = pd.read_excel(up_o)

        # Llamada SIEMPRE con factores (y la función también tolera None)
        factores = st.session_state.get("factores", DEFAULT_FACTORES)

        try:
            result = procesar_monitor_outview(monitor_file=up_m, outview_df=out_df, factores=factores)
        except Exception as e:
            st.error(f"Ocurrió un error procesando: {e}")
            return

        # Mostramos un ok + descarga si existe
        st.success("¡Listo! ✅")
        # Resumen simple
        if "resumen" in result:
            st.subheader("Resumen")
            st.json(result["resumen"], expanded=False)

        # Descarga Excel si corresponde
        if "excel_bytes" in result and result["excel_bytes"]:
            st.download_button(
                "Descargar Excel",
                data=result["excel_bytes"],
                file_name="mougli_resultado.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

# ----- APP: MAPITO -----
def ui_mapito():
    st.header("Mapito – Perú")
    # Estilos (color y grosor)
    st.sidebar.markdown("### Estilos del mapa")
    color_general = st.sidebar.color_picker("Color general", "#BEBEBE", key="map_gen_color")
    color_sel = st.sidebar.color_picker("Color seleccionado", "#5F48C6", key="map_sel_color")
    color_borde = st.sidebar.color_picker("Color de borde", "#000000", key="map_border_color")
    grosor = st.sidebar.slider("Grosor de borde", 0.2, 4.0, 0.8, 0.05, key="map_border_width")
    mostrar_bordes = st.sidebar.checkbox("Mostrar bordes", value=True)

    tabs = st.tabs(["Regiones", "Provincias", "Distritos", "Lima/Callao"])

    # Región
    with tabs[0]:
        st.caption("Elige una o más regiones (opcional)")
        html, _ = build_map(
            data_dir=DATA_DIR,
            nivel="regiones",
            color_general=color_general,
            color_selected=color_sel,
            color_border=color_borde,
            border_weight=grosor,
            show_borders=mostrar_bordes,
            filtros=None,
        )
        st.components.v1.html(html, height=650, scrolling=True)

    # Provincias
    with tabs[1]:
        html, _ = build_map(
            data_dir=DATA_DIR,
            nivel="provincias",
            color_general=color_general,
            color_selected=color_sel,
            color_border=color_borde,
            border_weight=grosor,
            show_borders=mostrar_bordes,
            filtros=None,
        )
        st.components.v1.html(html, height=650, scrolling=True)

    # Distritos
    with tabs[2]:
        html, _ = build_map(
            data_dir=DATA_DIR,
            nivel="distritos",
            color_general=color_general,
            color_selected=color_sel,
            color_border=color_borde,
            border_weight=grosor,
            show_borders=mostrar_bordes,
            filtros=None,
        )
        st.components.v1.html(html, height=650, scrolling=True)

    # Lima/Callao
    with tabs[3]:
        html, _ = build_map(
            data_dir=DATA_DIR,
            nivel="lima_callao",
            color_general=color_general,
            color_selected=color_sel,
            color_border=color_borde,
            border_weight=grosor,
            show_borders=mostrar_bordes,
            filtros=None,
        )
        st.components.v1.html(html, height=650, scrolling=True)

# ----- ROUTER -----
if app == "Mougli":
    ui_mougli()
else:
    ui_mapito()

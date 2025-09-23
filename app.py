import io
import json
import streamlit as st
from pathlib import Path

# --- Módulos de negocio
from core.mougli_core import procesar_monitor_outview, resumen_mougli
from core.mapito_core import build_map

# ---------- Config ----------
st.set_page_config(page_title="SiReset", layout="wide")
DATA_DIR = Path("data")  # carpeta base para geojson y auxiliares (Mapito)

# ---------- Encabezado ----------
st.image("assets/Encabezado.png", use_container_width=True)

# ---------- Sidebar: selector de aplicación ----------
app = st.sidebar.radio("Elige aplicación", ["Mougli", "Mapito"], index=0)

# =============== M O U G L I ===============
if app == "Mougli":
    st.markdown("## Mougli – Monitor & OutView")

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

    # --------- Factores SOLO en Mougli ----------
    st.sidebar.markdown("### Factores (Monitor)")
    f_tv = st.sidebar.number_input("TV", min_value=0.0, step=0.01, value=0.26)
    f_cable = st.sidebar.number_input("CABLE", min_value=0.0, step=0.01, value=0.42)
    f_radio = st.sidebar.number_input("RADIO", min_value=0.0, step=0.01, value=0.42)
    f_revista = st.sidebar.number_input("REVISTA", min_value=0.0, step=0.01, value=0.15)
    f_diarios = st.sidebar.number_input("DIARIOS", min_value=0.0, step=0.01, value=0.15)

    factores = {
        "TV": f_tv,
        "CABLE": f_cable,
        "RADIO": f_radio,
        "REVISTA": f_revista,
        "DIARIOS": f_diarios,
    }

    st.write("")
    if st.button("Procesar Mougli", type="primary", use_container_width=False):
        try:
            df, xlsx = procesar_monitor_outview(
                up_monitor, up_out, factores=factores
            )
            st.success("¡Listo! ✅")

            # Descarga Excel (si se generó)
            if xlsx is not None:
                st.download_button(
                    "Descargar Excel",
                    data=xlsx.getvalue(),
                    file_name="mougli_resultado.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )

            # Resumen bonito
            st.markdown("### Resumen")
            st.dataframe(resumen_mougli(df), use_container_width=True)

        except Exception as e:
            st.error(f"Ocurrió un error procesando: {e}")

# =============== M A P I T O ===============
else:
    st.markdown("## Mapito – Perú")

    # Controles de estilo SOLO Mapito
    st.sidebar.markdown("### Estilos del mapa")
    color_general = st.sidebar.color_picker("Color general", "#713030")
    color_sel = st.sidebar.color_picker("Color seleccionado", "#5F48C6")
    color_borde = st.sidebar.color_picker("Color de borde", "#000000")
    grosor = st.sidebar.slider("Grosor de borde", 0.1, 2.0, 0.8, 0.05)

    show_borders = st.sidebar.checkbox("Mostrar bordes", value=True)
    show_basemap = st.sidebar.checkbox("Mostrar mapa base (OSM) en vista interactiva", value=True)

    # Construye el mapa (usa GeoJSON locales dentro de data/peru)
    try:
        html, seleccion = build_map(
            data_dir=DATA_DIR,
            nivel="regiones",
            colores={
                "fill": color_general,
                "selected": color_sel,
                "border": color_borde,
            },
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

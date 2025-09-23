import streamlit as st
from pathlib import Path

# --- Módulos de negocio
from core.mougli_core import (
    procesar_monitor_outview,
    resumen_mougli,
    _read_monitor_txt,
    _read_out_robusto,
    load_monitor_factors,
    save_monitor_factors,
    load_outview_factor,
    save_outview_factor,
)
from core.mapito_core import build_map  # si no usas Mapito, puedes comentar esta línea

# ---------- Config ----------
st.set_page_config(page_title="SiReset", layout="wide")
DATA_DIR = Path("data")

# ---------- Encabezado ----------
st.image("assets/Encabezado.png", use_container_width=True)

# ---------- Sidebar: selector & ajustes ----------
app = st.sidebar.radio("Elige aplicación", ["Mougli", "Mapito"], index=0)

st.sidebar.markdown("### Factores")
# Cargar persistentes
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
    btn = st.button("Procesar Mougli", type="primary")
    if btn:
        try:
            df_result, xlsx = procesar_monitor_outview(
                up_monitor, up_out, factores=factores, outview_factor=out_factor
            )
            st.success("¡Listo! ✅")

            # --- Resumen “doble” (misma lógica del core)
            colA, colB = st.columns(2)
            with colA:
                st.markdown("#### Monitor")
                df_m = _read_monitor_txt(up_monitor) if up_monitor else None
                st.dataframe(resumen_mougli(df_m, es_monitor=True), use_container_width=True)
            with colB:
                st.markdown("#### OutView")
                df_o = _read_out_robusto(up_out) if up_out else None
                st.dataframe(resumen_mougli(df_o, es_monitor=False), use_container_width=True)

            # --- Descarga Excel multihoja
            st.download_button(
                "Descargar Excel",
                data=xlsx.getvalue(),
                file_name="SiReset_Mougli.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

            # Vista rápida (Consolidado si existe)
            st.markdown("### Vista previa")
            st.dataframe(df_result.head(100), use_container_width=True)

        except Exception as e:
            st.error(f"Ocurrió un error procesando: {e}")

# =============== M A P I T O ===============
else:
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
            style={"weight": grosor, "show_borders": show_borders, "show_basemap": show_basemap},
        )
        st.components.v1.html(html, height=700, scrolling=False)
        if seleccion:
            st.caption(f"Elementos mostrados: {len(seleccion)}")
    except Exception as e:
        st.error(f"No se pudo construir el mapa: {e}")

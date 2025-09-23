# app.py
import streamlit as st
from pathlib import Path
import pandas as pd

# --- Módulos de negocio (Mougli) – NO TOCAR ---
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

# --- Mapito (nuevo backend matplotlib) ---
from core.mapito_core import (
    load_layers,
    list_regiones, list_provincias, list_distritos,
    draw_map_png,
)

# ---------- Config ----------
st.set_page_config(page_title="SiReset", layout="wide")
DATA_DIR = Path("data")

# ---------- Encabezado ----------
st.image("assets/Encabezado.png", use_container_width=True)

# ---------- Selector app ----------
app = st.sidebar.radio("Elige aplicación", ["Mougli", "Mapito"], index=0)

# ---------- Factores (solo Mougli) ----------
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


# ============================================================
#                         M O U G L I
# ============================================================
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

            colA, colB = st.columns(2)
            with colA:
                st.markdown("#### Monitor")
                df_m = None
                if up_monitor is not None:
                    try:
                        up_monitor.seek(0)
                        df_m = _read_monitor_txt(up_monitor)
                    except Exception:
                        df_m = None
                st.dataframe(resumen_mougli(df_m, es_monitor=True), use_container_width=True)

            with colB:
                st.markdown("#### OutView")
                df_o = None
                if up_out is not None:
                    try:
                        up_out.seek(0)
                        df_o = _read_out_robusto(up_out)
                    except Exception:
                        df_o = None
                st.dataframe(resumen_mougli(df_o, es_monitor=False), use_container_width=True)

            # Descarga Excel
            st.download_button(
                "Descargar Excel",
                data=xlsx.getvalue(),
                file_name="SiReset_Mougli.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

            # Vista rápida
            st.markdown("### Vista previa")
            st.dataframe(df_result.head(100), use_container_width=True)

        except Exception as e:
            st.error(f"Ocurrió un error procesando: {e}")

# ============================================================
#                         M A P I T O
# ============================================================
else:
    st.markdown("## Mapito – Perú")

    # Cargar capas una sola vez
    try:
        regiones_gdf, provincias_gdf, distritos_gdf = load_layers(DATA_DIR)
    except Exception as e:
        st.error(f"No se pudo construir el mapa: {e}")
        st.stop()

    # ---- Controles de estilo (sidebar) ----
    st.sidebar.markdown("### Estilos del mapa")
    color_general = st.sidebar.color_picker("Color general", "#713030")
    color_sel = st.sidebar.color_picker("Color seleccionado", "#5F48C6")
    color_borde = st.sidebar.color_picker("Color de borde", "#000000")
    grosor = st.sidebar.slider("Grosor de borde", 0.1, 3.0, 0.8, 0.05)
    show_borders = st.sidebar.checkbox("Mostrar bordes", value=True)

    st.sidebar.markdown("### Fondo y exportación")
    trans = st.sidebar.checkbox("PNG sin fondo (transparente)", value=False)
    color_fondo = None if trans else st.sidebar.color_picker("Color de fondo del PNG", "#ffffff")

    recortar = st.sidebar.checkbox("Recortar al área seleccionada", value=False)

    # ---- Jerarquía de selección ----
    st.markdown("### Selección")
    nivel = st.radio("Nivel", ["regiones", "provincias", "distritos", "lima"], index=0,
                     horizontal=True, help="Elige el nivel que vas a resaltar.")

    regiones_sel: list[str] = []
    provincias_sel: list[str] = []
    distritos_sel: list[str] = []
    lima_groups_sel: list[str] = []

    if nivel == "regiones":
        regiones_sel = st.multiselect("Elige regiones", list_regiones(regiones_gdf))

    elif nivel == "provincias":
        regiones_sel = st.multiselect("Primero elige regiones (opcional)", list_regiones(regiones_gdf))
        provincias_sel = st.multiselect(
            "Elige provincias",
            list_provincias(provincias_gdf, regiones_sel)
        )

    elif nivel == "distritos":
        regiones_sel = st.multiselect("Primero elige regiones (opcional)", list_regiones(regiones_gdf))
        provincias_sel = st.multiselect(
            "Ahora elige provincias (opcional, filtra por las regiones elegidas)",
            list_provincias(provincias_gdf, regiones_sel)
        )
        distritos_sel = st.multiselect(
            "Elige distritos",
            list_distritos(distritos_gdf, provincias_sel=provincias_sel, regiones_sel=regiones_sel)
        )

    else:  # lima
        grupos = ["LimaNorte", "LimaEste", "LimaCentro", "LimaSur", "LimaModerna", "Callao"]
        lima_groups_sel = st.multiselect("Grupos Lima/Callao", grupos)

    # ---- Render ----
    gen = st.button("Generar mapa", type="primary")
    if gen:
        try:
            png, n = draw_map_png(
                data_dir=DATA_DIR,
                nivel=nivel,
                regiones_sel=regiones_sel,
                provincias_sel=provincias_sel,
                distritos_sel=distritos_sel,
                lima_groups_sel=lima_groups_sel,
                color_general=color_general,
                color_selected=color_sel,
                color_borde=color_borde,
                grosor_borde=grosor,
                mostrar_borde=show_borders,
                fondo_transparente=trans,
                color_fondo=color_fondo,
                recortar_area=recortar,
            )

            st.success(f"Mostrando: {nivel} — resaltados: {n}")
            st.image(png, use_container_width=True)

            # Botones de descarga: con y sin fondo
            cold1, cold2 = st.columns(2)
            with cold1:
                st.download_button(
                    "⬇ PNG (SIN fondo)",
                    data=draw_map_png(
                        data_dir=DATA_DIR, nivel=nivel,
                        regiones_sel=regiones_sel, provincias_sel=provincias_sel,
                        distritos_sel=distritos_sel, lima_groups_sel=lima_groups_sel,
                        color_general=color_general, color_selected=color_sel,
                        color_borde=color_borde, grosor_borde=grosor, mostrar_borde=show_borders,
                        fondo_transparente=True, color_fondo="#ffffff", recortar_area=recortar
                    )[0].getvalue(),
                    file_name="mapito_sin_fondo.png",
                    mime="image/png",
                )
            with cold2:
                st.download_button(
                    "⬇ PNG (CON fondo)",
                    data=draw_map_png(
                        data_dir=DATA_DIR, nivel=nivel,
                        regiones_sel=regiones_sel, provincias_sel=provincias_sel,
                        distritos_sel=distritos_sel, lima_groups_sel=lima_groups_sel,
                        color_general=color_general, color_selected=color_sel,
                        color_borde=color_borde, grosor_borde=grosor, mostrar_borde=show_borders,
                        fondo_transparente=False, color_fondo=(color_fondo or "#ffffff"), recortar_area=recortar
                    )[0].getvalue(),
                    file_name="mapito_con_fondo.png",
                    mime="image/png",
                )

        except Exception as e:
            st.error(f"No se pudo construir el mapa: {e}")


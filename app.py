import streamlit as st
from pathlib import Path
import pandas as pd

# ========= Mougli =========
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

# ========= Mapito =========
from core.mapito_core import (
    build_map,
    available_names,
    _load_geojson,
    export_png_from_geojson,
    export_csv_names,
    _try_import_matplotlib,
    build_hierarchy_indices,
)

# =========================
# Config & paths
# =========================
st.set_page_config(page_title="SiReset", layout="wide")

DATA_DIR_CANDIDATES = [
    Path(__file__).parent / "core" / "data",
    Path("core/data"),
    Path("data"),
    Path("."),
]
DATA_DIR = next((p for p in DATA_DIR_CANDIDATES if p.exists()), Path("data"))

# Encabezado
st.image("assets/Encabezado.png", use_container_width=True)

# Selector
app = st.sidebar.radio("Elige aplicación", ["Mougli", "Mapito"], index=0)

# ======================================================================
# M O U G L I
# ======================================================================
if app == "Mougli":
    st.sidebar.markdown("### Factores (Monitor/OutView)")
    # Persistentes
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

    BAD_TIPOS = {
        "INSERT", "INTERNACIONAL", "OBITUARIO", "POLITICO",
        "AUTOAVISO", "PROMOCION CON AUSPICIO", "PROMOCION SIN AUSPICIO"
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
        return ", ".join(vals[:max_items]) + (f" … (+{len(vals)-max_items} más)" if len(vals) > max_items else "")

    def _web_resumen_enriquecido(df, *, es_monitor: bool) -> pd.DataFrame:
        base = resumen_mougli(df, es_monitor=es_monitor)
        if base is None or base.empty:
            base = pd.DataFrame([{"Filas": 0, "Rango de fechas": "—", "Marcas / Anunciantes": 0}])
        base_vertical = pd.DataFrame({"Descripción": base.columns, "Valor": base.iloc[0].tolist()})
        # extras
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

    def _scan_alertas(df, *, es_monitor: bool):
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
        reg_col = "REGION/ÁMBITO" if es_monitor else ("Región" if (df is not None and "Región" in df.columns) else None)
        if reg_col and reg_col in df.columns:
            regiones = df[reg_col].astype(str).str.upper().str.strip().replace({"NAN": ""}).dropna()
            fuera = sorted(set([r for r in regiones.unique() if r and r != "LIMA"]))
            if fuera:
                alerts.append("Regiones distintas de LIMA detectadas: " + ", ".join(fuera))
        return alerts

    st.write("")
    btn = st.button("Procesar Mougli", type="primary")
    if btn:
        try:
            df_result, xlsx = procesar_monitor_outview(up_monitor, up_out, factores=factores, outview_factor=out_factor)
            st.success("¡Listo! ✅")

            colA, colB = st.columns(2)
            with colA:
                st.markdown("#### Monitor")
                df_m = None
                if up_monitor is not None:
                    up_monitor.seek(0)
                    df_m = _read_monitor_txt(up_monitor)
                st.dataframe(_web_resumen_enriquecido(df_m, es_monitor=True), use_container_width=True)
            with colB:
                st.markdown("#### OutView")
                df_o = None
                if up_out is not None:
                    up_out.seek(0)
                    df_o = _read_out_robusto(up_out)
                st.dataframe(_web_resumen_enriquecido(df_o, es_monitor=False), use_container_width=True)

            issues = []
            issues += _scan_alertas(df_m, es_monitor=True)
            issues += _scan_alertas(df_o, es_monitor=False)
            if issues:
                st.warning("⚠️ **Revisión sugerida antes de exportar**:\n\n- " + "\n- ".join(issues))

            st.download_button(
                "Descargar Excel",
                data=xlsx.getvalue(),
                file_name="SiReset_Mougli.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

            st.markdown("### Vista previa")
            st.dataframe(df_result.head(100), use_container_width=True)

        except Exception as e:
            st.error(f"Ocurrió un error procesando: {e}")

# ======================================================================
# M A P I T O  (UX jerárquica)
# ======================================================================
else:
    st.markdown("## Mapito – Perú")

    # Estilos del mapa (sidebar)
    st.sidebar.markdown("### Estilos del mapa")
    color_general = st.sidebar.color_picker("Color general", "#713030")
    color_sel = st.sidebar.color_picker("Color seleccionado", "#5F48C6")
    color_borde = st.sidebar.color_picker("Color de borde", "#000000")
    grosor = st.sidebar.slider("Grosor de borde", 0.1, 2.0, 0.8, 0.05)
    show_borders = st.sidebar.checkbox("Mostrar bordes", value=True)
    show_basemap = st.sidebar.checkbox("Mostrar mapa base (OSM) en vista interactiva", value=True)

    # Exportación
    st.sidebar.markdown("### Exportación")
    png_transparent = st.sidebar.checkbox("PNG sin fondo (transparente)", value=True)
    bg_color = None
    if not png_transparent:
        bg_color = st.sidebar.color_picker("Color de fondo del PNG", "#FFFFFF")
    have_mpl = _try_import_matplotlib()
    if not have_mpl:
        st.sidebar.info("Para exportar PNG instala: `pip install matplotlib`")

    # Cargar geojsons e índices solo una vez
    gj_reg = _load_geojson(DATA_DIR, "regiones")
    gj_prov = _load_geojson(DATA_DIR, "provincias")
    gj_dist = _load_geojson(DATA_DIR, "distritos")
    idx = build_hierarchy_indices(gj_reg, gj_prov, gj_dist)

    # === Selectores jerárquicos ===
    st.caption("Selecciona por niveles (las opciones se filtran automáticamente).")
    colR, colP, colD = st.columns(3)

    # Regiones
    reg_all = available_names(gj_reg, idx["k1"])
    sel_reg = colR.multiselect("Regiones", options=reg_all, default=[], help="Escribe para buscar")

    # Provincias filtradas por regiones seleccionadas
    if sel_reg:
        prov_opts = sorted({p for r in sel_reg for p in idx["reg_to_provs"].get(r, set())})
    else:
        prov_opts = available_names(gj_prov, idx["k2"])
    sel_prov = colP.multiselect("Provincias", options=prov_opts, default=[], help="Se filtran por regiones elegidas")

    # Distritos filtrados por provincias seleccionadas (o regiones cuando no hay provincias)
    if sel_prov:
        dist_opts = sorted({d for p in sel_prov for d in idx["prov_to_dists"].get(p, set())})
    elif sel_reg:
        # todas las prov de esas regiones → sus distritos
        provs = {p for r in sel_reg for p in idx["reg_to_provs"].get(r, set())}
        dist_opts = sorted({d for p in provs for d in idx["prov_to_dists"].get(p, set())})
    else:
        dist_opts = available_names(gj_dist, idx["k3"])
    sel_dist = colD.multiselect("Distritos", options=dist_opts, default=[], help="Se filtran por provincias elegidas")

    # Chips
    def chips(lst):
        return " ".join(f"<span style='display:inline-block;padding:6px 10px;margin:0 6px 6px 0;border-radius:16px;background:#efefef'>{s}</span>" for s in lst)
    if sel_reg: st.markdown("**Regiones:** " + chips(sel_reg), unsafe_allow_html=True)
    if sel_prov: st.markdown("**Provincias:** " + chips(sel_prov), unsafe_allow_html=True)
    if sel_dist: st.markdown("**Distritos:** " + chips(sel_dist), unsafe_allow_html=True)

    # Determinar nivel a dibujar (más específico disponible)
    if sel_dist:
        draw_level = "distritos"
        draw_selection = sel_dist
    elif sel_prov:
        draw_level = "provincias"
        draw_selection = sel_prov
    else:
        draw_level = "regiones"
        draw_selection = sel_reg

    try:
        html, seleccion_norm, gj_draw, name_key = build_map(
            data_dir=DATA_DIR,
            nivel=draw_level,
            colores={"fill": color_general, "selected": color_sel, "border": color_borde},
            style={"weight": grosor, "show_borders": show_borders, "show_basemap": show_basemap},
            seleccion=draw_selection,
        )
        st.components.v1.html(html, height=700, scrolling=False)

        st.caption(f"Mostrando: **{draw_level}** — resaltados: {len(seleccion_norm)}")

        # Descargas
        colA, colB, colC = st.columns(3)
        with colA:
            csv_bytes = export_csv_names(seleccion_norm or available_names(gj_draw, name_key), header=name_key)
            st.download_button("⬇ CSV (mostrado)", data=csv_bytes, file_name=f"{draw_level}.csv", mime="text/csv")

        if have_mpl:
            with colB:
                png_bytes = export_png_from_geojson(
                    gj_draw,
                    seleccion=seleccion_norm,
                    name_key=name_key,
                    color_fill=color_general,
                    color_selected=color_sel,
                    color_border=color_borde,
                    background=None if png_transparent else bg_color,
                )
                fname = f"mapito_{draw_level}_{'transp' if png_transparent else 'fondo'}.png"
                st.download_button("⬇ PNG (actual)", data=png_bytes, file_name=fname, mime="image/png")
            with colC:
                png_bytes_alt = export_png_from_geojson(
                    gj_draw,
                    seleccion=seleccion_norm,
                    name_key=name_key,
                    color_fill=color_general,
                    color_selected=color_sel,
                    color_border=color_borde,
                    background="#FFFFFF" if png_transparent else None,
                )
                altname = f"mapito_{draw_level}_{'fondo' if png_transparent else 'transp'}.png"
                st.download_button("⬇ PNG (alterno)", data=png_bytes_alt, file_name=altname, mime="image/png")

    except Exception as e:
        st.error(f"No se pudo construir el mapa: {e}")

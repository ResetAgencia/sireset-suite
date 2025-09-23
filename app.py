# … (todo Mougli igual que ya te compartí) …

# =============== M A P I T O ===============
else:
    st.markdown("## Mapito – Perú")

    # ── Estilos y opciones
    st.sidebar.markdown("### Estilos del mapa")
    color_general = st.sidebar.color_picker("Color general", "#713030")
    color_sel = st.sidebar.color_picker("Color seleccionado", "#5F48C6")
    color_borde = st.sidebar.color_picker("Color de borde", "#000000")
    grosor = st.sidebar.slider("Grosor de borde", 0.1, 2.0, 0.8, 0.05)
    show_borders = st.sidebar.checkbox("Mostrar bordes", value=True)
    show_basemap = st.sidebar.checkbox("Mostrar mapa base (OSM) en vista interactiva", value=True)

    # Controles de exportación
    st.sidebar.markdown("### Exportación")
    png_transparent = st.sidebar.checkbox("PNG sin fondo (transparente)", value=True)
    bg_color = None
    if not png_transparent:
        bg_color = st.sidebar.color_picker("Color de fondo del PNG", "#FFFFFF")

    # Barra de selección (chips)
    st.markdown(
        """
        <style>
        .chip {display:inline-block;padding:6px 10px;margin:0 6px 6px 0;border-radius:16px;background:#efefef;}
        </style>
        """,
        unsafe_allow_html=True,
    )

    # Cargar lista de nombres para el multiselect
    try:
        # Cargamos una vez para poblar el multiselect
        from core.mapito_core import build_map, available_names, _load_geojson, export_png_from_geojson, export_csv_names
        DATA_DIR_CANDIDATES = [Path(__file__).parent / "core" / "data", Path("core/data"), Path("data")]
        DATA_DIR = next((p for p in DATA_DIR_CANDIDATES if p.exists()), Path("data"))

        # GeoJSON base para el selector
        gj_for_list = _load_geojson(DATA_DIR, "regiones")
        all_names = available_names(gj_for_list)

        sel = st.multiselect("Selecciona regiones a resaltar", options=all_names, default=[], help="Escribe para buscar")
        # Chips arriba
        if sel:
            st.write(" ".join(f"<span class='chip'>{s}</span>" for s in sel), unsafe_allow_html=True)

        # Construir mapa con la selección actual
        html, seleccion_norm, gj, name_key = build_map(
            data_dir=DATA_DIR,
            nivel="regiones",
            colores={"fill": color_general, "selected": color_sel, "border": color_borde},
            style={"weight": grosor, "show_borders": show_borders, "show_basemap": show_basemap},
            seleccion=sel,
        )
        st.components.v1.html(html, height=700, scrolling=False)
        st.caption(f"Elementos mostrados: {len(seleccion_norm)}")

        # Botones de descarga
        colA, colB, colC = st.columns(3)
        with colA:
            png_bytes = export_png_from_geojson(
                gj,
                seleccion=seleccion_norm,
                name_key=name_key,
                color_fill=color_general,
                color_selected=color_sel,
                color_border=color_borde,
                background=None if png_transparent else bg_color,
            )
            fname = "mapito_transparente.png" if png_transparent else "mapito_con_fondo.png"
            st.download_button("⬇ PNG (actual)", data=png_bytes, file_name=fname, mime="image/png")
        with colB:
            # Siempre ofrezco la alternativa opuesta por conveniencia
            png_bytes_alt = export_png_from_geojson(
                gj,
                seleccion=seleccion_norm,
                name_key=name_key,
                color_fill=color_general,
                color_selected=color_sel,
                color_border=color_borde,
                background="#FFFFFF" if png_transparent else None,
            )
            altname = "mapito_con_fondo.png" if png_transparent else "mapito_transparente.png"
            st.download_button("⬇ PNG (alterno)", data=png_bytes_alt, file_name=altname, mime="image/png")
        with colC:
            csv_bytes = export_csv_names(seleccion_norm or all_names)
            st.download_button("⬇ CSV (regiones mostradas)", data=csv_bytes, file_name="regiones.csv", mime="text/csv")

    except Exception as e:
        st.error(f"No se pudo construir el mapa: {e}")

# app.py
import sys
from pathlib import Path
from io import BytesIO
import inspect
import json

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
        "No pude importar `core.mougli_core`. Verifica que exista la carpeta **core/** al lado de `app.py` "
        "y que dentro esté `mougli_core.py`.\n\n"
        f"Detalle técnico: {e}"
    )
    st.stop()

def require_any(preferido: str, *alternativos: str):
    candidatos = (preferido, *alternativos)
    for name in candidatos:
        fn = getattr(mc, name, None)
        if callable(fn):
            if name != preferido:
                st.info(f"Usando `{name}()` como alias de `{preferido}()`.")
            return fn
    exports = sorted([x for x in dir(mc) if not x.startswith("_")])
    st.error(
        f"No encontré la función **{preferido}** en `core/mougli_core.py`.\n\n"
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
resumen_mougli      = require_any("resumen_mougli")
_read_monitor_txt   = require_any("_read_monitor_txt")
_read_out_robusto   = require_any("_read_out_robusto")
load_monitor_factors = require_any("load_monitor_factors")
save_monitor_factors = require_any("save_monitor_factors")
load_outview_factor  = require_any("load_outview_factor")
save_outview_factor  = require_any("save_outview_factor")

def llamar_procesar_monitor_outview(monitor_file, out_file, factores, outview_factor):
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

# ---------- Selector de app ----------
apps = ["Mougli"]
if build_map is not None:
    apps.append("Mapito")
app = st.sidebar.radio("Elige aplicación", apps, index=0)

# ---------- Sidebar: Factores SOLO en Mougli ----------
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

# ---------- Helpers UI Mougli ----------
BAD_TIPOS = {
    "INSERT", "INTERNACIONAL", "OBITUARIO", "POLITICO",
    "AUTOAVISO", "PROMOCION CON AUSPICIO", "PROMOCION SIN AUSPICIO"
}

def _unique_list_str(series, max_items=50):
    if series is None:
        return "—"
    vals = (
        series.astype(str).str.strip()
        .replace({"nan": ""}).dropna()
        .loc[lambda s: s.str.len() > 0].unique().tolist()
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

def _clone_for_processing_and_summary(upfile):
    if upfile is None:
        return None, None
    data = upfile.getvalue()
    a = BytesIO(data); b = BytesIO(data)
    name = getattr(upfile, "name", "")
    try:
        setattr(a, "name", name)
        setattr(b, "name", name)
    except Exception:
        pass
    return a, b

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
    if st.button("Procesar Mougli", type="primary"):
        try:
            mon_proc, mon_sum = _clone_for_processing_and_summary(up_monitor)
            out_proc, out_sum = _clone_for_processing_and_summary(up_out)

            df_result, xlsx = llamar_procesar_monitor_outview(
                mon_proc, out_proc, factores=load_monitor_factors(), outview_factor=load_outview_factor()
            )

            st.success("¡Listo! ✅")

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

# =============== M A P I T O ===============
elif app == "Mapito" and build_map is not None:
    st.markdown("## Mapito – Perú")

    # ───────────────── Sidebar: estilos/visibilidad (colores aquí)
    st.sidebar.markdown("### Estilos del mapa")
    color_general = st.sidebar.color_picker("Color general", "#713030")
    color_sel     = st.sidebar.color_picker("Color seleccionado", "#5F48C6")
    color_borde   = st.sidebar.color_picker("Color de borde", "#000000")
    color_fondo   = st.sidebar.color_picker("Color de fondo del mapa", "#CAE3EC")
    show_borders  = st.sidebar.checkbox("Mostrar bordes", value=True)
    show_basemap  = st.sidebar.checkbox("Mostrar mapa base (OSM) en vista interactiva", value=True)

    # ───────────────── Cargar catálogos (regiones/provincias/distritos)
    import json
    DATA_DIR = Path("data")

    def _read_fc(p: Path) -> dict:
        return json.loads((DATA_DIR / p).read_text(encoding="utf-8"))

    gj1 = _read_fc(Path("gadm41_PER_1.json"))  # regiones
    gj2 = _read_fc(Path("gadm41_PER_2.json"))  # provincias
    gj3 = _read_fc(Path("gadm41_PER_3.json"))  # distritos

    regiones = sorted({f["properties"]["NAME_1"] for f in gj1["features"]})
    prov_all = [(f["properties"]["NAME_1"], f["properties"]["NAME_2"]) for f in gj2["features"]]
    dist_all = [
        (f["properties"]["NAME_1"], f["properties"]["NAME_2"], f["properties"]["NAME_3"])
        for f in gj3["features"]
    ]

    # ───────────────── Filtros arriba del mapa
    c1, c2, c3, c4 = st.columns([1.1, 1.4, 1.8, 1.2])
    with c1:
        sel_reg = st.multiselect("Regiones", regiones, default=[])
    with c2:
        prov_disp = sorted({p for p in prov_all if (not sel_reg) or p[0] in sel_reg})
        sel_prov = st.multiselect("Provincias", prov_disp, format_func=lambda t: f"{t[1]} ({t[0]})", default=[])
    with c3:
        if sel_prov:
            prov_set = set(sel_prov)
            dist_disp = sorted({d for d in dist_all if (d[0], d[1]) in prov_set})
        elif sel_reg:
            reg_set = set(sel_reg)
            dist_disp = sorted({d for d in dist_all if d[0] in reg_set})
        else:
            dist_disp = []
        sel_dist = st.multiselect("Distritos", dist_disp, format_func=lambda t: f"{t[2]} - {t[1]} ({t[0]})", default=[])
    with c4:
        ZONAS_LIMA = {
            "Norte": ["Ancón","Santa Rosa","Puente Piedra","Comas","Carabayllo",
                      "Independencia","San Martín de Porres","Los Olivos"],
            "Centro": ["Lima","Breña","Lince","Jesús María","La Victoria",
                       "Pueblo Libre","Magdalena del Mar","San Miguel"],
            "Este": ["San Juan de Lurigancho","Ate","Santa Anita","El Agustino",
                     "La Molina","Chaclacayo","Cieneguilla","Lurigancho-Chosica"],
            "Sur": ["San Juan de Miraflores","Villa María del Triunfo","Villa El Salvador",
                    "Pachacámac","Lurín","Punta Hermosa","Punta Negra","San Bartolo",
                    "Pucusana","Santa María del Mar","Chorrillos"],
            "Callao": ["Callao","Bellavista","Carmen de la Legua-Reynoso","La Perla",
                       "La Punta","Ventanilla","Mi Perú"],
        }
        zonas_sel = st.multiselect("Zonas de Lima", list(ZONAS_LIMA.keys()), default=[])

    # Ajustar vista arriba (se queda aquí, no en la barra)
    fit_selected = st.checkbox("Ajustar vista a lo seleccionado", value=True)

    # Expandir zonas a distritos (Lima/Callao)
    if zonas_sel:
        dist_lookup = set((d[0].lower(), d[1].lower(), d[2].lower()) for d in dist_all)
        extra = []
        for z in zonas_sel:
            for d in ZONAS_LIMA.get(z, []):
                k1 = ("lima", "lima", d.lower())
                k2 = ("callao", "callao", d.lower())
                if k1 in dist_lookup:
                    extra.append(("Lima", "Lima", d))
                if k2 in dist_lookup:
                    extra.append(("Callao", "Callao", d))
        sel_dist = sorted(set(list(sel_dist) + extra))

    # Normalizar selecciones para build_map
    def low(s): return (s or "").strip().lower()
    selections = {
        "regions":   [low(r) for r in sel_reg],
        "provinces": [(low(a), low(b)) for (a, b) in sel_prov],
        "districts": [(low(a), low(b), low(c)) for (a, b, c) in sel_dist],
    }

    # ───────────────── Construir mapa
    try:
        html, meta = build_map(
            data_dir=DATA_DIR,
            colores={"fill": color_general, "selected": color_sel, "border": color_borde},
            style={"weight": 0.8, "show_borders": show_borders, "show_basemap": show_basemap},
            selections=selections,
            fit_selected=fit_selected,
            background_color=color_fondo,   # <- color de fondo desde la sidebar
        )
        st.components.v1.html(html, height=700, scrolling=False)
        st.caption(f"Mostrando: general={meta.get('n_regions',0)} · destacados={meta.get('n_selected',0)}")
    except Exception as e:
        st.error(f"No se pudo construir el mapa: {e}")

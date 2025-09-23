from pathlib import Path
import json
import folium
from folium import GeoJson

# Render Folium dentro de Streamlit
def _folium_to_html(m: folium.Map) -> str:
    return m.get_root().render()

def _load_geojson(data_dir: Path, nivel: str) -> dict:
    """
    Intenta varias rutas:
      1) data_dir/peru/{nivel}.json
      2) data_dir/{nivel}.json
      3) GADM mapeado:
         - regiones   -> gadm41_PER_1.json
         - provincias -> gadm41_PER_2.json
         - distritos  -> gadm41_PER_3.json
    También prueba data_dir relativo al módulo (core/data).
    """
    candidates = []

    # Rutas relativas al data_dir pasado
    candidates.append(data_dir / "peru" / f"{nivel}.json")
    candidates.append(data_dir / f"{nivel}.json")

    # Mapear a archivos GADM si existen
    gadm_map = {
        "regiones": "gadm41_PER_1.json",
        "provincias": "gadm41_PER_2.json",
        "distritos": "gadm41_PER_3.json",
    }
    if nivel in gadm_map:
        candidates.append(data_dir / gadm_map[nivel])

    # Alternativa: core/data si se llamó con otro base path
    core_data = Path(__file__).parent / "data"
    candidates.append(core_data / "peru" / f"{nivel}.json")
    candidates.append(core_data / f"{nivel}.json")
    if nivel in gadm_map:
        candidates.append(core_data / gadm_map[nivel])

    for p in candidates:
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))

    # Si nada funcionó, error entendible
    tried = " | ".join(str(p) for p in candidates)
    raise FileNotFoundError(f"No se encontró GeoJSON para '{nivel}'. Probé: {tried}")

def build_map(
    data_dir: Path,
    nivel: str = "regiones",
    colores: dict | None = None,
    style: dict | None = None,
):
    """
    colores: {"fill": "#713030", "selected": "#5F48C6", "border": "#000000"}
    style: {"weight": 0.8, "show_borders": True, "show_basemap": True}
    """
    colores = colores or {}
    style = style or {}
    col_fill = colores.get("fill", "#713030")
    col_border = colores.get("border", "#000000")
    weight = float(style.get("weight", 0.8))
    show_borders = bool(style.get("show_borders", True))
    show_basemap = bool(style.get("show_basemap", True))

    gj = _load_geojson(data_dir, nivel)

    # Centro aproximado del Perú
    m = folium.Map(location=[-9.2, -75.0], zoom_start=5, tiles=None)

    if show_basemap:
        folium.TileLayer("openstreetmap", name="OSM").add_to(m)

    def _style(_):
        return {
            "color": col_border if show_borders else col_fill,
            "weight": weight if show_borders else 0.0,
            "fillColor": col_fill,
            "fillOpacity": 0.85,
        }

    # Campos posibles en GADM: NAME_1 / NAME_2 / NAME_3
    props0 = gj["features"][0]["properties"]
    tooltip_fields = [k for k in ("NAME_1", "NAME_2", "NAME_3", "NAME_0") if k in props0]

    GeoJson(
        gj,
        name=nivel.capitalize(),
        style_function=_style,
        tooltip=folium.GeoJsonTooltip(fields=tooltip_fields),
    ).add_to(m)

    folium.LayerControl().add_to(m)

    html = _folium_to_html(m)
    return html, []  # selección futura

from pathlib import Path
import json
import folium
from folium import GeoJson
from branca.colormap import linear

# Para renderizar el mapa dentro de Streamlit
def _folium_to_html(m: folium.Map) -> str:
    root = m.get_root()
    return root.render()

def _load_geojson(data_dir: Path, nivel: str) -> dict:
    # Ajusta rutas a tus archivos reales:
    # data/peru/regiones.json , data/peru/provincias.json , data/peru/distritos.json
    path = data_dir / "peru" / f"{nivel}.json"
    if not path.exists():
        raise FileNotFoundError(f"No existe {path}")
    return json.loads(path.read_text(encoding="utf-8"))

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
    col_selected = colores.get("selected", "#5F48C6")  # reservado para futura selección
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

    GeoJson(
        gj,
        name=nivel.capitalize(),
        style_function=_style,
        tooltip=folium.GeoJsonTooltip(fields=[k for k in ("NAME_1","NAME_2","NAME_3") if k in gj["features"][0]["properties"]]),
    ).add_to(m)

    folium.LayerControl().add_to(m)

    html = _folium_to_html(m)
    seleccion = []  # si luego agregas filtros, retorna la lista de códigos/ids
    return html, seleccion


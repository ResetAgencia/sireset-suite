from pathlib import Path
import json
import folium
from folium import GeoJson

# Para renderizar el mapa dentro de Streamlit
def _folium_to_html(m: folium.Map) -> str:
    root = m.get_root()
    return root.render()

def _first_existing(*paths: Path) -> Path | None:
    for p in paths:
        if p and p.exists():
            return p
    return None

def _load_geojson(data_dir: Path, nivel: str) -> dict:
    """
    Intenta cargar primero los GADM:
      - gadm41_PER_1.json (regiones)
      - gadm41_PER_2.json (provincias)
      - gadm41_PER_3.json (distritos)
    y como alternativa, archivos en data/peru/{nivel}.json si existieran.
    """
    nivel = (nivel or "").lower().strip()
    lvl_map = {"regiones": 1, "provincias": 2, "distritos": 3}
    lvl = lvl_map.get(nivel, 1)

    # Rutas candidatas
    gadm = data_dir / f"gadm41_PER_{lvl}.json"
    alt  = data_dir / "peru" / f"{nivel}.json"

    p = _first_existing(gadm, alt)
    if not p:
        raise FileNotFoundError(
            f"No encontré el GeoJSON para {nivel}. Busqué: {gadm} y {alt}"
        )
    return json.loads(p.read_text(encoding="utf-8"))

def build_map(
    data_dir: Path,
    nivel: str = "regiones",
    colores: dict | None = None,
    style: dict | None = None,
):
    """
    Devuelve (html, seleccion)
    - html: mapa folium renderizado
    - seleccion: lista vacía (reservado para futuras selecciones)
    """
    colores = colores or {}
    style = style or {}
    col_fill = colores.get("fill", "#713030")
    col_border = colores.get("border", "#000000")
    weight = float(style.get("weight", 0.8))
    show_borders = bool(style.get("show_borders", True))
    show_basemap = bool(style.get("show_basemap", True))

    # Cargar datos
    gj = _load_geojson(data_dir, nivel)

    # Centro aproximado del Perú
    m = folium.Map(location=[-9.2, -75.0], zoom_start=5, tiles=None)

    if show_basemap:
        folium.TileLayer("openstreetmap", name="OSM").add_to(m)

    # Campos posibles por nivel (GADM)
    # NAME_1: región/departamento, NAME_2: provincia, NAME_3: distrito
    prop0 = gj["features"][0]["properties"] if gj.get("features") else {}
    tooltip_fields = [k for k in ("NAME_1", "NAME_2", "NAME_3") if k in prop0]
    if not tooltip_fields:
        # fallback genérico
        tooltip_fields = [k for k in prop0.keys() if isinstance(k, str)][:1]

    def _style(_feature):
        return {
            "color": col_border if show_borders else col_fill,
            "weight": weight if show_borders else 0.0,
            "fillColor": col_fill,
            "fillOpacity": 0.85,
        }

    # GeoJson
    GeoJson(
        gj,
        name=nivel.capitalize(),
        style_function=_style,
        tooltip=folium.GeoJsonTooltip(fields=tooltip_fields),
        highlight_function=lambda f: {"weight": weight + 0.6, "fillOpacity": 0.95},
        control=True,
        embed=False,
        zoom_on_click=False,
    ).add_to(m)

    folium.LayerControl().add_to(m)

    html = _folium_to_html(m)
    seleccion = []  # reservado para más adelante
    return html, seleccion

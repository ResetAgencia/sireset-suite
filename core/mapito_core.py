from pathlib import Path
import json
import folium
from folium import GeoJson


# -------------------- Utiles --------------------
def _folium_to_html(m: folium.Map) -> str:
    """Render del mapa Folium a HTML embebible en Streamlit."""
    return m.get_root().render()


def _try_read_json(p: Path) -> dict | None:
    try:
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        pass
    return None


def _load_geojson(data_dir: Path, nivel: str) -> dict:
    """
    Busca primero data/peru/{nivel}.json.
    Si no existe, cae a los GADM:
      - regiones   -> gadm41_PER_1.json (NAME_1)
      - provincias -> gadm41_PER_2.json (NAME_2)
      - distritos  -> gadm41_PER_3.json (NAME_3)
    """
    # 1) Intento "peru/{nivel}.json"
    p1 = data_dir / "peru" / f"{nivel}.json"
    gj = _try_read_json(p1)
    if gj:
        return gj

    # 2) Fallback a GADM
    map_gadm = {
        "regiones": data_dir / "gadm41_PER_1.json",
        "provincias": data_dir / "gadm41_PER_2.json",
        "distritos": data_dir / "gadm41_PER_3.json",
    }
    p2 = map_gadm.get(nivel)
    gj = _try_read_json(p2) if p2 else None
    if gj:
        return gj

    raise FileNotFoundError(
        f"No encontré GeoJSON para '{nivel}'. Probé: {p1} "
        + (f"y {p2}" if p2 else "")
    )


# -------------------- API pública --------------------
def build_map(
    data_dir: Path,
    nivel: str = "regiones",
    colores: dict | None = None,
    style: dict | None = None,
):
    """
    Devuelve:
      html (str): HTML del mapa Folium para st.components.v1.html
      seleccion (list): reservado (por ahora [])
    """
    colores = colores or {}
    style = style or {}

    col_fill = colores.get("fill", "#713030")
    col_selected = colores.get("selected", "#5F48C6")  # reservado (futuro)
    col_border = colores.get("border", "#000000")

    weight = float(style.get("weight", 0.8))
    show_borders = bool(style.get("show_borders", True))
    show_basemap = bool(style.get("show_basemap", True))

    nivel = (nivel or "regiones").lower().strip()
    if nivel not in {"regiones", "provincias", "distritos"}:
        nivel = "regiones"

    # Cargar GeoJSON (peru/{nivel}.json o gadm41_PER_X.json)
    gj = _load_geojson(data_dir, nivel)

    # Centro Perú aproximado
    m = folium.Map(location=[-9.2, -75.0], zoom_start=5, tiles=None)
    if show_basemap:
        folium.TileLayer("openstreetmap", name="OSM").add_to(m)

    # Campo de nombre para el tooltip
    # Si viene de "peru/{nivel}.json" normalmente ya está limpio.
    # En GADM los nombres típicos son NAME_1 / NAME_2 / NAME_3.
    props = gj["features"][0]["properties"]
    name_key = None
    for cand in ("name", "NAME", "NAME_1", "NAME_2", "NAME_3"):
        if cand in props:
            name_key = cand
            break

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
        tooltip=folium.GeoJsonTooltip(
            fields=[name_key] if name_key else [],
            aliases=["Nombre"] if name_key else None,
        ),
    ).add_to(m)

    folium.LayerControl().add_to(m)

    html = _folium_to_html(m)
    seleccion = []  # reservado para selección futura
    return html, seleccion

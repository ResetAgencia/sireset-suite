from pathlib import Path
import json
import folium
from folium import GeoJson

def _folium_to_html(m: folium.Map) -> str:
    return m.get_root().render()

def _try_read_json(p: Path) -> dict | None:
    try:
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        pass
    return None

def _load_geojson(data_dir: Path, nivel: str) -> dict:
    # 1) data/peru/{nivel}.json
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
        f"No encontré GeoJSON para '{nivel}'. Probé: {p1}"
        + (f" y {p2}" if p2 else "")
    )

def build_map(
    data_dir: Path,
    nivel: str = "regiones",
    colores: dict | None = None,
    style: dict | None = None,
):
    """Devuelve (html, seleccion) para usar con st.components.v1.html en app.py."""
    colores = colores or {}
    style = style or {}
    col_fill = colores.get("fill", "#713030")
    col_selected = colores.get("selected", "#5F48C6")  # reservado
    col_border = colores.get("border", "#000000")
    weight = float(style.get("weight", 0.8))
    show_borders = bool(style.get("show_borders", True))
    show_basemap = bool(style.get("show_basemap", True))
    bg_color = style.get("bg_color", "#A9D3DF")  # NUEVO: color de fondo

    nivel = (nivel or "regiones").lower().strip()
    if nivel not in {"regiones", "provincias", "distritos"}:
        nivel = "regiones"

    gj = _load_geojson(data_dir, nivel)

    # Perú centrado
    m = folium.Map(location=[-9.2, -75.0], zoom_start=5, tiles=None)
    if show_basemap:
        folium.TileLayer("openstreetmap", name="OSM").add_to(m)

    # Inyectar CSS para color de fondo del lienzo Leaflet
    m.get_root().html.add_child(
        folium.Element(
            f"<style>.leaflet-container{{background:{bg_color} !important;}}</style>"
        )
    )

    # Elegir nombre para tooltip
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
    return html, []

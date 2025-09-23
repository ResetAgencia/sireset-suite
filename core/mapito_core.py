from pathlib import Path
import json
import math
from typing import Dict, List, Tuple, Iterable

import folium
from folium import GeoJson


# =============================
# util folium → HTML para st
# =============================
def _folium_to_html(m: folium.Map) -> str:
    return m.get_root().render()


# =============================
# carga de geojson por nivel
# =============================
def _first_existing(*paths: Path) -> Path | None:
    for p in paths:
        if p and p.exists():
            return p
    return None


def _load_geojson(data_dir: Path, nivel: str) -> dict:
    """
    Intenta cargar primero GADM:
      - gadm41_PER_1.json (regiones)
      - gadm41_PER_2.json (provincias)
      - gadm41_PER_3.json (distritos)
    Fallback: data/peru/{nivel}.json
    """
    nivel = (nivel or "").lower().strip()
    lvl_map = {"regiones": 1, "provincias": 2, "distritos": 3}
    lvl = lvl_map.get(nivel, 1)

    gadm = data_dir / f"gadm41_PER_{lvl}.json"
    alt = data_dir / "peru" / f"{nivel}.json"

    p = _first_existing(gadm, alt)
    if not p:
        raise FileNotFoundError(f"No encontré GeoJSON para {nivel} (busqué {gadm} y {alt}).")
    return json.loads(p.read_text(encoding="utf-8"))


# =============================
# jerarquía (región→prov→dist)
# =============================
def _safe_prop(props: dict, key: str) -> str:
    v = props.get(key, "")
    return "" if v is None else str(v)


def build_hierarchy(data_dir: Path) -> tuple[Dict[str, List[str]], Dict[tuple[str, str], List[str]]]:
    """
    Devuelve:
      - provincias_por_region: {NAME_1: [NAME_2,...]}
      - distritos_por_region_prov: {(NAME_1, NAME_2): [NAME_3,...]}
    Construido a partir de GADM nivel 3 (contiene NAME_1/NAME_2/NAME_3).
    """
    gj3 = _load_geojson(data_dir, "distritos")
    provincias_por_region: Dict[str, set] = {}
    distritos_por_region_prov: Dict[tuple[str, str], set] = {}

    for f in gj3.get("features", []):
        p = f.get("properties", {})
        r = _safe_prop(p, "NAME_1")
        pr = _safe_prop(p, "NAME_2")
        d = _safe_prop(p, "NAME_3")
        if not r or not pr or not d:
            continue
        provincias_por_region.setdefault(r, set()).add(pr)
        distritos_por_region_prov.setdefault((r, pr), set()).add(d)

    # orden alfabético consistente
    provincias_por_region_sorted = {r: sorted(list(provs)) for r, provs in provincias_por_region.items()}
    distritos_por_region_prov_sorted = {k: sorted(list(v)) for k, v in distritos_por_region_prov.items()}
    return provincias_por_region_sorted, distritos_por_region_prov_sorted


# =============================
# filtro/estilo de selección
# =============================
def _name_tuple(feature_props: dict) -> tuple[str, str, str]:
    return (
        _safe_prop(feature_props, "NAME_1"),
        _safe_prop(feature_props, "NAME_2"),
        _safe_prop(feature_props, "NAME_3"),
    )


def _is_selected(props: dict, nivel: str,
                 sel_reg: set[str], sel_prov: set[tuple[str, str]], sel_dist: set[tuple[str, str, str]]) -> bool:
    r, p, d = _name_tuple(props)
    if nivel == "regiones":
        return r in sel_reg
    if nivel == "provincias":
        return (r, p) in sel_prov or (r in sel_reg)  # si marcaste región también resalta todo dentro
    # distritos
    return (r, p, d) in sel_dist or (r, p) in sel_prov or (r in sel_reg)


def _filtered_geojson(gj: dict, nivel: str,
                      sel_reg: set[str], sel_prov: set[tuple[str, str]], sel_dist: set[tuple[str, str, str]]) -> dict:
    """ Devuelve una copia del GeoJSON con solo las features seleccionadas. """
    feats = []
    for f in gj.get("features", []):
        if _is_selected(f.get("properties", {}), nivel, sel_reg, sel_prov, sel_dist):
            feats.append(f)
    return {"type": "FeatureCollection", "features": feats}


# =============================
# mapa folium (html)
# =============================
def build_map(
    data_dir: Path,
    nivel: str = "regiones",
    colores: dict | None = None,
    style: dict | None = None,
    # selección & comportamiento
    selected_regions: Iterable[str] | None = None,
    selected_provinces: Iterable[tuple[str, str]] | None = None,  # (region, provincia)
    selected_districts: Iterable[tuple[str, str, str]] | None = None,  # (region, prov, dist)
    crop_to_selection: bool = False,
    background_color: str | None = None,  # solo visual (no export)
):
    """
    Devuelve (html, seleccion)
    - nivel: "regiones" | "provincias" | "distritos"
    - crop_to_selection: True → solo se muestran features seleccionadas. False → se ve todo y se resaltan las seleccionadas.
    """
    colores = colores or {}
    style = style or {}

    col_fill = colores.get("fill", "#713030")
    col_selected = colores.get("selected", "#5F48C6")
    col_border = colores.get("border", "#000000")
    weight = float(style.get("weight", 0.8))
    show_borders = bool(style.get("show_borders", True))
    show_basemap = bool(style.get("show_basemap", True))

    nivel = (nivel or "regiones").lower().strip()
    gj = _load_geojson(data_dir, nivel)

    sel_reg = set(selected_regions or [])
    sel_prov = set(selected_provinces or [])
    sel_dist = set(selected_districts or [])

    # Crop?
    gj_to_draw = _filtered_geojson(gj, nivel, sel_reg, sel_prov, sel_dist) if crop_to_selection else gj

    # Centro aprox Perú
    m = folium.Map(location=[-9.2, -75.0], zoom_start=5, tiles=None)
    if show_basemap:
        folium.TileLayer("openstreetmap", name="OSM").add_to(m)

    # Fijar color de fondo del contenedor del mapa (no afecta a export PNG)
    if background_color:
        m.get_root().html.add_child(folium.Element(
            f"<style>.leaflet-container{{background:{background_color}!important;}}</style>"
        ))

    # tooltip dinámico
    prop0 = gj_to_draw["features"][0]["properties"] if gj_to_draw.get("features") else {}
    tooltip_fields = [k for k in ("NAME_1", "NAME_2", "NAME_3") if k in prop0] or list(prop0.keys())[:1]

    def _style_function(feat):
        props = feat.get("properties", {})
        selected = _is_selected(props, nivel, sel_reg, sel_prov, sel_dist)
        edge = col_border if show_borders else (col_selected if selected else col_fill)
        return {
            "color": edge,
            "weight": weight if show_borders else (weight + 0.8 if selected else 0.0),
            "fillColor": col_selected if selected else col_fill,
            "fillOpacity": 0.88 if selected else 0.80,
        }

    GeoJson(
        gj_to_draw,
        name=nivel.capitalize(),
        style_function=_style_function,
        tooltip=folium.GeoJsonTooltip(fields=tooltip_fields),
        highlight_function=lambda f: {"weight": weight + 0.6, "fillOpacity": 0.95},
        control=True,
        embed=False,
        zoom_on_click=False,
    ).add_to(m)

    folium.LayerControl().add_to(m)

    return _folium_to_html(m), []


# =============================
# Export PNG (matplotlib puro)
# =============================
def _extract_polygons(geom: dict) -> List[List[Tuple[float, float]]]:
    """
    Convierte un geometry GeoJSON en una lista de polígonos (cada uno = lista de (lon,lat)).
    Solo exterior (sin hoyos) para uso simple en PNG.
    """
    polys: List[List[Tuple[float, float]]] = []
    gtype = geom.get("type")
    coords = geom.get("coordinates")

    if gtype == "Polygon":
        if coords:
            outer = coords[0]
            polys.append([(float(x), float(y)) for x, y in outer])
    elif gtype == "MultiPolygon":
        for poly in coords or []:
            if poly:
                outer = poly[0]
                polys.append([(float(x), float(y)) for x, y in outer])
    return polys


def export_png(
    data_dir: Path,
    nivel: str,
    # selección
    selected_regions: Iterable[str] | None = None,
    selected_provinces: Iterable[tuple[str, str]] | None = None,
    selected_districts: Iterable[tuple[str, str, str]] | None = None,
    # estilo
    face_all: str = "#713030",
    face_sel: str = "#5F48C6",
    edge: str = "#000000",
    linewidth: float = 0.6,
    transparent: bool = False,
    bg_color: str = "#ffffff",
    crop_to_selection: bool = False,
    fig_width: int = 1200,
    fig_height: int = 900,
) -> bytes:
    """
    Genera un PNG por matplotlib.
    - Si transparent=True => alpha fondo 0.
    - crop_to_selection: True => extiende los ejes al bbox de la selección.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.patches import Polygon as MplPolygon
    except Exception as e:
        raise RuntimeError("matplotlib no está disponible para exportar PNG") from e

    nivel = (nivel or "regiones").lower().strip()
    gj = _load_geojson(data_dir, nivel)

    sel_reg = set(selected_regions or [])
    sel_prov = set(selected_provinces or [])
    sel_dist = set(selected_districts or [])

    # preparar figura
    dpi = 100
    fig = plt.figure(figsize=(fig_width / dpi, fig_height / dpi), dpi=dpi)
    ax = fig.add_subplot(111)

    # bounds
    minx = miny = +1e9
    maxx = maxy = -1e9
    any_selected = False

    for feat in gj.get("features", []):
        props = feat.get("properties", {})
        geom = feat.get("geometry", {})
        polys = _extract_polygons(geom)
        if not polys:
            continue

        selected = _is_selected(props, nivel, sel_reg, sel_prov, sel_dist)
        any_selected = any_selected or selected

        fc = face_sel if selected else face_all
        for ring in polys:
            xs, ys = zip(*ring)
            minx, miny = min(minx, min(xs)), min(miny, min(ys))
            maxx, maxy = max(maxx, max(xs)), max(maxy, max(ys))
            patch = MplPolygon(ring, closed=True, facecolor=fc, edgecolor=edge, linewidth=linewidth)
            ax.add_patch(patch)

    # límites
    if crop_to_selection and any_selected:
        pass  # ya usamos bbox acumulado
    else:
        # usar bbox global Perú si no cropeas o no hay selección
        # (aprox) long/lat
        minx, miny, maxx, maxy = (-82.0, -19.0, -68.5, -0.0)

    # margen
    dx = maxx - minx
    dy = maxy - miny
    pad_x = dx * 0.03
    pad_y = dy * 0.03
    ax.set_xlim(minx - pad_x, maxx + pad_x)
    ax.set_ylim(miny - pad_y, maxy + pad_y)

    ax.set_aspect("equal", adjustable="box")
    ax.axis("off")

    buf_bg = (0, 0, 0, 0) if transparent else None
    if not transparent:
        fig.patch.set_facecolor(bg_color)
        ax.set_facecolor(bg_color)

    from io import BytesIO
    out = BytesIO()
    fig.savefig(out, format="png", dpi=dpi, bbox_inches="tight", pad_inches=0, transparent=transparent, facecolor=buf_bg)
    plt.close(fig)
    out.seek(0)
    return out.getvalue()

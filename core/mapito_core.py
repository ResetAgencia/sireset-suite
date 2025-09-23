from __future__ import annotations

from pathlib import Path
import io
import json
from typing import Iterable, List, Tuple

import folium
from folium import GeoJson

# ────────────────────────── util folium → html ──────────────────────────
def _folium_to_html(m: folium.Map) -> str:
    return m.get_root().render()

# ────────────────────────── carga de geojson ────────────────────────────
def _load_geojson(data_dir: Path, nivel: str) -> dict:
    """
    Busca los datos en varias rutas:
      1) data_dir/peru/{nivel}.json
      2) data_dir/{nivel}.json
      3) GADM mapeado:
           regiones   → gadm41_PER_1.json
           provincias → gadm41_PER_2.json
           distritos  → gadm41_PER_3.json
      4) lo mismo pero relativo a core/data
    """
    candidates = []
    candidates.append(data_dir / "peru" / f"{nivel}.json")
    candidates.append(data_dir / f"{nivel}.json")

    gadm_map = {
        "regiones": "gadm41_PER_1.json",
        "provincias": "gadm41_PER_2.json",
        "distritos": "gadm41_PER_3.json",
    }
    if nivel in gadm_map:
        candidates.append(data_dir / gadm_map[nivel])

    core_data = Path(__file__).parent / "data"
    candidates.append(core_data / "peru" / f"{nivel}.json")
    candidates.append(core_data / f"{nivel}.json")
    if nivel in gadm_map:
        candidates.append(core_data / gadm_map[nivel])

    for p in candidates:
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))

    tried = " | ".join(str(p) for p in candidates)
    raise FileNotFoundError(f"No se encontró GeoJSON para '{nivel}'. Probé: {tried}")

# ────────────────────────── helpers de propiedades ──────────────────────
def _name_field(gj: dict) -> str:
    # toma el primer campo disponible entre NAME_1/2/3/0
    props0 = gj["features"][0]["properties"]
    for k in ("NAME_1", "NAME_2", "NAME_3", "NAME_0"):
        if k in props0:
            return k
    # fallback: primer string que parezca nombre
    for k, v in props0.items():
        if isinstance(v, str):
            return k
    return list(props0.keys())[0]

def available_names(gj: dict) -> List[str]:
    key = _name_field(gj)
    vals = [f["properties"].get(key, "") for f in gj["features"]]
    # filtra vacíos y ordena
    return sorted({str(v) for v in vals if str(v).strip()})

# ────────────────────────── construcción del mapa ───────────────────────
def build_map(
    data_dir: Path,
    nivel: str = "regiones",
    colores: dict | None = None,
    style: dict | None = None,
    seleccion: Iterable[str] | None = None,
) -> Tuple[str, List[str], dict, str]:
    """
    Devuelve: (html, seleccion_normalizada, geojson, name_field)
    - colores: {"fill": "#713030", "selected": "#5F48C6", "border": "#000000"}
    - style:   {"weight": 0.8, "show_borders": True, "show_basemap": True}
    - seleccion: lista de nombres a resaltar (según campo nombre).
    """
    colores = colores or {}
    style = style or {}
    col_fill = colores.get("fill", "#713030")
    col_selected = colores.get("selected", "#5F48C6")
    col_border = colores.get("border", "#000000")
    weight = float(style.get("weight", 0.8))
    show_borders = bool(style.get("show_borders", True))
    show_basemap = bool(style.get("show_basemap", True))

    gj = _load_geojson(data_dir, nivel)
    name_key = _name_field(gj)

    sel = set(s.strip() for s in (seleccion or []) if str(s).strip())
    # Centro aproximado del Perú
    m = folium.Map(location=[-9.2, -75.0], zoom_start=5, tiles=None)
    if show_basemap:
        folium.TileLayer("openstreetmap", name="OSM").add_to(m)

    def style_fn(feat):
        name = str(feat["properties"].get(name_key, "")).strip()
        is_sel = name in sel
        return {
            "color": col_border if show_borders else (col_selected if is_sel else col_fill),
            "weight": weight if show_borders else 0.0,
            "fillColor": col_selected if is_sel else col_fill,
            "fillOpacity": 0.85 if is_sel else 0.7,
        }

    tooltip_fields = [k for k in ("NAME_1", "NAME_2", "NAME_3", "NAME_0") if k in gj["features"][0]["properties"]]
    GeoJson(
        gj,
        name=nivel.capitalize(),
        style_function=style_fn,
        tooltip=folium.GeoJsonTooltip(fields=tooltip_fields) if tooltip_fields else None,
    ).add_to(m)

    folium.LayerControl().add_to(m)
    html = _folium_to_html(m)
    return html, sorted(list(sel)), gj, name_key

# ────────────────────────── exportaciones ────────────────────────────────
def export_png_from_geojson(
    gj: dict,
    *,
    seleccion: Iterable[str] | None,
    name_key: str,
    color_fill: str,
    color_selected: str,
    color_border: str,
    background: str | None,  # None → transparente
    figsize: Tuple[int, int] = (1600, 1600),
) -> bytes:
    """
    Exporta un PNG simple (sin tiles OSM) dibujando los polígonos del GeoJSON.
    No requiere geopandas/cartopy. Usa matplotlib.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Polygon
    from matplotlib.collections import PatchCollection

    sel = set(s.strip() for s in (seleccion or []) if str(s).strip())
    patches_sel: List[Polygon] = []
    patches_rest: List[Polygon] = []

    def add_poly(coords, is_sel: bool):
        # coords: [[(lon,lat),...], ...]  (posibles multipolígonos)
        for ring in coords:
            xy = [(x, y) for (x, y) in ring]
            (patches_sel if is_sel else patches_rest).append(Polygon(xy, closed=True))

    for feat in gj["features"]:
        geom = feat["geometry"]
        name = str(feat["properties"].get(name_key, "")).strip()
        is_sel = name in sel
        if geom["type"] == "Polygon":
            add_poly(geom["coordinates"], is_sel)
        elif geom["type"] == "MultiPolygon":
            for poly in geom["coordinates"]:
                add_poly(poly, is_sel)

    # Extensión aproximada del Perú para que salga bien centrado
    xs, ys = [], []
    for feat in gj["features"]:
        geom = feat["geometry"]
        if geom["type"] == "Polygon":
            for ring in geom["coordinates"]:
                for x, y in ring:
                    xs.append(x); ys.append(y)
        elif geom["type"] == "MultiPolygon":
            for poly in geom["coordinates"]:
                for ring in poly:
                    for x, y in ring:
                        xs.append(x); ys.append(y)

    fig = plt.figure(figsize=(figsize[0]/100, figsize[1]/100), dpi=100)
    ax = plt.axes()
    ax.set_aspect("equal", adjustable="box")
    ax.axis("off")

    if patches_rest:
        pc_rest = PatchCollection(patches_rest, facecolor=color_fill, edgecolor=color_border, linewidths=0.6, alpha=0.85)
        ax.add_collection(pc_rest)
    if patches_sel:
        pc_sel = PatchCollection(patches_sel, facecolor=color_selected, edgecolor=color_border, linewidths=0.8, alpha=0.95)
        ax.add_collection(pc_sel)

    # márgenes
    if xs and ys:
        xmin, xmax = min(xs), max(xs)
        ymin, ymax = min(ys), max(ys)
        dx = (xmax - xmin) * 0.05
        dy = (ymax - ymin) * 0.05
        ax.set_xlim(xmin - dx, xmax + dx)
        ax.set_ylim(ymin - dy, ymax + dy)

    buf = io.BytesIO()
    if background is None:
        fig.patch.set_alpha(0.0)
        ax.patch.set_alpha(0.0)
        plt.savefig(buf, format="png", bbox_inches="tight", pad_inches=0.1, transparent=True)
    else:
        fig.patch.set_facecolor(background)
        ax.set_facecolor(background)
        plt.savefig(buf, format="png", bbox_inches="tight", pad_inches=0.1)
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()

def export_csv_names(names: Iterable[str]) -> bytes:
    import pandas as pd
    df = pd.DataFrame({"region": list(names)})
    return df.to_csv(index=False).encode("utf-8")


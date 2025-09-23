from __future__ import annotations

from pathlib import Path
import io
import json
from typing import Iterable, List, Tuple, Optional, Dict, Set

import folium
from folium import GeoJson


# ============ Folium → HTML ============
def _folium_to_html(m: folium.Map) -> str:
    return m.get_root().render()


# ============ Carga robusta de GeoJSON ============
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
    candidates: List[Path] = []
    candidates.append(data_dir / "peru" / f"{nivel}.json")
    candidates.append(data_dir / f"{nivel}.json")

    gadm_map = {"regiones": "gadm41_PER_1.json", "provincias": "gadm41_PER_2.json", "distritos": "gadm41_PER_3.json"}
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


# ============ Helpers de nombres ============
def _name_field_for_level(nivel: str, gj: dict | None = None) -> str:
    preferred = {"regiones": "NAME_1", "provincias": "NAME_2", "distritos": "NAME_3"}
    if gj is None:
        return preferred.get(nivel, "NAME_1")
    props0 = gj["features"][0]["properties"]
    key = preferred.get(nivel)
    if key and key in props0:
        return key
    for k in ("NAME_3", "NAME_2", "NAME_1", "NAME_0"):
        if k in props0:
            return k
    for k, v in props0.items():
        if isinstance(v, str):
            return k
    return list(props0.keys())[0]


def available_names(gj: dict, name_key: Optional[str] = None) -> List[str]:
    if name_key is None:
        name_key = _name_field_for_level("regiones", gj)
    vals = [f["properties"].get(name_key, "") for f in gj["features"]]
    return sorted({str(v).strip() for v in vals if str(v).strip()})


# ============ Índices jerárquicos ============
def build_hierarchy_indices(gj_reg: dict, gj_prov: dict, gj_dist: dict) -> dict:
    """Devuelve diccionarios para filtrar rápidamente."""
    k1 = _name_field_for_level("regiones", gj_reg)
    k2 = _name_field_for_level("provincias", gj_prov)
    k3 = _name_field_for_level("distritos", gj_dist)

    # province -> region
    prov_to_reg: Dict[str, str] = {}
    for f in gj_prov["features"]:
        p = str(f["properties"].get(k2, "")).strip()
        r = str(f["properties"].get("NAME_1", f["properties"].get(k1, ""))).strip()
        if p and r:
            prov_to_reg[p] = r

    # district -> province (+region mirror)
    dist_to_prov: Dict[str, str] = {}
    dist_to_reg: Dict[str, str] = {}
    for f in gj_dist["features"]:
        d = str(f["properties"].get(k3, "")).strip()
        p = str(f["properties"].get("NAME_2", f["properties"].get(k2, ""))).strip()
        r = str(f["properties"].get("NAME_1", "")).strip()
        if d and p:
            dist_to_prov[d] = p
        if d and r:
            dist_to_reg[d] = r

    # region -> set(provinces)
    reg_to_provs: Dict[str, Set[str]] = {}
    for p, r in prov_to_reg.items():
        reg_to_provs.setdefault(r, set()).add(p)

    # province -> set(districts)
    prov_to_dists: Dict[str, Set[str]] = {}
    for d, p in dist_to_prov.items():
        prov_to_dists.setdefault(p, set()).add(d)

    return {
        "k1": k1,
        "k2": k2,
        "k3": k3,
        "prov_to_reg": prov_to_reg,
        "dist_to_prov": dist_to_prov,
        "dist_to_reg": dist_to_reg,
        "reg_to_provs": reg_to_provs,
        "prov_to_dists": prov_to_dists,
    }


# ============ Construcción del mapa ============
def build_map(
    data_dir: Path,
    nivel: str,  # 'regiones' | 'provincias' | 'distritos' (nivel a dibujar finalmente)
    colores: dict | None,
    style: dict | None,
    seleccion: Iterable[str] | None,  # nombres del name_key correspondiente al nivel
) -> Tuple[str, List[str], dict, str]:
    """
    Devuelve: (html, seleccion_normalizada, geojson, name_field)
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
    name_key = _name_field_for_level(nivel, gj)
    sel = set(s.strip() for s in (seleccion or []) if str(s).strip())

    m = folium.Map(location=[-9.2, -75.0], zoom_start=5, tiles=None)
    if show_basemap:
        folium.TileLayer("openstreetmap", name="OSM").add_to(m)

    def style_fn(feat):
        name = str(feat["properties"].get(name_key, "")).strip()
        is_sel = name in sel if sel else False
        return {
            "color": col_border if show_borders else (col_selected if is_sel else col_fill),
            "weight": weight if show_borders else 0.0,
            "fillColor": col_selected if is_sel else col_fill,
            "fillOpacity": 0.9 if is_sel else 0.7,
        }

    tooltip_fields = [k for k in ("NAME_1", "NAME_2", "NAME_3") if k in gj["features"][0]["properties"]]
    GeoJson(
        gj,
        name=nivel.capitalize(),
        style_function=style_fn,
        tooltip=folium.GeoJsonTooltip(fields=tooltip_fields) if tooltip_fields else None,
    ).add_to(m)

    folium.LayerControl().add_to(m)
    return _folium_to_html(m), sorted(list(sel)), gj, name_key


# ============ Exportaciones ============
def _try_import_matplotlib():
    try:
        import matplotlib  # noqa
        return True
    except Exception:
        return False


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
    if not _try_import_matplotlib():
        raise RuntimeError("matplotlib no está instalado")

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Polygon
    from matplotlib.collections import PatchCollection

    sel = set(s.strip() for s in (seleccion or []) if str(s).strip())
    patches_sel: List[Polygon] = []
    patches_rest: List[Polygon] = []

    def add_poly(coords, is_sel: bool):
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

    if background is None:
        fig.patch.set_alpha(0.0)
        ax.patch.set_alpha(0.0)
    else:
        fig.patch.set_facecolor(background)
        ax.set_facecolor(background)

    if patches_rest:
        pc_rest = PatchCollection(patches_rest, facecolor=color_fill, edgecolor=color_border, linewidths=0.6, alpha=0.85)
        ax.add_collection(pc_rest)
    if patches_sel:
        pc_sel = PatchCollection(patches_sel, facecolor=color_selected, edgecolor=color_border, linewidths=0.8, alpha=0.95)
        ax.add_collection(pc_sel)

    if xs and ys:
        xmin, xmax = min(xs), max(xs)
        ymin, ymax = min(ys), max(ys)
        dx = (xmax - xmin) * 0.05
        dy = (ymax - ymin) * 0.05
        ax.set_xlim(xmin - dx, xmax + dx)
        ax.set_ylim(ymin - dy, ymax + dy)

    buf = io.BytesIO()
    plt.savefig(buf, format="png", bbox_inches="tight", pad_inches=0.1, transparent=(background is None))
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()


def export_csv_names(names: Iterable[str], header: str = "nombre") -> bytes:
    import pandas as pd
    df = pd.DataFrame({header: list(names)})
    return df.to_csv(index=False).encode("utf-8")

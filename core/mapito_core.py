# core/mapito_core.py
# -------------------------------------------------------------
# Núcleo de Mapito (Perú) para Streamlit.
# Expone:
#   - build_map(data_dir, nivel, sel_color, **opciones) -> (html:str, seleccion:dict)
#   - export_png(html:str, width:int=1400, height:int=900, transparent:bool=True) -> Optional[bytes]
#
# Requiere: folium, branca
# (Opcional para exportar PNG directamente desde HTML: imgkit + wkhtmltoimage instalados)
# -------------------------------------------------------------

from __future__ import annotations
import json
import os
from functools import lru_cache
from typing import Callable, Dict, Optional, Set, Tuple

import folium
from folium.features import GeoJsonTooltip

# -------------------- Carga GeoJSON (cacheada) -------------------- #

@lru_cache(maxsize=1)
def _load_geo1(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

@lru_cache(maxsize=1)
def _load_geo2(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

@lru_cache(maxsize=1)
def _load_geo3(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def _bbox_of(gj: dict) -> Tuple[Tuple[float, float], Tuple[float, float]]:
    """Calcula bounds (latlon) simples para ajustar el mapa."""
    # Intento: usar 'bbox' si existe
    if "bbox" in gj and isinstance(gj["bbox"], (list, tuple)) and len(gj["bbox"]) == 4:
        minx, miny, maxx, maxy = gj["bbox"]
        return (miny, minx), (maxy, maxx)

    # Fallback: recorrer coordenadas (puede ser más lento, pero seguro)
    minlat =  90.0
    minlon = 180.0
    maxlat = -90.0
    maxlon = -180.0

    def _walk_coords(geom):
        nonlocal minlat, minlon, maxlat, maxlon
        t = geom.get("type")
        coords = geom.get("coordinates")
        if not t or coords is None:
            return
        if t == "Point":
            lon, lat = coords
            minlat = min(minlat, lat); maxlat = max(maxlat, lat)
            minlon = min(minlon, lon); maxlon = max(maxlon, lon)
        elif t in ("MultiPoint", "LineString"):
            for lon, lat in coords:
                minlat = min(minlat, lat); maxlat = max(maxlat, lat)
                minlon = min(minlon, lon); maxlon = max(maxlon, lon)
        elif t in ("MultiLineString", "Polygon"):
            for ring in coords:
                for lon, lat in ring:
                    minlat = min(minlat, lat); maxlat = max(maxlat, lat)
                    minlon = min(minlon, lon); maxlon = max(maxlon, lon)
        elif t == "MultiPolygon":
            for poly in coords:
                for ring in poly:
                    for lon, lat in ring:
                        minlat = min(minlat, lat); maxlat = max(maxlat, lat)
                        minlon = min(minlon, lon); maxlon = max(maxlon, lon)

    for feat in gj.get("features", []):
        geom = feat.get("geometry") or {}
        _walk_coords(geom)

    return (minlat, minlon), (maxlat, maxlon)

# -------------------- Estilos -------------------- #

def _style_factory(
    fill_color: str,
    border_color: str,
    weight: float,
    show_edges: bool,
) -> Callable:
    def _style(_):
        return {
            "fillColor": fill_color,
            "color": border_color if show_edges else fill_color,
            "weight": weight if show_edges else 0,
            "fillOpacity": 1.0,
            "opacity": 1.0,
        }
    return _style

def _style_selected(sel_color: str, border_color: str, weight: float) -> Callable:
    def _style(_):
        return {
            "fillColor": sel_color,
            "color": border_color,
            "weight": weight,
            "fillOpacity": 1.0,
            "opacity": 1.0,
        }
    return _style

# -------------------- Filtros -------------------- #

def _make_filter(
    nivel: str,
    filtros: Dict[str, Set[str]] | None,
) -> Callable[[dict], bool]:
    """
    Devuelve función booleana que decide si una feature pasa el filtro.
    filtros puede traer sets en:
      - "regiones": IDs o nombres (ID_1 / NAME_1)
      - "provincias": IDs o nombres (ID_2 / NAME_2)
      - "distritos": IDs o nombres (ID_3 / NAME_3)
    """
    filtros = filtros or {}
    regs: Set[str] = set(map(str, filtros.get("regiones", set())))
    provs: Set[str] = set(map(str, filtros.get("provincias", set())))
    dists: Set[str] = set(map(str, filtros.get("distritos", set())))

    def _ok(feat: dict) -> bool:
        p = feat.get("properties", {})
        if nivel == "regiones":
            if not regs:
                return True
            return (str(p.get("ID_1")) in regs) or (str(p.get("NAME_1")) in regs)
        if nivel == "provincias":
            # si hay regiones restringimos por región
            if regs and not ((str(p.get("ID_1")) in regs) or (str(p.get("NAME_1")) in regs)):
                return False
            if not provs:
                return True
            return (str(p.get("ID_2")) in provs) or (str(p.get("NAME_2")) in provs)
        if nivel == "distritos":
            if regs and not ((str(p.get("ID_1")) in regs) or (str(p.get("NAME_1")) in regs)):
                return False
            if provs and not ((str(p.get("ID_2")) in provs) or (str(p.get("NAME_2")) in provs)):
                return False
            if not dists:
                return True
            return (str(p.get("ID_3")) in dists) or (str(p.get("NAME_3")) in dists)
        # Lima/Callao
        if nivel == "lima_callao":
            return str(p.get("NAME_1")) in {"Lima", "Callao"}
        return True

    return _ok

# -------------------- Render de capas -------------------- #

def _tooltip_for(nivel: str) -> GeoJsonTooltip:
    if nivel == "regiones":
        fields = ["NAME_1"]; aliases = ["Región:"]
    elif nivel == "provincias":
        fields = ["NAME_1", "NAME_2"]; aliases = ["Región:", "Provincia:"]
    else:
        # distritos / lima_callao
        fields = ["NAME_1", "NAME_2", "NAME_3"]
        aliases = ["Región:", "Provincia:", "Distrito:"]
    # En folium, fields y aliases DEBEN tener la misma longitud
    return GeoJsonTooltip(fields=fields, aliases=aliases, sticky=False)

def _render_layer(
    m: folium.Map,
    gj: dict,
    name: str,
    nivel: str,
    ok: Callable[[dict], bool],
    style_all: Callable,
    style_sel: Callable,
) -> Dict[str, int]:
    """
    Dibuja una capa. Devuelve un resumen de selección:
      {"total": X, "pintados": Y}
    """
    total = 0
    pintados = 0

    def _sf(feat):
        nonlocal total, pintados
        total += 1
        if ok(feat):
            pintados += 1
            return style_sel(feat)
        return style_all(feat)

    folium.GeoJson(
        gj,
        name=name,
        style_function=_sf,
        tooltip=_tooltip_for(nivel)
    ).add_to(m)

    return {"total": total, "pintados": pintados}

# -------------------- API principal -------------------- #

def build_map(
    data_dir: str,
    nivel: str,
    sel_color: str,
    *,
    base_color: str = "#e5e7eb",
    border_color: str = "#000000",
    border_weight: float = 1.2,
    show_edges: bool = True,
    show_base_map: bool = False,
    filtros: Dict[str, Set[str]] | None = None,
) -> Tuple[str, Dict[str, Dict[str, int]]]:
    """
    Construye el mapa y devuelve:
      (html_render:str, seleccion_por_capa:dict)
    niveles soportados: "regiones", "provincias", "distritos", "lima_callao"
    """
    # Rutas a los geojson
    g1 = os.path.join(data_dir, "gadm41_PER_1.json")
    g2 = os.path.join(data_dir, "gadm41_PER_2.json")
    g3 = os.path.join(data_dir, "gadm41_PER_3.json")

    gj1 = _load_geo1(g1)
    gj2 = _load_geo2(g2)
    gj3 = _load_geo3(g3)

    # Mapa base
    tiles = "CartoDB positron" if show_base_map else None
    m = folium.Map(
        location=[-9.1, -75.1],
        zoom_start=5,
        tiles=tiles,
        control_scale=True,
        prefer_canvas=True,
    )

    # Ajustar bounds al país (usamos regiones)
    sw, ne = _bbox_of(gj1)
    try:
        m.fit_bounds([sw, ne])
    except Exception:
        pass

    ok = _make_filter(nivel, filtros)
    style_all = _style_factory(base_color, border_color, border_weight, show_edges)
    style_sel = _style_selected(sel_color, border_color, border_weight)

    resumen: Dict[str, Dict[str, int]] = {}

    if nivel == "regiones":
        resumen["Regiones"] = _render_layer(m, gj1, "Regiones", "regiones", ok, style_all, style_sel)
    elif nivel == "provincias":
        resumen["Provincias"] = _render_layer(m, gj2, "Provincias", "provincias", ok, style_all, style_sel)
    elif nivel == "distritos":
        resumen["Distritos"] = _render_layer(m, gj3, "Distritos", "distritos", ok, style_all, style_sel)
    elif nivel == "lima_callao":
        # Solo distritos de Lima/Callao
        ok_lc = _make_filter("lima_callao", filtros)
        resumen["Lima/Callao"] = _render_layer(m, gj3, "Lima/Callao", "distritos", ok_lc, style_all, style_sel)
    else:
        # fallback: regiones
        resumen["Regiones"] = _render_layer(m, gj1, "Regiones", "regiones", ok, style_all, style_sel)

    # Control de capas si hay tiles
    folium.LayerControl(collapsed=True).add_to(m)

    # HTML final
    html = m.get_root().render()
    return html, resumen

# -------------------- Exportar PNG (opcional) -------------------- #

def export_png(
    html: str,
    width: int = 1400,
    height: int = 900,
    transparent: bool = True,
) -> Optional[bytes]:
    """
    Intenta convertir HTML -> PNG usando imgkit (si está instalado y tienes wkhtmltoimage).
    Si no se puede, devuelve None (la app debe manejar ese caso y mostrar un aviso).
    """
    try:
        import imgkit  # type: ignore
    except Exception:
        return None

    options = {
        "format": "png",
        "width": str(width),
        "height": str(height),
        "encoding": "UTF-8",
        "quiet": "",
    }
    # Transparencia (cuando wkhtmltoimage lo respeta)
    if transparent:
        options["transparent"] = ""

    try:
        png_bytes = imgkit.from_string(html, False, options=options)
        return png_bytes if isinstance(png_bytes, (bytes, bytearray)) else None
    except Exception:
        return None

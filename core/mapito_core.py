# core/mapito_core.py
from __future__ import annotations

from pathlib import Path
import json
from typing import Iterable, Tuple, Dict, List, Any, Optional

import folium
from folium import GeoJson


# ───────────────────────────── Helpers ─────────────────────────────

def _load_gadm(data_dir: Path, level: int) -> dict:
    """
    Carga GADM para Perú:
      level=1 -> regiones   (gadm41_PER_1.json)
      level=2 -> provincias (gadm41_PER_2.json)
      level=3 -> distritos  (gadm41_PER_3.json)
    """
    fname = {
        1: "gadm41_PER_1.json",
        2: "gadm41_PER_2.json",
        3: "gadm41_PER_3.json",
    }[level]
    p = data_dir / fname
    if not p.exists():
        raise FileNotFoundError(f"No existe {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def _props(f: dict) -> dict:
    return f.get("properties", {})


def _filter_fc(fc: dict, keep: Iterable[bool]) -> dict:
    feats = [f for f, k in zip(fc["features"], keep) if k]
    return {"type": "FeatureCollection", "features": feats}


def _match_names(props: dict, n1: Optional[str], n2: Optional[str], n3: Optional[str]) -> bool:
    ok = True
    if n1 is not None:
        ok = ok and str(props.get("NAME_1", "")).strip().lower() == n1
    if n2 is not None:
        ok = ok and str(props.get("NAME_2", "")).strip().lower() == n2
    if n3 is not None:
        ok = ok and str(props.get("NAME_3", "")).strip().lower() == n3
    return ok


def _to_lower_safe(x: str) -> str:
    return (x or "").strip().lower()


def _bounds_from_fc(fc: dict) -> Optional[List[List[float]]]:
    """
    Bounding box aproximado de un FeatureCollection (lat, lon).
    Para simplicidad, usamos bounds de folium al añadir y luego lo leemos.
    Retorna None si no hay features.
    """
    if not fc["features"]:
        return None
    # Hacemos una capa temporal en un mapa en memoria para que folium calcule bounds.
    tmp_map = folium.Map(location=[-9.2, -75.0], zoom_start=5, tiles=None)
    gj = GeoJson(fc)
    gj.add_to(tmp_map)
    b = gj.get_bounds()  # [[lat_min, lon_min], [lat_max, lon_max]]
    return b


# ───────────────────────────── Núcleo ─────────────────────────────

def build_map(
    data_dir: Path,
    *,
    colores: Dict[str, str] | None = None,
    style: Dict[str, Any] | None = None,
    selections: Dict[str, Any] | None = None,
    fit_selected: bool = False,
    background_color: str = "#ffffff",
) -> Tuple[str, Dict[str, Any]]:
    """
    Renderiza un mapa folium con selección jerárquica.
    Parámetros:
      - colores: {"fill": "#713030", "selected": "#5F48C6", "border": "#000000"}
      - style:   {"weight": 0.8, "show_borders": True, "show_basemap": True}
      - selections: {
            "regions":   [NAME_1, ...]                            (lowercase)
            "provinces": [(NAME_1, NAME_2), ...]                  (lowercase)
            "districts": [(NAME_1, NAME_2, NAME_3), ...]          (lowercase)
        }
      - fit_selected: si True, centra/ajusta la vista a lo seleccionado
      - background_color: color de fondo del contenedor del mapa (cuando no hay tiles)
    Retorna:
      (html, meta) donde meta incluye contadores: {"n_regions":..,"n_provinces":..,"n_districts":..}
    """
    colores = colores or {}
    style = style or {}
    selections = selections or {}

    col_fill = colores.get("fill", "#713030")
    col_selected = colores.get("selected", "#5F48C6")
    col_border = colores.get("border", "#000000")
    weight = float(style.get("weight", 0.8))
    show_borders = bool(style.get("show_borders", True))
    show_basemap = bool(style.get("show_basemap", True))

    sel_regions: List[str] = [*map(_to_lower_safe, selections.get("regions", []) or [])]
    sel_prov: List[Tuple[str, str]] = [
        (_to_lower_safe(a), _to_lower_safe(b)) for (a, b) in (selections.get("provinces") or [])
    ]
    sel_dist: List[Tuple[str, str, str]] = [
        (_to_lower_safe(a), _to_lower_safe(b), _to_lower_safe(c))
        for (a, b, c) in (selections.get("districts") or [])
    ]

    # Carga de GADM
    gj1 = _load_gadm(data_dir, 1)  # regiones
    gj2 = _load_gadm(data_dir, 2)  # provincias
    gj3 = _load_gadm(data_dir, 3)  # distritos

    # Qué pinto con "fill" (general) y qué con "selected"
    general_fc: dict
    selected_fc: dict | None = None

    if sel_dist:  # distritos seleccionados
        # selected -> distritos exactos
        keep_sel = [
            _match_names(_props(f), n1, n2, n3) for (f) in gj3["features"]
            for (n1, n2, n3) in [(_to_lower_safe(_props(f).get("NAME_1")),
                                  _to_lower_safe(_props(f).get("NAME_2")),
                                  _to_lower_safe(_props(f).get("NAME_3")))]
        ]  # placeholder; lo reemplazaremos con set para O(1):
        wanted_dist = set(sel_dist)
        keep_sel = []
        for f in gj3["features"]:
            p = _props(f)
            k = (_to_lower_safe(p.get("NAME_1")),
                 _to_lower_safe(p.get("NAME_2")),
                 _to_lower_safe(p.get("NAME_3")))
            keep_sel.append(k in wanted_dist)
        selected_fc = _filter_fc(gj3, keep_sel)

        # general -> provincias contenedoras
        prov_needed = set((a, b) for (a, b, _) in sel_dist)
        keep_gen = []
        for f in gj2["features"]:
            p = _props(f)
            k = (_to_lower_safe(p.get("NAME_1")), _to_lower_safe(p.get("NAME_2")))
            keep_gen.append(k in prov_needed)
        general_fc = _filter_fc(gj2, keep_gen)

    elif sel_prov:  # provincias seleccionadas
        # selected -> provincias exactas
        wanted_prov = set(sel_prov)
        keep_sel = []
        for f in gj2["features"]:
            p = _props(f)
            k = (_to_lower_safe(p.get("NAME_1")), _to_lower_safe(p.get("NAME_2")))
            keep_sel.append(k in wanted_prov)
        selected_fc = _filter_fc(gj2, keep_sel)

        # general -> regiones contenedoras
        regions_needed = set(a for (a, _) in sel_prov)
        keep_gen = []
        for f in gj1["features"]:
            p = _props(f)
            k = _to_lower_safe(p.get("NAME_1"))
            keep_gen.append(k in regions_needed)
        general_fc = _filter_fc(gj1, keep_gen)

    elif sel_regions:  # solo regiones
        # general -> regiones
        wanted_reg = set(sel_regions)
        keep_gen = []
        for f in gj1["features"]:
            p = _props(f)
            k = _to_lower_safe(p.get("NAME_1"))
            keep_gen.append(k in wanted_reg)
        general_fc = _filter_fc(gj1, keep_gen)
        selected_fc = None

    else:
        # Nada seleccionado: muestro todo Perú (regiones)
        general_fc = gj1
        selected_fc = None

    # Construcción del mapa
    m = folium.Map(location=[-9.2, -75.0], zoom_start=5, tiles=None)
    if show_basemap:
        folium.TileLayer("openstreetmap", name="OSM").add_to(m)

    # Fondo del contenedor del mapa
    style_tag = f"<style>.folium-map {{ background: {background_color}; }}</style>"
    m.get_root().html.add_child(folium.Element(style_tag))

    def _style_general(_):
        return {
            "color": col_border if show_borders else col_fill,
            "weight": weight if show_borders else 0.0,
            "fillColor": col_fill,
            "fillOpacity": 0.85,
        }

    def _style_selected(_):
        return {
            "color": col_border if show_borders else col_selected,
            "weight": weight if show_borders else 0.0,
            "fillColor": col_selected,
            "fillOpacity": 0.95,
        }

    # Tooltips dinámicos
    def _fields_for(fc: dict) -> List[str]:
        if not fc["features"]:
            return []
        props = fc["features"][0]["properties"]
        return [k for k in ("NAME_1", "NAME_2", "NAME_3") if k in props]

    if general_fc and general_fc["features"]:
        GeoJson(
            general_fc,
            name="General",
            style_function=_style_general,
            tooltip=folium.GeoJsonTooltip(fields=_fields_for(general_fc)),
        ).add_to(m)

    if selected_fc and selected_fc["features"]:
        GeoJson(
            selected_fc,
            name="Seleccionado",
            style_function=_style_selected,
            tooltip=folium.GeoJsonTooltip(fields=_fields_for(selected_fc)),
        ).add_to(m)

    folium.LayerControl(collapsed=True).add_to(m)

    # Ajuste de vista
    if fit_selected:
        fc_to_fit = selected_fc if (selected_fc and selected_fc["features"]) else general_fc
        bounds = _bounds_from_fc(fc_to_fit)
        if bounds:
            m.fit_bounds(bounds)

    meta = {
        "n_regions": len(general_fc["features"]) if general_fc else 0,
        "n_selected": len(selected_fc["features"]) if (selected_fc and selected_fc.get("features")) else 0,
    }
    return m.get_root().render(), meta

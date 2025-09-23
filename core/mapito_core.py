# core/mapito_core.py
# Versión estable de Mapito: genera mapas Folium con tooltips seguros.

from typing import Tuple, Optional, Dict
import json
import pathlib

import folium
from folium import GeoJson
from folium.features import GeoJsonTooltip

# Carga GeoJSON desde /data
# Estructura esperada:
#   data/
#     peru_regiones.geojson
#     peru_provincias.geojson
#     peru_distritos.geojson
#     lima_callao.geojson

NOMBRE_ARCHIVOS = {
    "regiones": "peru_regiones.geojson",
    "provincias": "peru_provincias.geojson",
    "distritos": "peru_distritos.geojson",
    "lima_callao": "lima_callao.geojson",
}

def _load_geojson(path: pathlib.Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)

def _default_center() -> Tuple[float, float]:
    # Centro aproximado de Perú
    return (-9.19, -75.015)

def _tooltip_cols(props: dict) -> Tuple[list, list]:
    """
    Devuelve (fields, aliases) según las keys disponibles.
    Evita errores por longitud distinta.
    """
    posibles = [("NAME_1", "Región"), ("NAME_2", "Provincia"), ("NAME_3", "Distrito")]
    fields, aliases = [], []
    for key, alias in posibles:
        if key in props:
            fields.append(key)
            aliases.append(alias + ":")
    if not fields:
        # Al menos una key cualquiera
        any_key = next(iter(props.keys()))
        fields = [any_key]
        aliases = ["Nombre:"]
    return fields, aliases

def build_map(
    data_dir: pathlib.Path,
    nivel: str,
    color_general: str = "#BEBEBE",
    color_selected: str = "#5F48C6",
    color_border: str = "#000000",
    border_weight: float = 0.8,
    show_borders: bool = True,
    filtros: Optional[Dict[str, set]] = None,
) -> Tuple[str, dict]:
    """
    Construye y devuelve (html, seleccion). 'seleccion' se deja como dict vacío para mantener firma.
    """
    fname = NOMBRE_ARCHIVOS.get(nivel)
    if not fname:
        raise ValueError(f"Nivel desconocido: {nivel}")

    gj_path = data_dir / fname
    if not gj_path.exists():
        # Si falta el archivo, devolvemos un mapa vacío con mensaje
        m = folium.Map(location=_default_center(), zoom_start=5, tiles="cartodbpositron")
        folium.Marker(_default_center(), tooltip="GeoJSON no encontrado").add_to(m)
        return m.get_root().render(), {}

    gj = _load_geojson(gj_path)

    m = folium.Map(location=_default_center(), zoom_start=5, tiles="cartodbpositron")

    def style_fn(_):
        return {"fillColor": color_general, "color": color_border if show_borders else color_general,
                "weight": border_weight, "fillOpacity": 0.8}

    def highlight_fn(_):
        return {"fillColor": color_selected, "color": color_border, "weight": border_weight + 0.2, "fillOpacity": 0.9}

    # Tooltip seguro
    # Determinamos fields/aliases de la PRIMERA feature
    first_props = gj["features"][0]["properties"] if gj["features"] else {}
    fields, aliases = _tooltip_cols(first_props)

    GeoJson(
        gj,
        name="layer",
        style_function=style_fn,
        highlight_function=highlight_fn,
        tooltip=GeoJsonTooltip(fields=fields, aliases=aliases, sticky=False),
    ).add_to(m)

    html = m.get_root().render()
    return html, {}


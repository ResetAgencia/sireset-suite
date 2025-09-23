# core/mougli_core.py
# Versión estable: la función acepta factores=None y usa valores por defecto.

import io
from typing import Optional, Dict, Any

import pandas as pd

DEFAULT_FACTORES = {
    "tv": 0.26,
    "cable": 0.42,
    "radio": 0.42,
    "revista": 0.15,
    "diarios": 0.15,
}

def _leer_monitor_txt(file) -> pd.DataFrame:
    # Implementación mínima: ajusta a tu formato real
    # Asume archivo de texto separado por tabulaciones/espacios; adapta si es CSV.
    # Si tu formato es diferente, cambia esta función, pero mantén la firma externa.
    try:
        df = pd.read_csv(file, sep="\t", engine="python")
    except Exception:
        file.seek(0)
        df = pd.read_csv(file, sep=";", engine="python")
    return df

def _resumen_basico(m_df: pd.DataFrame, o_df: Optional[pd.DataFrame]) -> Dict[str, Any]:
    res = {
        "archivos_monitor": 1 if m_df is not None else 0,
        "archivos_outview": 1 if o_df is not None else 0,
        "filas_monitor": int(len(m_df)) if m_df is not None else 0,
        "filas_outview": int(len(o_df)) if o_df is not None else 0,
        "tiene_consolidado": bool(o_df is not None),
    }
    return res

def procesar_monitor_outview(
    monitor_file,
    outview_df: Optional[pd.DataFrame] = None,
    factores: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """
    Procesa Monitor + OutView. Soporta factores=None (usa DEFAULT_FACTORES).
    Retorna: dict con 'resumen' y 'excel_bytes' (para descargar).
    """
    if factores is None:
        factores = DEFAULT_FACTORES.copy()

    # Lee monitor
    m_df = _leer_monitor_txt(monitor_file)

    # Si hay OutView, ya viene como DataFrame
    o_df = outview_df

    # Aquí harías tu lógica real de Mougli (aplicar factores, joins, etc.)
    # Para dejarlo estable, metemos una columna de ejemplo con factor TV:
    m_proc = m_df.copy()
    if "monto" in m_proc.columns:
        m_proc["monto_ajustado_tv"] = m_proc["monto"] * factores.get("tv", DEFAULT_FACTORES["tv"])

    # Resumen
    resumen = _resumen_basico(m_proc, o_df)

    # Generamos Excel con hojas “Monitor” (+ OutView si hay)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        m_proc.to_excel(writer, index=False, sheet_name="Monitor")
        if o_df is not None:
            o_df.to_excel(writer, index=False, sheet_name="OutView")
    excel_bytes = output.getvalue()

    return {"resumen": resumen, "excel_bytes": excel_bytes}

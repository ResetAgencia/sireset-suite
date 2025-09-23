import io
from io import BytesIO
from typing import Dict, List, Tuple
import pandas as pd
import numpy as np


# =========================
#  LECTURA ROBUSTA ARCHIVOS
# =========================

def _decode_bytes(b: bytes) -> str:
    """Intenta decodificar en utf-8, latin-1, cp1252."""
    for enc in ("utf-8", "latin-1", "cp1252"):
        try:
            return b.decode(enc)
        except Exception:
            pass
    raise ValueError("No fue posible decodificar el TXT (probé utf-8, latin-1, cp1252).")


def _read_txt_robusto(file) -> pd.DataFrame:
    """
    Lee un .txt buscando separadores comunes: \t ; , |
    Retorna un DataFrame (si falla, DataFrame vacío).
    """
    if file is None:
        return pd.DataFrame()

    raw = file.read()
    text = _decode_bytes(raw) if isinstance(raw, (bytes, bytearray)) else raw
    buf = io.StringIO(text)

    # probamos separadores típicos
    seps = ["\t", ";", ",", "|"]
    for sep in seps:
        buf.seek(0)
        try:
            df = pd.read_csv(buf, sep=sep, engine="python")
            # válido si tiene al menos 1 columna y 1 fila
            if df.shape[1] >= 1 and len(df) >= 1:
                return df
        except Exception:
            continue

    # último intento: una línea por registro
    lines = [l for l in text.splitlines() if l.strip()]
    return pd.DataFrame({"linea": lines})


def _read_out_robusto(file) -> pd.DataFrame:
    """Lee CSV/XLSX de OutView."""
    if file is None:
        return pd.DataFrame()
    name = file.name.lower()
    try:
        if name.endswith(".csv"):
            return pd.read_csv(file)
        return pd.read_excel(file)
    except Exception:
        # fallback por si tiene separador ; o latin-1
        file.seek(0)
        try:
            return pd.read_csv(file, sep=";", encoding="latin-1")
        except Exception:
            file.seek(0)
            return pd.read_excel(file)


# ==================================
#  APLICACIÓN DE FACTORES (si aplica)
# ==================================

_NUMERIC_CANDIDATES = ["Valor", "Inversion", "Puntos", "GRP", "Cantidad", "Importe", "Monto"]

def _col_numerica(df: pd.DataFrame) -> str | None:
    for c in _NUMERIC_CANDIDATES:
        if c in df.columns and pd.api.types.is_numeric_dtype(df[c]):
            return c
    # si no encuentra, prueba la 1ra numérica
    for c in df.columns:
        if pd.api.types.is_numeric_dtype(df[c]):
            return c
    return None

def _aplicar_factores(df: pd.DataFrame, factores: Dict[str, float]) -> pd.DataFrame:
    """
    Si existe columna 'Medio' y alguna columna numérica (ej. 'Valor'),
    crea 'Valor_ajustado' = valor * factor[Medio] (si existe).
    """
    if df.empty or not isinstance(factores, dict) or "Medio" not in df.columns:
        return df

    col_val = _col_numerica(df)
    if not col_val:
        return df

    def _fx(medio: str) -> float:
        m = str(medio or "").strip().upper()
        # normaliza claves típicas
        map_norm = {
            "TV": "TV", "TELEVISION": "TV",
            "CABLE": "CABLE",
            "RADIO": "RADIO",
            "REVISTA": "REVISTA", "REVISTAS": "REVISTA",
            "DIARIO": "DIARIOS", "DIARIOS": "DIARIOS", "PRENSA": "DIARIOS",
        }
        key = map_norm.get(m, None)
        return float(factores.get(key, 1.0)) if key else 1.0

    df = df.copy()
    df["Valor_ajustado"] = df.apply(
        lambda r: (r[col_val] * _fx(r.get("Medio"))) if pd.notnull(r.get("Medio")) and pd.notnull(r.get(col_val)) else r.get(col_val),
        axis=1,
    )
    return df


# ==========================
#  RESÚMENES Y CONSOLIDACIÓN
# ==========================

_BRAND_CANDS = ["Marca", "Anunciante", "Brand", "Cliente", "Advertiser"]
_DATE_CANDS  = ["Fecha", "DATE", "Date", "FECHA"]

def _find_first_column(df: pd.DataFrame, candidates: List[str]) -> str | None:
    for c in candidates:
        if c in df.columns:
            return c
    return None

def _date_range(df: pd.DataFrame) -> Tuple[str, str] | Tuple[None, None]:
    col = _find_first_column(df, _DATE_CANDS)
    if not col:
        return (None, None)
    s = pd.to_datetime(df[col], errors="coerce", dayfirst=True)
    if s.notna().any():
        return (s.min().date().isoformat(), s.max().date().isoformat())
    return (None, None)

def _brands_count(df: pd.DataFrame) -> int | None:
    col = _find_first_column(df, _BRAND_CANDS)
    if not col:
        return None
    return int(df[col].dropna().astype(str).nunique())

def resumen_mougli(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame([{"Filas": 0, "Rango de fechas": "", "Marcas / Anunciantes": 0}])

    d1, d2 = _date_range(df)
    rdate = f"{d1} - {d2}" if d1 and d2 else ""
    b = _brands_count(df) or 0
    return pd.DataFrame([{
        "Filas": len(df),
        "Rango de fechas": rdate,
        "Marcas / Anunciantes": b,
    }])


# Keys comunes para intentar hacer merge
_JOIN_CANDS = ["Marca", "Anunciante", "Brand", "Cliente", "Producto", "Categoria", "Fecha"]

def _join_keys(df1: pd.DataFrame, df2: pd.DataFrame) -> List[str]:
    common = [c for c in _JOIN_CANDS if (c in df1.columns and c in df2.columns)]
    # al menos 1, o ninguno
    return common

def _consolidar(df_m: pd.DataFrame, df_o: pd.DataFrame) -> pd.DataFrame:
    if df_m.empty or df_o.empty:
        return pd.DataFrame()

    keys = _join_keys(df_m, df_o)
    if not keys:
        # sin claves comunes, no consolidamos
        return pd.DataFrame()

    # nos aseguramos de no duplicar columnas
    return df_m.merge(df_o, how="left", on=keys, suffixes=("_m", "_o"))


# ==========================
#  FUNCIÓN PRINCIPAL + EXCEL
# ==========================

def procesar_monitor_outview(monitor_file, out_file, factores: Dict[str, float]):
    """
    Lee y procesa Monitor y OutView.
    - Aplica factores a Monitor (si hay 'Medio' + columna numérica).
    - Devuelve df_consolidado y Excel con hojas: 'Monitor', 'OutView', 'Consolidado' y 'Resumen'.
    """
    # 1) leer
    df_m = _read_txt_robusto(monitor_file)
    df_o = _read_out_robusto(out_file)

    # 2) aplicar factores
    df_m = _aplicar_factores(df_m, factores or {})

    # 3) consolidar si procede
    df_c = _consolidar(df_m, df_o)

    # 4) armar excel
    xlsx = BytesIO()
    with pd.ExcelWriter(xlsx, engine="xlsxwriter") as writer:
        if not df_m.empty:
            df_m.to_excel(writer, index=False, sheet_name="Monitor")
        if not df_o.empty:
            df_o.to_excel(writer, index=False, sheet_name="OutView")
        if not df_c.empty:
            df_c.to_excel(writer, index=False, sheet_name="Consolidado")

        # Resumen (como en la app de escritorio, uno por lado)
        resum_m = resumen_mougli(df_m)
        resum_o = resumen_mougli(df_o)

        # para que se vea “tablero” en Excel
        resum_m.insert(0, "Fuente", "Monitor")
        resum_o.insert(0, "Fuente", "OutView")
        resumen_excel = pd.concat([resum_m, resum_o], ignore_index=True)
        resumen_excel.to_excel(writer, index=False, sheet_name="Resumen")

        # formatitos mínimos
        wb = writer.book
        fmt = wb.add_format({"text_wrap": True, "valign": "vcenter"})
        for sh in ("Monitor", "OutView", "Consolidado", "Resumen"):
            if sh in writer.sheets:
                ws = writer.sheets[sh]
                ws.set_column(0, 0, 18, fmt)
                ws.set_column(1, 50, 18, fmt)

    xlsx.seek(0)

    # Qué devolvemos a la app:
    # - df_resultado (prioriza el consolidado; si no hay, el monitor)
    df_resultado = df_c if not df_c.empty else df_m
    return df_resultado, xlsx


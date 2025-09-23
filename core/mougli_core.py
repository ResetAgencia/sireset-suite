import io
from io import BytesIO
from typing import Dict, List, Tuple
import pandas as pd
import numpy as np


# =========================
#  UTIL: decodificación TXT
# =========================
def _decode_bytes(b: bytes) -> str:
    for enc in ("utf-8-sig", "latin-1", "cp1252"):
        try:
            return b.decode(enc)
        except Exception:
            pass
    raise ValueError("No fue posible decodificar el TXT (probé utf-8-sig, latin-1, cp1252).")


# ==================================================
#  LECTOR ESPECÍFICO DE MONITOR (como el “básico”)
# ==================================================
def _read_monitor_txt(file) -> pd.DataFrame:
    """
    Lee el .txt de Monitor buscando la fila donde aparece la cabecera real
    con pipes (ej.: '#|MEDIO|DIA|MARCA|...'). A partir de allí parsea con sep='|'.
    Limpia la primera columna '#' si existe y normaliza campos clave.
    """
    if file is None:
        return pd.DataFrame()

    # Streamlit UploadedFile tiene .read() y .seek()
    raw = file.read()
    text = _decode_bytes(raw) if isinstance(raw, (bytes, bytearray)) else raw
    lines = text.splitlines()

    # Fila de cabecera: donde aparezca '|MEDIO|' en los primeros 60 renglones
    hdr_idx = None
    for i, l in enumerate(lines[:60]):
        if "|MEDIO|" in l.upper():
            hdr_idx = i
            break
    if hdr_idx is None:
        # Si no encuentro cabecera "formal", devuelvo líneas crudas para depurar
        return pd.DataFrame({"linea": [l for l in lines if l.strip()]})

    # Leemos desde la fila de cabecera
    buf = io.StringIO("\n".join(lines[hdr_idx:]))
    df = pd.read_csv(buf, sep="|", engine="python")

    # Normalizaciones
    df.columns = df.columns.astype(str).str.strip()
    df = df.dropna(axis=1, how="all")

    # Si la primera columna es '#' o viene vacía, la quitamos (número correlativo)
    first_col = df.columns[0]
    if first_col.strip() in {"#", ""}:
        df = df.drop(columns=[first_col])

    # Asegurar mayúsculas de nombres estándar (si vinieron en minúsculas)
    cols_up = {c: c.upper() for c in df.columns}
    df.rename(columns=cols_up, inplace=True)

    # Campos típicos
    if "DIA" in df.columns:
        df["DIA"] = pd.to_datetime(df["DIA"], format="%d/%m/%Y", errors="coerce").dt.normalize()
        df["AÑO"] = df["DIA"].dt.year
        df["MES"] = df["DIA"].dt.month
        df["SEMANA"] = df["DIA"].dt.isocalendar().week

    if "MEDIO" in df.columns:
        df["MEDIO"] = df["MEDIO"].astype(str).str.upper().str.strip()

    # Inversión a numérico si existe
    if "INVERSION" in df.columns:
        df["INVERSION"] = pd.to_numeric(df["INVERSION"], errors="coerce").fillna(0)

    # Orden: fechas primero
    order = [c for c in ["DIA", "AÑO", "MES", "SEMANA"] if c in df.columns]
    df = df[[*order] + [c for c in df.columns if c not in order]]
    return df


# ========================
#  LECTOR ROBUSTO OUTVIEW
# ========================
def _read_out_robusto(file) -> pd.DataFrame:
    if file is None:
        return pd.DataFrame()
    name = (getattr(file, "name", "") or "").lower()
    try:
        if name.endswith(".csv"):
            try:
                # primer intento: autodetección
                file.seek(0)
                return pd.read_csv(file)
            except UnicodeDecodeError:
                file.seek(0)
                return pd.read_csv(file, sep=";", encoding="latin-1")
        # Excel (xlsx/xls)
        file.seek(0)
        return pd.read_excel(file)
    except Exception:
        # Fallback CSV latino con ;
        try:
            file.seek(0)
            return pd.read_csv(file, sep=";", encoding="latin-1")
        except Exception:
            # Último recurso: Excel
            file.seek(0)
            return pd.read_excel(file)


# ==================================
#  APLICACIÓN DE FACTORES A MONITOR
# ==================================
def _aplicar_factores_monitor(df: pd.DataFrame, factores: Dict[str, float]) -> pd.DataFrame:
    """
    Igual que el básico: si existen 'MEDIO' e 'INVERSION', multiplica por el factor.
    """
    if df.empty or "MEDIO" not in df.columns or "INVERSION" not in df.columns:
        return df
    df = df.copy()

    def fx(m):
        m = (str(m) or "").upper().strip()
        mapa = {
            "TV": "TV", "TELEVISION": "TV",
            "CABLE": "CABLE",
            "RADIO": "RADIO",
            "REVISTA": "REVISTA", "REVISTAS": "REVISTA",
            "DIARIO": "DIARIOS", "DIARIOS": "DIARIOS", "PRENSA": "DIARIOS",
        }
        clave = mapa.get(m, None)
        return float(factores.get(clave, 1.0)) if clave else 1.0

    df["INVERSION"] = df.apply(lambda r: r["INVERSION"] * fx(r["MEDIO"]), axis=1)
    return df


# ==========================
#  RESÚMENES Y CONSOLIDACIÓN
# ==========================
_BRAND_CANDS = ["MARCA", "ANUNCIANTE", "BRAND", "CLIENTE"]
_DATE_MON = ["DIA"]
_DATE_OUT = ["Fecha", "FECHA"]

def _brands_count(df: pd.DataFrame, candidates: List[str]) -> int | None:
    for c in candidates:
        if c in df.columns:
            return int(df[c].dropna().astype(str).nunique())
    return None

def _date_range(df: pd.DataFrame, candidates: List[str]) -> Tuple[str, str] | Tuple[None, None]:
    for c in candidates:
        if c in df.columns:
            s = pd.to_datetime(df[c], errors="coerce", dayfirst=True)
            if s.notna().any():
                return (s.min().date().isoformat(), s.max().date().isoformat())
    return (None, None)

def resumen_mougli(df: pd.DataFrame, es_monitor: bool) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame([{"Filas": 0, "Rango de fechas": "", "Marcas / Anunciantes": 0}])
    d1, d2 = _date_range(df, _DATE_MON if es_monitor else _DATE_OUT)
    r = f"{d1} - {d2}" if d1 and d2 else ""
    b = _brands_count(df, _BRAND_CANDS) or 0
    return pd.DataFrame([{"Filas": len(df), "Rango de fechas": r, "Marcas / Anunciantes": b}])


# Consolidado: si hay claves comunes razonables
_JOIN_CANDS = ["MARCA", "ANUNCIANTE", "PRODUCTO", "CATEGORIA", "DIA", "Fecha", "FECHA"]

def _consolidar(df_m: pd.DataFrame, df_o: pd.DataFrame) -> pd.DataFrame:
    if df_m.empty or df_o.empty:
        return pd.DataFrame()
    # intentamos con un subconjunto de columnas que existan en ambos
    keys = [k for k in _JOIN_CANDS if (k in df_m.columns and k in df_o.columns)]
    if not keys:
        return pd.DataFrame()
    return df_m.merge(df_o, how="left", on=keys, suffixes=("_m", "_o"))


# ==========================
#  FUNCIÓN PRINCIPAL + EXCEL
# ==========================
def procesar_monitor_outview(monitor_file, out_file, factores: Dict[str, float]):
    """
    - Lee Monitor con el parser específico (cabecera '#|MEDIO|DIA|...')
    - Aplica factores a INVERSION por MEDIO
    - Lee OutView de forma robusta
    - Consolida si hay llaves comunes
    - Devuelve df_result y un Excel multihoja (Monitor, OutView, Consolidado, Resumen)
    """
    # MONITOR
    df_m = _read_monitor_txt(monitor_file)
    df_m = _aplicar_factores_monitor(df_m, factores or {})

    # OUTVIEW
    df_o = _read_out_robusto(out_file)

    # CONSOLIDADO
    df_c = _consolidar(df_m, df_o)

    # EXCEL
    xlsx = BytesIO()
    with pd.ExcelWriter(xlsx, engine="xlsxwriter", datetime_format="dd/mm/yyyy", date_format="dd/mm/yyyy") as w:
        if not df_m.empty:
            df_m.to_excel(w, index=False, sheet_name="Monitor")
        if not df_o.empty:
            df_o.to_excel(w, index=False, sheet_name="OutView")
        if not df_c.empty:
            df_c.to_excel(w, index=False, sheet_name="Consolidado")

        # Resumen “doble”
        rm = resumen_mougli(df_m, es_monitor=True);  rm.insert(0, "Fuente", "Monitor")
        ro = resumen_mougli(df_o, es_monitor=False); ro.insert(0, "Fuente", "OutView")
        pd.concat([rm, ro], ignore_index=True).to_excel(w, index=False, sheet_name="Resumen")

        wb = w.book
        fmt = wb.add_format({"text_wrap": True, "valign": "vcenter"})
        for sh in ("Monitor", "OutView", "Consolidado", "Resumen"):
            if sh in w.sheets:
                ws = w.sheets[sh]
                ws.set_column(0, 0, 18, fmt)
                ws.set_column(1, 60, 18, fmt)

    xlsx.seek(0)
    df_result = df_c if not df_c.empty else df_m
    return df_result, xlsx

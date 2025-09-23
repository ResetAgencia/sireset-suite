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
                file.seek(0)
                return pd.read_csv(file)
            except UnicodeDecodeError:
                file.seek(0)
                return pd.read_csv(file, sep=";", encoding="latin-1")
        file.seek(0)
        return pd.read_excel(file)
    except Exception:
        try:
            file.seek(0)
            return pd.read_csv(file, sep=";", encoding="latin-1")
        except Exception:
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
#  RESÚMENES
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


# ==========================
#  CONSOLIDADO UNIFICADO
# ==========================
_TARGET_ORDER = [
    "FECHA","AÑO","MES","SEMANA","MEDIO","MARCA","PRODUCTO","VERSIÓN",
    "DURACIÓN","TIPO ELEMENTO","TIME / Q VERSIONES","EMISORA / DISTRITO",
    "PROGRAMA / AVENIDA","BREAK / CALLE","POS. SPOT / ORIENTACIÓN",
    "INVERSIÓN REAL","SECTOR","CATEGORÍA","ÍTEM","AGENCIA","ANUNCIANTE",
    "REGIÓN","ANCHO / LATITUD","ALTO / LONGITUD","GEN / +1 SUPERFICIE",
    "Q ELEMENTOS","EDITORA / PROVEEDOR"
]

# Mapeos “suaves”: solo renombra si existe
_MONITOR_MAP = {
    "DIA":"FECHA","AÑO":"AÑO","MES":"MES","SEMANA":"SEMANA",
    "MEDIO":"MEDIO","MARCA":"MARCA","PRODUCTO":"PRODUCTO","VERSION":"VERSIÓN",
    "DURACION":"DURACIÓN","TIPO":"TIPO ELEMENTO","HORA":"TIME / Q VERSIONES",
    "EMISORA/SITE":"EMISORA / DISTRITO","PROGRAMA/TIPO DE SITE":"PROGRAMA / AVENIDA",
    "BREAK":"BREAK / CALLE","POS. SPOT":"POS. SPOT / ORIENTACIÓN",
    "INVERSION":"INVERSIÓN REAL","SECTOR":"SECTOR","CATEGORIA":"CATEGORÍA",
    "ITEM":"ÍTEM","AGENCIA":"AGENCIA","ANUNCIANTE":"ANUNCIANTE",
    "REGION/ÁMBITO":"REGIÓN","ANCHO":"ANCHO / LATITUD","ALTO":"ALTO / LONGITUD",
    "GENERO":"GEN / +1 SUPERFICIE","SPOTS":"Q ELEMENTOS","EDITORA":"EDITORA / PROVEEDOR"
}
_OUT_MAP = {
    "Fecha":"FECHA","AÑO":"AÑO","MES":"MES","SEMANA":"SEMANA","Medio":"MEDIO",
    "Marca":"MARCA","Producto":"PRODUCTO","Versión":"VERSIÓN","Duración (Seg)":"DURACIÓN",
    "Tipo Elemento":"TIPO ELEMENTO","Q versiones por elemento Mes":"TIME / Q VERSIONES",
    "Distrito":"EMISORA / DISTRITO","Avenida":"PROGRAMA / AVENIDA",
    "Nro Calle/Cuadra":"BREAK / CALLE","Orientación de Vía":"POS. SPOT / ORIENTACIÓN",
    "Tarifa Real ($)":"INVERSIÓN REAL","Sector":"SECTOR",
    "Categoría":"CATEGORÍA","Item":"ÍTEM","Agencia":"AGENCIA","Anunciante":"ANUNCIANTE",
    "Región":"REGIÓN","Latitud":"ANCHO / LATITUD","Longitud":"ALTO / LONGITUD",
    "+1 Superficie":"GEN / +1 SUPERFICIE","Conteo mensual":"Q ELEMENTOS",
    "Proveedor":"EDITORA / PROVEEDOR"
}

def _to_unified(df: pd.DataFrame, mapping: dict) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=_TARGET_ORDER)
    df = df.copy()
    # Renombrar solo las que existan
    df.rename(columns={k:v for k,v in mapping.items() if k in df.columns}, inplace=True)
    # Asegurar todas las columnas del target
    for c in _TARGET_ORDER:
        if c not in df.columns:
            df[c] = np.nan
    df = df[_TARGET_ORDER]
    # Tipos clave
    if "FECHA" in df.columns:
        df["FECHA"] = pd.to_datetime(df["FECHA"], errors="coerce").dt.date
    return df


# ==========================
#  UTIL: escribir tablas XLSX
# ==========================
def _col_letter(idx: int) -> str:
    """0 -> A, 1 -> B, ..."""
    s = ""
    n = idx
    while n >= 0:
        s = chr(n % 26 + 65) + s
        n = n // 26 - 1
    return s

def _write_sheet_with_header_and_table(writer: pd.ExcelWriter, *, sheet_name: str,
                                       df: pd.DataFrame, header_rows: List[Tuple[str, str]]):
    """
    Escribe un bloque de encabezado (2 columnas: Descripción, Valor) y debajo
    una tabla con formato Excel Table para el dataframe.
    """
    # 1) Encabezado
    header_df = pd.DataFrame(header_rows, columns=["Descripción", "Valor"])
    header_df.to_excel(writer, sheet_name=sheet_name, index=False, startrow=0)
    ws = writer.sheets[sheet_name]
    # 2) DataFrame como tabla
    start_row = len(header_df) + 2
    df = df.copy()
    df.to_excel(writer, sheet_name=sheet_name, index=False, startrow=start_row)

    nrow, ncol = df.shape
    if nrow == 0:
        # Aún creamos encabezados de tabla para consistencia
        nrow_for_table = 1
    else:
        nrow_for_table = nrow

    start_col_letter = "A"
    end_col_letter = _col_letter(ncol - 1)
    # Rango incluye fila de encabezado de columnas (+1)
    rng = f"{start_col_letter}{start_row+1}:{end_col_letter}{start_row+nrow_for_table+1}"

    ws.add_table(rng, {
        "name": f"{sheet_name.replace(' ', '_')}_tbl",
        "header_row": True,
        "style": "Table Style Medium 9",
        "columns": [{"header": str(h)} for h in df.columns]
    })
    ws.freeze_panes(start_row + 1, 0)  # fija encabezado de la tabla
    # Ancho de columnas decente
    ws.set_column(0, max(0, ncol-1), 18)


# ==========================
#  FUNCIÓN PRINCIPAL + EXCEL
# ==========================
def procesar_monitor_outview(monitor_file, out_file, factores: Dict[str, float]):
    """
    - Lee Monitor con el parser específico (cabecera '#|MEDIO|DIA|...')
    - Aplica factores a INVERSION por MEDIO
    - Lee OutView de forma robusta
    - Construye 'Consolidado' con columnas unificadas (concat de las dos fuentes)
    - Devuelve df_result y un Excel multihoja con tablas y encabezados
    """
    # MONITOR
    df_m = _read_monitor_txt(monitor_file)
    df_m = _aplicar_factores_monitor(df_m, factores or {})

    # OUTVIEW
    df_o = _read_out_robusto(out_file)

    # CONSOLIDADO (unificar columnas y concatenar lo que haya)
    mon_u = _to_unified(df_m, _MONITOR_MAP) if not df_m.empty else pd.DataFrame(columns=_TARGET_ORDER)
    out_u = _to_unified(df_o, _OUT_MAP) if not df_o.empty else pd.DataFrame(columns=_TARGET_ORDER)
    df_c = pd.concat([mon_u, out_u], ignore_index=True)
    if not df_c.empty:
        df_c.sort_values(["FECHA","MARCA"], inplace=True, na_position="last")

    # RESÚMENES
    rm = resumen_mougli(df_m, es_monitor=True);  rm.insert(0, "Fuente", "Monitor")
    ro = resumen_mougli(df_o, es_monitor=False); ro.insert(0, "Fuente", "OutView")
    resumen = pd.concat([rm, ro], ignore_index=True)

    # EXCEL
    xlsx = BytesIO()
    with pd.ExcelWriter(xlsx, engine="xlsxwriter", datetime_format="dd/mm/yyyy", date_format="dd/mm/yyyy") as w:
        # Monitor
        if not df_m.empty:
            # Encabezado
            h_m = [
                ("Filas", len(df_m)),
                ("Rango de fechas", resumen.loc[resumen["Fuente"]=="Monitor","Rango de fechas"].iat[0] if not resumen.empty else ""),
                ("Marcas / Anunciantes", int(resumen.loc[resumen["Fuente"]=="Monitor","Marcas / Anunciantes"].iat[0]) if not resumen.empty else 0)
            ]
            _write_sheet_with_header_and_table(w, sheet_name="Monitor", df=df_m, header_rows=h_m)

        # OutView
        if not df_o.empty:
            h_o = [
                ("Filas", len(df_o)),
                ("Rango de fechas", resumen.loc[resumen["Fuente"]=="OutView","Rango de fechas"].iat[0] if not resumen.empty else ""),
                ("Marcas / Anunciantes", int(resumen.loc[resumen["Fuente"]=="OutView","Marcas / Anunciantes"].iat[0]) if not resumen.empty else 0)
            ]
            _write_sheet_with_header_and_table(w, sheet_name="OutView", df=df_o, header_rows=h_o)

        # Consolidado (si hay al menos una fuente)
        if not df_c.empty:
            # Encabezado rápido
            d1, d2 = _date_range(df_c, ["FECHA"])
            h_c = [
                ("Filas", len(df_c)),
                ("Rango de fechas", f"{d1} - {d2}" if d1 and d2 else ""),
                ("Fuentes incluidas", ("Monitor" if not df_m.empty else "") + (" + " if (not df_m.empty and not df_o.empty) else "") + ("OutView" if not df_o.empty else ""))
            ]
            _write_sheet_with_header_and_table(w, sheet_name="Consolidado", df=df_c, header_rows=h_c)

        # Resumen (también como tabla)
        if not resumen.empty:
            _write_sheet_with_header_and_table(w, sheet_name="Resumen", df=resumen, header_rows=[("Notas","Resumen por fuente")])

        # Ajustes visuales globales
        wb = w.book
        fmt = wb.add_format({"text_wrap": True, "valign": "vcenter"})
        for sh in ("Monitor", "OutView", "Consolidado", "Resumen"):
            if sh in w.sheets:
                ws = w.sheets[sh]
                ws.set_column(0, 0, 22, fmt)
                ws.set_column(1, 60, 18, fmt)

    xlsx.seek(0)
    # Resultado principal: Consolidado si existe, si no Monitor, si no OutView
    if not df_c.empty:
        df_result = df_c
    elif not df_m.empty:
        df_result = df_m
    else:
        df_result = df_o
    return df_result, xlsx


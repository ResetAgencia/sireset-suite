# core/mougli_core.py
import io
import json
from io import BytesIO
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

# ───────────────────────────── Config persistente ─────────────────────────────
APP_DIR = Path(__file__).parent
CONFIG_PATH = APP_DIR / "factores_config.json"

_DEFAULT_MONITOR = {"TV": 0.255, "CABLE": 0.425, "RADIO": 0.425, "REVISTA": 0.14875, "DIARIOS": 0.14875}
_DEFAULT_OUTVIEW = {"tarifa_superficie_factor": 1.25}


def _load_cfg() -> dict:
    if CONFIG_PATH.exists():
        try:
            cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            cfg.setdefault("monitor", _DEFAULT_MONITOR.copy())
            cfg.setdefault("outview", _DEFAULT_OUTVIEW.copy())
            cfg["outview"].setdefault("tarifa_superficie_factor", 1.25)
            return cfg
        except Exception:
            pass
    cfg = {"monitor": _DEFAULT_MONITOR.copy(), "outview": _DEFAULT_OUTVIEW.copy()}
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return cfg


def load_monitor_factors() -> Dict[str, float]:
    return _load_cfg().get("monitor", _DEFAULT_MONITOR.copy())


def save_monitor_factors(f: Dict[str, float]) -> None:
    cfg = _load_cfg()
    cfg["monitor"] = {k: float(v) for k, v in f.items()}
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def load_outview_factor() -> float:
    return float(_load_cfg().get("outview", _DEFAULT_OUTVIEW)["tarifa_superficie_factor"])


def save_outview_factor(v: float) -> None:
    cfg = _load_cfg()
    cfg.setdefault("outview", _DEFAULT_OUTVIEW.copy())
    cfg["outview"]["tarifa_superficie_factor"] = float(v)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


# ───────────────────────── Utiles generales ─────────────────────────
MESES_ES = ["", "enero", "febrero", "marzo", "abril", "mayo", "junio",
            "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


def _decode_bytes(b: bytes) -> str:
    for enc in ("utf-8-sig", "latin-1", "cp1252"):
        try:
            return b.decode(enc)
        except Exception:
            pass
    raise ValueError("No fue posible decodificar el TXT.")


def _col_letter(idx: int) -> str:
    s = ""
    n = idx
    while n >= 0:
        s = chr(n % 26 + 65) + s
        n = n // 26 - 1
    return s


# ───────────────────────── Lectores de fuentes ──────────────────────
def _read_monitor_txt(file) -> pd.DataFrame:
    """Lee TXT de Monitor detectando cabecera con '|MEDIO|' y normaliza columnas."""
    if file is None:
        return pd.DataFrame()

    raw = file.read()
    text = _decode_bytes(raw) if isinstance(raw, (bytes, bytearray)) else raw
    lines = text.splitlines()

    hdr_idx = None
    for i, l in enumerate(lines[:60]):
        if "|MEDIO|" in l.upper():
            hdr_idx = i
            break
    if hdr_idx is None:
        return pd.DataFrame({"linea": [l for l in lines if l.strip()]})

    buf = io.StringIO("\n".join(lines[hdr_idx:]))
    df = pd.read_csv(buf, sep="|", engine="python")

    df.columns = df.columns.astype(str).str.strip()
    df = df.dropna(axis=1, how="all")

    first_col = df.columns[0]
    if first_col.strip() in {"#", ""}:
        df = df.drop(columns=[first_col])

    cols_up = {c: c.upper() for c in df.columns}
    df.rename(columns=cols_up, inplace=True)

    if "DIA" in df.columns:
        df["DIA"] = pd.to_datetime(df["DIA"], format="%d/%m/%Y", errors="coerce").dt.normalize()
        df["AÑO"] = df["DIA"].dt.year
        df["MES"] = df["DIA"].dt.month.apply(lambda m: MESES_ES[int(m)] if pd.notnull(m) and 1 <= m <= 12 else "")
        df["SEMANA"] = df["DIA"].dt.isocalendar().week

    if "MEDIO" in df.columns:
        df["MEDIO"] = df["MEDIO"].astype(str).str.upper().str.strip()

    if "INVERSION" in df.columns:
        df["INVERSION"] = pd.to_numeric(df["INVERSION"], errors="coerce").fillna(0)

    order = [c for c in ["DIA", "AÑO", "MES", "SEMANA"] if c in df.columns]
    df = df[[*order] + [c for c in df.columns if c not in order]]
    return df


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


# ───────────────────────── Transformaciones ─────────────────────────
def _aplicar_factores_monitor(df: pd.DataFrame, factores: Dict[str, float]) -> pd.DataFrame:
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


def _version_column(df: pd.DataFrame) -> str | None:
    for c in df.columns:
        if str(c).lower().startswith("vers"):
            return c
    return None


def _transform_outview_enriquecido(df: pd.DataFrame, *, factor_outview: float) -> pd.DataFrame:
    """Replica cálculos de OutView (incluye Tarifa Real $)."""
    if df is None or df.empty:
        return pd.DataFrame()

    df = df.copy()
    # Normalización de fechas
    df["Fecha"] = pd.to_datetime(df.get("Fecha"), dayfirst=True, errors="coerce")
    df["AÑO"] = df["Fecha"].dt.year
    df["MES"] = df["Fecha"].dt.month.apply(lambda m: MESES_ES[int(m)] if pd.notnull(m) and 1 <= m <= 12 else "")
    df["SEMANA"] = df["Fecha"].dt.isocalendar().week
    df["_FechaDT"] = df["Fecha"]
    df["_YM"] = df["_FechaDT"].dt.to_period("M")

    safe = lambda v: "" if pd.isna(v) else str(v)
    ver_col = _version_column(df)

    # Identificadores base
    df["Código único"] = df.apply(lambda r: "|".join([
        safe(r.get("MES","")), safe(r.get("AÑO","")), safe(r.get("Latitud","")), safe(r.get("Longitud","")),
        safe(r.get("Avenida","")), safe(r.get("Nro Calle/Cuadra","")), safe(r.get("Marca","")),
        safe(r.get("Tipo Elemento","")), safe(r.get("Orientación de Vía","")), safe(r.get("Tarifa S/.","")),
        safe(r.get("Proveedor","")), safe(r.get("Distrito","")), safe(r.get("Cod.Proveedor",""))
    ]), axis=1)

    df["Código +1 pieza"] = df.apply(lambda r: "|".join([
        safe(r.get("NombreBase","")), safe(r.get("Proveedor","")), safe(r.get("Tipo Elemento","")),
        safe(r.get("Distrito","")), safe(r.get("Orientación de Vía","")), safe(r.get("Nro Calle/Cuadra","")),
        safe(r.get("Item","")), safe(r.get(ver_col,"") if ver_col else ""),
        safe(r.get("Latitud","")), safe(r.get("Longitud","")), safe(r.get("Categoría","")),
        safe(r.get("Tarifa S/.","")), safe(r.get("Anunciante","")), safe(r.get("MES","")),
        safe(r.get("AÑO","")), safe(r.get("SEMANA",""))
    ]), axis=1)

    # Métricas base
    df["Denominador"] = df.groupby("Código único")["Código único"].transform("size")
    if ver_col:
        # nombre visible
        df["Q versiones por elemento"] = df.groupby("Código único")[ver_col].transform("nunique")

    # visible (minúscula exacta pedida)
    df["+1 superficie"] = df.groupby("Código +1 pieza")["Código +1 pieza"].transform("size")

    tarifa_num = pd.to_numeric(df.get("Tarifa S/."), errors="coerce").fillna(0)
    first_in_piece = (df.groupby("Código +1 pieza").cumcount() == 0)

    # interna para cálculo
    df["Tarifa × Superficie"] = np.where(first_in_piece, tarifa_num * df["+1 superficie"], 0.0)
    df["Tarifa × Superficie"] = (df["Tarifa × Superficie"] * float(factor_outview)) / 3.8

    df["Semana en Mes por Código"] = (
        df.groupby(["Código único","_YM"])["_FechaDT"].transform(lambda s: s.rank(method="dense").astype(int))
    )
    order_in_month = (
        df.sort_values(["Código único","_YM","_FechaDT"]).groupby(["Código único","_YM"]).cumcount()
    )
    # visible
    df["Conteo Mensual"] = (order_in_month == 0).astype(int)

    # Inversión: primera TxS por Código único / nº de piezas del código (interna derivada)
    df_pieces = df[df["Tarifa × Superficie"] != 0].sort_values(["Código único","_FechaDT"])
    per_code_first = df_pieces.groupby("Código único")["Tarifa × Superficie"].first()
    per_code_count = df_pieces.groupby("Código único")["Tarifa × Superficie"].size()
    per_code_value = (per_code_first / per_code_count).astype(float)
    df["Tarifa × Superficie (1ra por Código único)"] = df["Código único"].map(per_code_value)

    # Columnas "Excel" (AB..AI y EXTRAE) — internas
    if "NombreBase" in df.columns:
        s_nb = df["NombreBase"].astype(str)
        df["NB_EXTRAE_6_7"] = s_nb.str.slice(5, 12)
    else:
        df["NB_EXTRAE_6_7"] = ""

    def copy_or_empty(src, newname):
        df[newname] = df[src] if src in df.columns else ""

    copy_or_empty("Fecha", "Fecha_AB")
    copy_or_empty("Proveedor", "Proveedor_AC")
    copy_or_empty("Tipo Elemento", "TipoElemento_AD")
    copy_or_empty("Distrito", "Distrito_AE")
    copy_or_empty("Avenida", "Avenida_AF")
    copy_or_empty("Nro Calle/Cuadra", "NroCalleCuadra_AG")
    copy_or_empty("Orientación de Vía", "OrientacionVia_AH")
    copy_or_empty("Marca", "Marca_AI")

    # Conteos tipo CONTAR.SI.CONJUNTO — internas
    ab_ai_keys = ["Fecha_AB","Proveedor_AC","TipoElemento_AD","Distrito_AE",
                  "Avenida_AF","NroCalleCuadra_AG","OrientacionVia_AH","Marca_AI"]
    for c in ab_ai_keys:
        if c not in df.columns:
            df[c] = ""
    counts = df.groupby(ab_ai_keys, dropna=False).size().reset_index(name="Conteo_AB_AI")
    df = df.merge(counts, on=ab_ai_keys, how="left")

    z_keys = ["NB_EXTRAE_6_7","Proveedor_AC","TipoElemento_AD","Distrito_AE",
              "Avenida_AF","NroCalleCuadra_AG","OrientacionVia_AH","Marca_AI"]
    for c in z_keys:
        if c not in df.columns:
            df[c] = ""
    counts2 = df.groupby(z_keys, dropna=False).size().reset_index(name="Conteo_Z_AB_AI")
    df = df.merge(counts2, on=z_keys, how="left")

    # TarifaS/3 — interna de apoyo
    df["TarifaS_div3"] = tarifa_num / 3.0
    df["TarifaS_div3_sobre_Conteo"] = df["TarifaS_div3"] / df["Conteo_AB_AI"].astype(float)

    # SUMAR.SI.CONJUNTO — interna
    sum_keys = ["NB_EXTRAE_6_7","Proveedor","Tipo Elemento","Distrito",
                "Avenida","Nro Calle/Cuadra","Orientación de Vía","Marca"]
    for c in sum_keys:
        if c not in df.columns:
            df[c] = ""
    sums = (
        df.groupby(sum_keys, dropna=False)["TarifaS_div3_sobre_Conteo"]
          .sum().reset_index(name="Suma_AM_Z_AB_AI")
    )
    df = df.merge(sums, on=sum_keys, how="left")

    # Tope por Tipo — internas de apoyo
    tipo_to_base = {
        "BANDEROLA": 12000, "CLIP": 600, "MINIPOLAR": 1000, "PALETA": 600,
        "PANEL": 1825, "PANEL CARRETERO": 5000, "PANTALLA LED": 5400,
        "PARADERO": 800, "PRISMA": 2800, "QUIOSCO": 600, "RELOJ": 840,
        "TORRE UNIPOLAR": 3000, "TOTEM": 950, "VALLA": 600, "VALLA ALTA": 1300
    }
    tipo_up = df.get("Tipo Elemento", "").astype(str).str.upper()
    tope = tipo_up.map(tipo_to_base).astype(float) * (4.0/3.0)
    df["TopeTipo_AQ"] = tope
    an_val = pd.to_numeric(df["Suma_AM_Z_AB_AI"], errors="coerce")
    df["Suma_AM_Topada_Tipo"] = np.where(np.isnan(tope), an_val, np.minimum(an_val, tope))

    # División AO/AK y Tarifa Real ($) — visible
    denom = pd.to_numeric(df["Conteo_Z_AB_AI"], errors="coerce")
    df["SumaTopada_div_ConteoZ"] = np.where(
        denom > 0,
        pd.to_numeric(df["Suma_AM_Topada_Tipo"], errors="coerce") / denom,
        0.0
    )
    df["Tarifa Real ($)"] = np.where(
        tipo_up == "PANTALLA LED",
        df["SumaTopada_div_ConteoZ"] * 0.4,
        df["SumaTopada_div_ConteoZ"] * 0.8
    )

    # Limpiezas solicitadas globales (internas)
    df.drop(columns=["Tarifa × Superficie"], inplace=True, errors="ignore")
    if "Tarifa S/." in df.columns:
        df.drop(columns=["Tarifa S/."], inplace=True, errors="ignore")

    # Orden de columnas (base al inicio)
    base = ["Fecha", "AÑO", "MES", "SEMANA"]
    tail = [
        "Código único","Denominador",
        "Q versiones por elemento" if "Q versiones por elemento" in df.columns else None,
        "Código +1 pieza",
        "+1 superficie",
        "Tarifa × Superficie (1ra por Código único)",
        "Semana en Mes por Código","Conteo Mensual",
        "NB_EXTRAE_6_7","Fecha_AB","Proveedor_AC","TipoElemento_AD","Distrito_AE",
        "Avenida_AF","NroCalleCuadra_AG","OrientacionVia_AH","Marca_AI",
        "Conteo_AB_AI","Conteo_Z_AB_AI","TarifaS_div3","TarifaS_div3_sobre_Conteo",
        "Suma_AM_Z_AB_AI","TopeTipo_AQ","Suma_AM_Topada_Tipo",
        "SumaTopada_div_ConteoZ",
        "Tarifa Real ($)"
    ]
    tail = [c for c in tail if c]
    cols = [*base] + [c for c in df.columns if c not in (*base, *tail, "_FechaDT", "_YM")] + tail
    return df[cols].copy()


# ───────────────────────── Resúmenes y consolidado ─────────────────────────
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


_TARGET_ORDER = [
    "FECHA","AÑO","MES","SEMANA","MEDIO","MARCA","PRODUCTO","VERSIÓN",
    "DURACIÓN","TIPO ELEMENTO","TIME / Q VERSIONES","EMISORA / DISTRITO",
    "PROGRAMA / AVENIDA","BREAK / CALLE","POS. SPOT / ORIENTACIÓN",
    "INVERSIÓN REAL","SECTOR","CATEGORÍA","ÍTEM","AGENCIA","ANUNCIANTE",
    "REGIÓN","ANCHO / LATITUD","ALTO / LONGITUD","GEN / +1 SUPERFICIE",
    "Q ELEMENTOS","EDITORA / PROVEEDOR"
]
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
    "Tipo Elemento":"TIPO ELEMENTO","Q versiones por elemento":"TIME / Q VERSIONES",
    "Distrito":"EMISORA / DISTRITO","Avenida":"PROGRAMA / AVENIDA",
    "Nro Calle/Cuadra":"BREAK / CALLE","Orientación de Vía":"POS. SPOT / ORIENTACIÓN",
    "Tarifa Real ($)":"INVERSIÓN REAL","Sector":"SECTOR",
    "Categoría":"CATEGORÍA","Item":"ÍTEM","Agencia":"AGENCIA","Anunciante":"ANUNCIANTE",
    "Región":"REGIÓN","Latitud":"ANCHO / LATITUD","Longitud":"ALTO / LONGITUD",
    "+1 superficie":"GEN / +1 SUPERFICIE","Conteo Mensual":"Q ELEMENTOS",
    "Proveedor":"EDITORA / PROVEEDOR"
}


def _to_unified(df: pd.DataFrame, mapping: dict) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=_TARGET_ORDER)
    df = df.copy()
    df.rename(columns={k: v for k, v in mapping.items() if k in df.columns}, inplace=True)
    for c in _TARGET_ORDER:
        if c not in df.columns:
            df[c] = np.nan
    df = df[_TARGET_ORDER]
    if "FECHA" in df.columns:
        df["FECHA"] = pd.to_datetime(df["FECHA"], errors="coerce").dt.date
    return df


# ───────────────────────── Excel (encabezado + tabla) ─────────────────────────
def _header_rows_for(df: pd.DataFrame, *, fecha_col: str | None, marca_col: str | None,
                     extras: List[Tuple[str, str]] | None = None) -> List[Tuple[str, str]]:
    filas = [("Filas", len(df))]
    if fecha_col and fecha_col in df.columns and not df.empty:
        fmin, fmax = df[fecha_col].min(), df[fecha_col].max()
        val = (f"{pd.to_datetime(fmin, errors='coerce'):%d/%m/%Y} - "
               f"{pd.to_datetime(fmax, errors='coerce'):%d/%m/%Y}") if pd.notna(fmin) else "—"
        filas.append(("Rango de fechas", val))
    if marca_col and marca_col in df.columns:
        filas.append(("Marcas / Anunciantes", df[marca_col].dropna().nunique()))
    if extras:
        for col, tit in extras:
            if col in df.columns:
                vals = ", ".join(sorted(map(str, df[col].dropna().astype(str).unique())))
                filas.append((tit, vals if vals else "—"))
    return filas


def _write_sheet_with_header_and_table(writer: pd.ExcelWriter, *,
                                       sheet_name: str,
                                       df: pd.DataFrame,
                                       header_rows: List[Tuple[str, str]]):
    header_df = pd.DataFrame(header_rows, columns=["Descripción", "Valor"])
    header_df.to_excel(writer, sheet_name=sheet_name, index=False, startrow=0)
    ws = writer.sheets[sheet_name]

    # Altura fija por defecto (no auto-ajustar)
    ws.set_default_row(15)
    ws.set_row(0, 15)
    ws.set_row(1, 15)

    # Datos como tabla
    start_row = len(header_df) + 2
    df = df.copy()
    df.to_excel(writer, sheet_name=sheet_name, index=False, startrow=start_row)

    nrow, ncol = df.shape
    start_col_letter = "A"
    end_col_letter = _col_letter(ncol - 1)
    rng = f"{start_col_letter}{start_row+1}:{end_col_letter}{start_row + max(nrow,1) + 1}"

    ws.add_table(rng, {
        "name": f"{sheet_name.replace(' ', '_')}_tbl",
        "header_row": True,
        "style": "Table Style Medium 9",
        "columns": [{"header": str(h)} for h in df.columns]
    })
    ws.freeze_panes(start_row + 1, 0)
    ws.set_column(0, max(0, ncol - 1), 18)


# ───────────────────────── Función principal ─────────────────────────
def procesar_monitor_outview(monitor_file, out_file, factores: Dict[str, float] | None,
                             outview_factor: float | None = None):
    """
    Devuelve (df_result, xlsx_bytes) con hojas condicionales:
      - 'Monitor' solo si hay Monitor
      - 'OutView' solo si hay OutView
      - 'Consolidado' solo si hay ambas fuentes
    """
    factores = factores or load_monitor_factors()
    outview_factor = float(outview_factor if outview_factor is not None else load_outview_factor())

    # MONITOR
    df_m = _read_monitor_txt(monitor_file)
    df_m = _aplicar_factores_monitor(df_m, factores)

    # OUTVIEW (enriquecido)
    df_o_raw = _read_out_robusto(out_file)
    df_o = _transform_outview_enriquecido(df_o_raw, factor_outview=outview_factor) if not df_o_raw.empty else pd.DataFrame()

    # CONSOLIDADO unificado SOLO si existen ambas fuentes
    if not df_m.empty and not df_o.empty:
        mon_u = _to_unified(df_m, _MONITOR_MAP)
        out_u = _to_unified(df_o, _OUT_MAP)
        df_c = pd.concat([mon_u, out_u], ignore_index=True)
        df_c.sort_values(["FECHA", "MARCA"], inplace=True, na_position="last")
    else:
        df_c = pd.DataFrame()

    # ===== OutView: eliminar columnas internas (no deben aparecer en Excel ni en vista previa) =====
    # Mantener VISIBLES: "Conteo Mensual", "Q versiones por elemento", "Tarifa Real ($)", "+1 superficie"
    internal_targets = {
        "código único", "código +1 pieza", "denominador",
        "tarifa × superficie", "tarifa × superficie (1ra por código único)",
        "semana en mes por código",  # <- clave: esta queda eliminada aquí
        "nb_extrae_6_7", "fecha_ab", "proveedor_ac", "tipoelemento_ad", "distrito_ae",
        "avenida_af", "nrocallecuadra_ag", "orientacionvia_ah", "marca_ai",
        "conteo_ab_ai", "conteo_z_ab_ai", "tarifas_div3", "tarifas_div3_sobre_conteo",
        "suma_am_z_ab_ai", "topetipo_aq", "suma_am_topada_tipo", "sumatopada_div_conteoz"
    }

    def _norm(s: str) -> str:
        return str(s).strip().casefold()

    # Construir lista de columnas a eliminar por coincidencia normalizada
    drop_cols = [c for c in df_o.columns if _norm(c) in internal_targets]
    df_o_public = df_o.drop(columns=drop_cols, errors="ignore")

    # Excel
    xlsx = BytesIO()
    with pd.ExcelWriter(xlsx, engine="xlsxwriter", datetime_format="dd/mm/yyyy", date_format="dd/mm/yyyy") as w:
        if not df_m.empty:
            hdr_m = _header_rows_for(
                df_m, fecha_col="DIA", marca_col="MARCA",
                extras=[("SECTOR","Sectores"), ("CATEGORIA","Categorías"), ("REGION/ÁMBITO","Regiones")]
            )
            _write_sheet_with_header_and_table(w, sheet_name="Monitor", df=df_m, header_rows=hdr_m)

        if not df_o.empty:
            hdr_o = _header_rows_for(
                df_o, fecha_col="Fecha", marca_col="Anunciante",
                extras=[("Tipo Elemento","Tipo"), ("Proveedor","Proveedor"), ("Región","Regiones")]
            )
            # Escribimos la versión "pública" sin columnas internas:
            _write_sheet_with_header_and_table(w, sheet_name="OutView", df=df_o_public, header_rows=hdr_o)

        if not df_c.empty:  # solo si hay ambas
            d1, d2 = _date_range(df_c, ["FECHA"])
            hdr_c = [("Filas", len(df_c)),
                     ("Rango de fechas", f"{d1} - {d2}" if d1 and d2 else ""),
                     ("Fuentes incluidas", "Monitor + OutView")]
            _write_sheet_with_header_and_table(w, sheet_name="Consolidado", df=df_c, header_rows=hdr_c)

        # Ajuste visual global
        wb = w.book
        fmt = wb.add_format({"valign": "vcenter"})
        for sh in ("Monitor", "OutView", "Consolidado"):
            if sh in w.sheets:
                ws = w.sheets[sh]
                ws.set_column(0, 0, 22, fmt)
                ws.set_column(1, 60, 18, fmt)

    xlsx.seek(0)
    # Resultado principal para vista previa:
    if not df_c.empty:
        df_result = df_c
    elif not df_m.empty:
        df_result = df_m
    else:
        # Si solo hay OutView, muestra versión pública (sin internas) en la vista previa
        df_result = df_o_public
    return df_result, xlsx

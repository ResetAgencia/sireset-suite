# core/mougli_core.py
# -*- coding: utf-8 -*-
import io, os, sys, json, subprocess
from datetime import datetime
from pathlib import Path
from typing import List, Tuple, Dict, Any

import pandas as pd
import numpy as np

# ---- Auto-install liviano (igual que tu desktop) ----
AUTO_INSTALL = True
def ensure(modname, pipname=None):
    try:
        return __import__(modname)
    except Exception:
        if not AUTO_INSTALL:
            return None
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", pipname or modname])
            return __import__(modname)
        except Exception:
            return None

def _read_text_lines(fp) -> Tuple[List[str], str]:
    """Lee líneas de un .txt en distintas codificaciones."""
    if hasattr(fp, "read"):
        raw = fp.read()
        if isinstance(raw, bytes):
            for enc in ("utf-8-sig","latin-1","cp1252"):
                try:
                    txt = raw.decode(enc)
                    return txt.splitlines(True), enc
                except UnicodeDecodeError:
                    continue
            # último intento
            return raw.decode("utf-8","ignore").splitlines(True), "utf-8"
        else:
            return str(raw).splitlines(True), "utf-8"
    else:
        # path string
        for enc in ("utf-8-sig","latin-1","cp1252"):
            try:
                return open(fp, encoding=enc).readlines(), enc
            except UnicodeDecodeError:
                continue
        return open(fp, encoding="utf-8", errors="ignore").readlines(), "utf-8"


def _proc_monitor_file(file_obj, factores: Dict[str, float]) -> pd.DataFrame:
    lines, enc = _read_text_lines(file_obj)
    # buscar encabezado con |MEDIO|
    hdr = next((i for i,l in enumerate(lines[:60]) if "|MEDIO|" in l), None)
    if hdr is None:
        return pd.DataFrame()

    df = pd.read_csv(io.StringIO("".join(lines[hdr:])), sep="|", engine="python")
    df.columns = df.columns.str.strip()
    df = df.dropna(axis=1, how="all")
    if df.columns[0] in {"#",""}:
        df = df.drop(columns=[df.columns[0]])

    # columnas base que solemos tener
    if "DIA" in df.columns:
        df["DIA"] = pd.to_datetime(df["DIA"], format="%d/%m/%Y", errors="coerce")
        df["AÑO"] = df["DIA"].dt.year
        df["MES"] = df["DIA"].dt.month
        df["SEMANA"] = df["DIA"].dt.isocalendar().week

    if "MEDIO" in df.columns:
        df["MEDIO"] = df["MEDIO"].astype(str).str.upper()

    if "INVERSION" in df.columns:
        df["INVERSION"] = pd.to_numeric(df["INVERSION"], errors="coerce").fillna(0)
        df["INVERSION"] = df.apply(lambda r: r["INVERSION"] * factores.get(r.get("MEDIO",""), 1), axis=1)

    return df


def _proc_outview_file(file_obj) -> pd.DataFrame:
    name = getattr(file_obj, "name", "")
    ext = Path(name).suffix.lower()
    if ext == ".csv" or not ext:
        # probar varias codificaciones
        raw = file_obj.read() if hasattr(file_obj, "read") else open(file_obj, "rb").read()
        for enc in ("latin-1","utf-8-sig","cp1252"):
            try:
                return pd.read_csv(io.BytesIO(raw), encoding=enc)
            except UnicodeDecodeError:
                continue
        # último recurso
        return pd.read_csv(io.BytesIO(raw), encoding="utf-8", on_bad_lines="skip")
    else:
        ensure("openpyxl","openpyxl")
        return pd.read_excel(file_obj, engine="openpyxl")


def _summary(df: pd.DataFrame, fecha_col: str, marca_col: str) -> Dict[str, Any]:
    if df is None or df.empty:
        return {"rows": 0, "date_min": "—", "date_max": "—", "brands": 0}
    f = pd.to_datetime(df[fecha_col], errors="coerce")
    fmin = f.min(); fmax = f.max()
    marcas = pd.Index(df.get(marca_col, pd.Series(dtype=object))).dropna().nunique()
    fmt = lambda x: ("—" if pd.isna(x) else x.strftime("%d/%m/%Y"))
    return {"rows": int(len(df)), "date_min": fmt(fmin), "date_max": fmt(fmax), "brands": int(marcas)}


def _col_letter(idx: int) -> str:
    s=""; n=idx
    while n>=0:
        s = chr(n%26 + 65) + s
        n = n//26 - 1
    return s


def _write_table(writer, sheet, df: pd.DataFrame, startrow=0):
    df.to_excel(writer, sheet, index=False, startrow=startrow)
    ws = writer.sheets[sheet]
    nrow, ncol = df.shape
    if nrow and ncol:
        rng = f"A{startrow+1}:{_col_letter(ncol-1)}{startrow+nrow+1}"
        ws.add_table(rng, {
            "name": f"{sheet}_tbl",
            "header_row": True,
            "style": "Table Style Medium 9",
            "columns": [{"header": str(c)} for c in df.columns]
        })
        ws.freeze_panes(startrow+1, 0)


def procesar_monitor_outview(monitor_files, outview_files, factores: Dict[str, float]) -> Tuple[bytes, Dict[str, Any]]:
    """Devuelve (bytes_excel, detalles_para_tarjetas)."""
    # ---- Parseo de entradas ----
    mon_dfs = []
    if monitor_files:
        for f in monitor_files:
            try:
                df = _proc_monitor_file(f, factores)
                if not df.empty:
                    mon_dfs.append(df)
            finally:
                try: f.seek(0)
                except Exception: pass
    out_dfs = []
    if outview_files:
        for f in outview_files:
            try:
                df = _proc_outview_file(f)
                if not df.empty:
                    # fecha OutView flexible
                    if "Fecha" in df.columns:
                        df["Fecha"] = pd.to_datetime(df["Fecha"], dayfirst=True, errors="coerce")
                        df["AÑO"] = df["Fecha"].dt.year
                        df["MES"] = df["Fecha"].dt.month
                        df["SEMANA"] = df["Fecha"].dt.isocalendar().week
                    out_dfs.append(df)
            finally:
                try: f.seek(0)
                except Exception: pass

    dfm = pd.concat(mon_dfs, ignore_index=True) if mon_dfs else pd.DataFrame()
    dfo = pd.concat(out_dfs, ignore_index=True) if out_dfs else pd.DataFrame()

    # ---- Detalles p/ tarjetas ----
    det = {
        "monitor": _summary(dfm, "DIA" if "DIA" in dfm.columns else dfm.columns[0] if not dfm.empty else "DIA",
                            "MARCA" if "MARCA" in dfm.columns else "ANUNCIANTE" if "ANUNCIANTE" in dfm.columns else dfm.columns[-1] if not dfm.empty else "MARCA"),
        "outview": _summary(dfo, "Fecha" if "Fecha" in dfo.columns else dfo.columns[0] if not dfo.empty else "Fecha",
                            "Anunciante" if "Anunciante" in dfo.columns else "Marca" if "Marca" in dfo.columns else dfo.columns[-1] if not dfo.empty else "Anunciante")
    }

    # ---- Excel de salida ----
    ensure("xlsxwriter","xlsxwriter")
    bio = io.BytesIO()
    with pd.ExcelWriter(bio, engine="xlsxwriter", date_format="dd/mm/yyyy") as w:
        # Hoja Resumen
        resumen_rows = []
        m = det["monitor"]; o = det["outview"]
        resumen_rows.append(["Monitor - Filas", m["rows"]])
        resumen_rows.append(["Monitor - Rango", f'{m["date_min"]} - {m["date_max"]}'])
        resumen_rows.append(["Monitor - Marcas/Anunciantes", m["brands"]])
        resumen_rows.append(["OutView - Filas", o["rows"]])
        resumen_rows.append(["OutView - Rango", f'{o["date_min"]} - {o["date_max"]}'])
        resumen_rows.append(["OutView - Marcas/Anunciantes", o["brands"]])
        df_res = pd.DataFrame(resumen_rows, columns=["Descripción","Valor"])
        _write_table(w, "Resumen", df_res, startrow=0)

        if not dfm.empty:
            _write_table(w, "Monitor", dfm, startrow=0)
        if not dfo.empty:
            _write_table(w, "OutView", dfo, startrow=0)

    bio.seek(0)
    return bio.getvalue(), det


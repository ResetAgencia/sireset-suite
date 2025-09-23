import io
import pandas as pd

# Intenta decodificar un archivo de texto con varias codificaciones
def _read_monitor_robusto(file) -> pd.DataFrame:
    if file is None:
        return pd.DataFrame()
    raw = file.read()
    if isinstance(raw, bytes):
        # pruebo varias codificaciones comunes
        for enc in ("utf-8", "latin-1", "cp1252"):
            try:
                text = raw.decode(enc)
                break
            except Exception:
                text = None
        if text is None:
            raise ValueError("No fue posible decodificar el TXT (probé utf-8, latin-1, cp1252).")
    else:
        # ya es str (raro en Streamlit), lo uso directo
        text = raw

    # Aquí parseas tu TXT real. Por ahora: ejemplo mínimo -> una línea por registro
    df = pd.DataFrame({"linea": [l for l in text.splitlines() if l.strip()]})
    return df


def _read_outview(file) -> pd.DataFrame:
    if file is None:
        return pd.DataFrame()
    if file.name.lower().endswith(".csv"):
        return pd.read_csv(file)
    return pd.read_excel(file)


def procesar_monitor_outview(monitor_file, out_file, factores: dict):
    """
    Devuelve: (df_resultado, xlsx_bytes)
    - df_resultado: DataFrame con datos integrados
    - xlsx_bytes: BytesIO del Excel exportado (o None)
    """
    df_m = _read_monitor_robusto(monitor_file)
    df_o = _read_outview(out_file)

    # ---- Lógica de ejemplo: añade columnas de factores (ajusta a tu regla real)
    for k, v in (factores or {}).items():
        df_m[f"factor_{k.lower()}"] = v

    # Combina si hubiera OutView
    if not df_o.empty:
        df_o = df_o.copy()
        df_o.columns = [str(c) for c in df_o.columns]
        df_m = df_m.merge(df_o.iloc[: len(df_m)], how="left", left_index=True, right_index=True)

    # Exporta Excel
    xlsx = io.BytesIO()
    with pd.ExcelWriter(xlsx, engine="xlsxwriter") as writer:
        df_m.to_excel(writer, index=False, sheet_name="Resultado")
    xlsx.seek(0)

    return df_m, xlsx


def resumen_mougli(df: pd.DataFrame) -> pd.DataFrame:
    """Arma un resumen simple (ajústalo a tus métricas reales)."""
    if df is None or df.empty:
        return pd.DataFrame([{"Filas": 0}])
    return pd.DataFrame(
        [
            {
                "Filas": len(df),
                "Columnas": len(df.columns),
                "Tiene OutView": any(col.startswith("Unnamed") for col in df.columns),
            }
        ]
    )

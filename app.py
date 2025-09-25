# =============== M O U G L I (con worker) ===============
if app == "Mougli":
    import gc

    st.markdown("## Mougli – Monitor & OutView (seguro)")

    # ---------- Estado de worker en curso ----------
    job_id = st.session_state.get("job_id")
    if job_id:
        job_dir = JOBS_DIR / job_id
        prog = _read_progress(job_dir)
        st.info(f"Trabajo en curso: `{job_id}`")
        colP, colBtns = st.columns([3,1])
        with colP:
            step = int(prog.get("step", 0))
            total = int(prog.get("total", 6) or 6)
            st.progress(min(step, total) / max(total, 1), text=prog.get("message", "Procesando…"))
        with colBtns:
            if st.button("↻ Actualizar"):
                st.rerun()
            if st.button("Cancelar / Limpiar"):
                _clear_job(job_id)
                st.rerun()

        with st.expander("Ver registro (log)"):
            st.code(_read_log_tail(job_dir), language="text")

        if prog.get("status") == "done":
            outxlsx = job_dir / "SiReset_Mougli.xlsx"
            if outxlsx.exists():
                st.success("¡Listo! ✅ Descarga tu Excel.")
                st.download_button(
                    "Descargar Excel",
                    data=outxlsx.read_bytes(),
                    file_name="SiReset_Mougli.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            else:
                st.warning("El proceso terminó pero no encontré el archivo de salida.")
        elif prog.get("status") == "error":
            st.error(f"El worker reportó un error: {prog.get('message')}")
        st.stop()

    # ---------- Staging: subir → volcar a disco inmediatamente ----------
    MAX_PREVIEW_BYTES = 15 * 1024 * 1024  # 15 MB

    def _ensure_pending_job():
        jid = st.session_state.get("pending_job_id")
        if not jid:
            jid = uuid.uuid4().hex[:12]
            st.session_state["pending_job_id"] = jid
        job_dir = JOBS_DIR / jid
        job_dir.mkdir(parents=True, exist_ok=True)
        return jid, job_dir

    def _stage_files(kind: str, files):
        if not files:
            return []
        jid, job_dir = _ensure_pending_job()
        paths = _save_upload_to(job_dir, files, kind)
        # Limpia los bytes del uploader para liberar RAM
        key = "m_txt_multi" if kind == "monitor" else "o_multi"
        try:
            st.session_state[key] = None
        except Exception:
            pass
        del files
        gc.collect()
        return paths

    def _on_upload_monitor():
        files = st.session_state.get("m_txt_multi") or []
        _stage_files("monitor", files)

    def _on_upload_out():
        files = st.session_state.get("o_multi") or []
        _stage_files("outview", files)

    # ---------- Carga con callbacks (stream to disk) ----------
    colL, colR = st.columns(2)
    with colL:
        st.caption("Sube Monitor (.txt) — puedes subir varios (se guardan inmediatamente)")
        st.file_uploader(
            "Arrastra y suelta aquí",
            type=["txt"],
            key="m_txt_multi",
            label_visibility="collapsed",
            accept_multiple_files=True,
            on_change=_on_upload_monitor,
        )
    with colR:
        st.caption("Sube OutView (.csv / .xlsx) — puedes subir varios (se guardan inmediatamente)")
        st.file_uploader(
            "Arrastra y suelta aquí",
            type=["csv", "xlsx"],
            key="o_multi",
            label_visibility="collapsed",
            accept_multiple_files=True,
            on_change=_on_upload_out,
        )

    # ---------- Mostrar bandeja de archivos ya volcados a disco ----------
    jid = st.session_state.get("pending_job_id")
    mon_paths = []
    out_paths = []
    if jid:
        job_dir = JOBS_DIR / jid
        mon_paths = sorted((job_dir / "uploads" / "monitor").glob("*"))
        out_paths = sorted((job_dir / "uploads" / "outview").glob("*"))

    def _fmt_size(p: Path) -> str:
        try:
            b = p.stat().st_size
        except Exception:
            b = 0
        mb = b / (1024*1024)
        return f"{mb:.1f} MB"

    st.markdown("#### Archivos preparados")
    colA, colB = st.columns(2)
    with colA:
        st.write("**Monitor**")
        if mon_paths:
            for p in mon_paths:
                st.write(f"• {p.name} — {_fmt_size(p)}")
        else:
            st.caption("— vacío —")
    with colB:
        st.write("**OutView**")
        if out_paths:
            for p in out_paths:
                st.write(f"• {p.name} — {_fmt_size(p)}")
        else:
            st.caption("— vacío —")

    colBtns1, colBtns2 = st.columns(2)
    with colBtns1:
        if st.button("🗑️ Vaciar bandeja"):
            if jid:
                _clear_job(jid)
                st.session_state.pop("pending_job_id", None)
                gc.collect()
                st.rerun()
    with colBtns2:
        if st.button("🚀 Procesar (seguro, en background)", type="primary"):
            if not (mon_paths or out_paths):
                st.warning("Primero sube algún archivo; se guardan al seleccionarlos.")
            else:
                try:
                    # Lanza el worker con lo que ya está en disco y libera staging
                    _start_worker(JOBS_DIR / jid, mon_paths, out_paths, factores, out_factor)
                    st.session_state["job_id"] = jid
                    st.session_state.pop("pending_job_id", None)
                    gc.collect()
                    st.success("Trabajo lanzado. Puedes seguir usando la app.")
                    st.rerun()
                except Exception as e:
                    _clear_job(jid)
                    st.error(f"No se pudo iniciar el procesamiento: {e}")

    # ---------- Vistazo rápido (protegido) ----------
    st.markdown("---")
    st.markdown("### ¿Solo quieres un vistazo rápido sin procesar todo?")
    st.caption("Esto carga y muestra **solo resúmenes** para validar archivos (no genera Excel).")

    colPrevA, colPrevB = st.columns(2)
    with colPrevA:
        # si hay staging, omitimos previews pesados: ya están en disco
        if mon_paths:
            total_mb = sum((p.stat().st_size for p in mon_paths if p.exists()), 0) / (1024*1024)
            if total_mb > 15:
                st.info("Monitor en bandeja es pesado: se omite preview para evitar cuelgues.")
            else:
                try:
                    # combinamos rápido para preview
                    buf = BytesIO()
                    for i, p in enumerate(mon_paths):
                        with p.open("rb") as f:
                            if i > 0:
                                buf.write(b"\n")
                            buf.write(f.read())
                    buf.seek(0); setattr(buf, "name", "monitor_preview.txt")
                    df_m = _read_monitor_txt(buf)
                    st.dataframe(_web_resumen_enriquecido(df_m, es_monitor=True), use_container_width=True)
                except MemoryError:
                    st.warning("Preview de Monitor omitido por tamaño (protección de memoria).")
                except Exception as e:
                    st.error(f"No se pudo leer Monitor: {e}")

    with colPrevB:
        if out_paths:
            try:
                f0 = out_paths[0]
                if f0.stat().st_size > MAX_PREVIEW_BYTES:
                    st.info("OutView en bandeja es pesado: se omite preview para evitar cuelgues.")
                else:
                    with f0.open("rb") as fh:
                        setattr(fh, "name", f0.name)  # para que el lector detecte extensión
                        df_o = _read_out_robusto(fh)
                    st.dataframe(_web_resumen_enriquecido(df_o, es_monitor=False), use_container_width=True)
            except MemoryError:
                st.warning("Preview de OutView omitido por tamaño (protección de memoria).")
            except Exception as e:
                st.error(f"No se pudo leer OutView: {e}")


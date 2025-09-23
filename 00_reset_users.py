# pages/00_reset_users.py
# Página temporal para borrar usuarios y sembrar un admin nuevo con el esquema actual.
import json
import streamlit as st

# Importa tu auth.py
import auth

st.title("🧹 Reiniciar usuarios y sembrar Admin")

st.info(
    "Esta página **borra todos los usuarios y tokens de login** y crea un **admin** nuevo "
    "con el formato actual de contraseñas (pbkdf2). "
    "Úsala solo una vez y **luego elimina esta página** del repositorio."
)

# “Seguro de dos pasos”
colA, colB = st.columns([1,2])
with colA:
    st.write("**Paso 1. Confirma**")
    seguro = st.text_input("Escribe BORRAR para confirmar", type="default").strip().upper() == "BORRAR"
with colB:
    st.write("**Paso 2. Credenciales del nuevo admin**")
    email  = st.text_input("Email admin", value="admin@sreset.local").strip()
    nombre = st.text_input("Nombre admin", value="Admin SiReset").strip()
    pwd    = st.text_input("Contraseña admin", type="password")
    pwd2   = st.text_input("Repite contraseña", type="password")

if st.button("🚨 BORRAR TODO y CREAR ADMIN 🚨", type="primary", use_container_width=True):
    if not seguro:
        st.error("Debes escribir **BORRAR** para confirmar.")
        st.stop()
    if not email or not nombre or not pwd:
        st.error("Completa email, nombre y contraseña.")
        st.stop()
    if pwd != pwd2:
        st.error("Las contraseñas no coinciden.")
        st.stop()

    # 1) Asegura que la DB existe y módulos base estén registrados
    auth.init_db()
    auth.ensure_builtin_modules()

    # 2) Borra usuarios + tokens
    con = auth._connect()
    cur = con.cursor()
    cur.execute("DELETE FROM users")
    cur.execute("DELETE FROM login_tokens")
    con.commit()

    # 3) Crea admin nuevo (usa hashing pbkdf2 actual)
    admin_id = auth.create_user(
        email=email,
        name=nombre,
        role="admin",
        pwd=pwd,
        active=True,
        modules=["Mougli", "Mapito"],   # da acceso completo
    )
    con.close()

    # 4) (Opcional) crea un magic-link temporal de acceso
    try:
        token = auth.create_login_token(admin_id, days=3)
        st.success("✅ Admin creado.")
        st.write("Puedes iniciar sesión con usuario/clave o usar este **magic-link (3 días)**:")
        st.code(f"?tk={token}", language="text")
        st.caption("Añade ese parámetro a la URL de tu app (por ejemplo, https://tuapp.streamlit.app/?tk=TOKEN)")
    except Exception:
        st.success("✅ Admin creado. (No se generó magic-link)")

    st.warning("⚠️ **IMPORTANTE**: elimina esta página (`pages/00_reset_users.py`) "
               "del repositorio una vez termines.")


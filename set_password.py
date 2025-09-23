# set_password.py
# Uso:
#   (.venv) python set_password.py "correo@dominio.com" "NUEVA_CONTRASEÑA" [rol]
# Si el usuario existe: le resetea contraseña, lo activa y mantiene (o actualiza) rol y módulos.
# Si NO existe: lo crea con ese correo, rol (por defecto 'admin') y acceso a Mougli/Mapito.

from pathlib import Path
import sys, json
import auth

def main():
    if len(sys.argv) < 3:
        print('Uso: python set_password.py "correo@dominio.com" "NUEVA_CONTRASEÑA" [rol]')
        sys.exit(1)

    email = sys.argv[1].strip()
    new_pwd = sys.argv[2].strip()
    role = sys.argv[3].strip() if len(sys.argv) >= 4 else "admin"

    auth.init_db()

    found = auth.find_user_by_email(email)
    if found:
        uid, u = found
        # Si no trae módulos por ser un registro viejo, dale ambos
        modules = u.get("modules") or ["Mougli", "Mapito"]
        auth.update_user(uid,
                         pw_hash=auth._hash_pw(new_pwd),  # usamos el mismo hasher que auth
                         active=True,
                         role=role,
                         modules=modules)
        print(f"[OK] Contraseña reseteada y usuario activado: {email} (rol={role})")
    else:
        uid = auth.create_user(email=email,
                               name=email.split("@")[0],
                               role=role,
                               pwd=new_pwd,
                               active=True,
                               modules=["Mougli", "Mapito"])
        print(f"[OK] Usuario creado: {email} (rol={role})  uid={uid}")

if __name__ == "__main__":
    main()

import argparse, getpass
from sqlalchemy import select
from .main import initialize
from .database import SessionLocal
from .models import User
from .auth import hash_password
from .schemas import Register

def main():
    parser=argparse.ArgumentParser(description='Crear administrador local de Ferretería Horizonte')
    parser.add_argument('--email')
    parser.add_argument('--name',default='Administrador')
    args=parser.parse_args()
    email=args.email or input('Correo del administrador: ').strip()
    password=getpass.getpass('Contraseña (mínimo 8 caracteres): ')
    if password!=getpass.getpass('Repite la contraseña: '): raise SystemExit('Las contraseñas no coinciden')
    data=Register(email=email,name=args.name,password=password)
    initialize()
    with SessionLocal() as db:
        if db.scalar(select(User).where(User.email==data.email)): raise SystemExit('El correo ya está registrado. No se modificó la cuenta existente.')
        db.add(User(email=data.email,name=data.name,password_hash=hash_password(data.password),role='admin'))
        db.commit()
    print('Administrador creado. Inicia sesión desde Mi cuenta.')
if __name__=='__main__': main()

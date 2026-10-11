import hashlib, hmac, secrets, time, os
from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session as DBSession
from .database import get_db
from .models import User, Session

def hash_password(password):
    salt = secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=salt.encode(), n=16384, r=8, p=1).hex()
    return f'{salt}${digest}'
def verify_password(password, value):
    salt, digest = value.split('$')
    return hmac.compare_digest(hashlib.scrypt(password.encode(), salt=salt.encode(), n=16384, r=8, p=1).hex(), digest)
def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()
def start_session(db, response, user):
    token = secrets.token_urlsafe(48)
    db.add(Session(token_hash=token_hash(token), user_id=user.id, expires=int(time.time()) + 86400 * 7))
    db.commit()
    response.set_cookie('horizonte_session', token, httponly=True, samesite='strict', secure=os.getenv('COOKIE_SECURE') == '1', max_age=86400*7, path='/')
def current_user(request: Request, db: DBSession = Depends(get_db)):
    session = db.get(Session, token_hash(request.cookies.get('horizonte_session','')))
    if not session or session.expires < time.time():
        raise HTTPException(401, 'Inicia sesión para continuar')
    user = db.get(User, session.user_id)
    if not user:
        raise HTTPException(401, 'Sesión inválida')
    return user
def admin(user: User = Depends(current_user)):
    if user.role != 'admin':
        raise HTTPException(403, 'Esta operación requiere acceso de administrador')
    return user
def public_user(user):
    return {k:getattr(user,k) for k in ['id','email','name','phone','role','addresses','created_at']}

from pathlib import Path
from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from .config import setting

DATA = Path(__file__).resolve().parent / 'data'
DATA.mkdir(exist_ok=True)
DEFAULT_DATABASE = DATA / ('presentacion.db' if (DATA/'presentacion.activa').exists() else 'horizonte.db')

def build_engine(address):
    try:
        url = make_url(address)
    except Exception:
        raise ValueError('La conexión de base de datos no es una dirección válida') from None
    if url.get_backend_name() == 'sqlite':
        result = create_engine(url, connect_args={'check_same_thread': False, 'timeout': 30})
        @event.listens_for(result, 'connect')
        def configure(connection, _):
            connection.execute('PRAGMA foreign_keys=ON')
            connection.execute('PRAGMA journal_mode=WAL')
        return result
    if url.drivername not in ('postgres', 'postgresql', 'postgresql+psycopg'):
        raise ValueError('Usa SQLite o PostgreSQL para la base de datos')
    if not all((url.host, url.username, url.password, url.database)):
        raise ValueError('La conexión PostgreSQL necesita servidor, usuario, contraseña y base')
    url = url.set(drivername='postgresql+psycopg')
    if url.host.endswith('.neon.tech'):
        if url.query.get('sslmode', 'require') not in ('require', 'verify-ca', 'verify-full'):
            raise ValueError('La conexión Neon requiere SSL')
        url = url.update_query_dict({'sslmode': url.query.get('sslmode', 'require')})
    return create_engine(url, connect_args={'connect_timeout': 15, 'prepare_threshold': None},
                         pool_size=3, max_overflow=2, pool_timeout=20,
                         pool_pre_ping=True, pool_recycle=300, hide_parameters=True)


# NEON_DATABASE_URL is only used by migration; DATABASE_URL selects the live app.
engine = build_engine(setting('DATABASE_URL', f'sqlite:///{DEFAULT_DATABASE}'))
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
class Base(DeclarativeBase):
    pass
def get_db():
    with SessionLocal() as db:
        yield db

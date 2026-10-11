import os
from pathlib import Path
from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DATA = Path(__file__).resolve().parent / 'data'
DATA.mkdir(exist_ok=True)
engine = create_engine(os.getenv('DATABASE_URL', f'sqlite:///{DATA / "horizonte.db"}'), connect_args={'check_same_thread': False, 'timeout': 30})
@event.listens_for(engine, 'connect')
def configure(connection, _):
    connection.execute('PRAGMA foreign_keys=ON')
    connection.execute('PRAGMA journal_mode=WAL')
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
class Base(DeclarativeBase):
    pass
def get_db():
    with SessionLocal() as db:
        yield db

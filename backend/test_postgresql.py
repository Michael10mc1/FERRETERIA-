"""Opt-in Neon integration checks in disposable schemas, never application tables.

RUN_NEON_TESTS=1 python -m pytest backend/test_postgresql.py -q
"""
import os
import re
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema

from .config import setting
from .database import Base, build_engine
from .models import Product, User, Session as LoginSession
from .migrate_neon import copy_database, digest

pytestmark = pytest.mark.skipif(os.getenv('RUN_NEON_TESTS') != '1', reason='Opt-in Neon tests')


@contextmanager
def isolated_database():
    engine = build_engine(setting('NEON_DATABASE_URL'))
    assert engine.dialect.name == 'postgresql'
    schema = 'horizonte_check_' + uuid4().hex
    assert re.fullmatch(r'horizonte_check_[0-9a-f]{32}', schema)
    with engine.begin() as db:
        db.execute(CreateSchema(schema))
    @event.listens_for(engine, 'begin')
    def use_schema(connection):
        connection.exec_driver_sql(f'SET LOCAL search_path TO "{schema}"')
    try:
        yield engine, schema
    finally:
        event.remove(engine, 'begin', use_schema)
        with engine.begin() as db:
            db.execute(DropSchema(schema, cascade=True))
        engine.dispose()


def test_migration_preserves_records_and_sequences(tmp_path):
    source = create_engine('sqlite:///' + str(tmp_path / 'origin.db'))
    Base.metadata.create_all(source)
    with Session(source) as db:
        db.add(User(id=17, email='migration@example.test', name='Migración', password_hash='test', role='cliente',
                    addresses=[{'district': 'Lima'}]))
        db.add(Product(id=23, sku='PRUEBA', name='Taladro', description='Prueba', category='Herramientas',
                       brand='Prueba', features={'potencia': '500 W'}, image='', unit='unidad',
                       price_cents=15990, cost_cents=10000, stock=1, active=True))
        db.flush()
        db.add(LoginSession(token_hash='local-only', user_id=17, expires=9999999999))
        db.commit()
    try:
        with isolated_database() as (destination, _):
            with source.connect() as origin, destination.begin() as target:
                manifest = copy_database(origin, target)
                assert digest(target, Product.__table__) == manifest['products']
                assert target.execute(select(LoginSession)).all() == []
            with Session(destination) as db:
                next_user = User(email='next@example.test', name='Nuevo', password_hash='test')
                db.add(next_user)
                db.commit()
                assert next_user.id > 17
            with pytest.raises(ValueError, match='contiene registros'):
                with source.connect() as origin, destination.begin() as target:
                    copy_database(origin, target)
            with destination.connect() as db:
                assert db.scalar(select(Product.stock)) == 1
    finally:
        source.dispose()


# PgBouncer rejects startup search_path options. SET LOCAL on every transaction
# isolates all sessions, including background tasks and the persistence subprocess.
PG_SETUP = '''
import os, re
from sqlalchemy import event
from backend.database import engine
_schema = os.environ['HORIZONTE_PG_TEST_SCHEMA']
assert re.fullmatch(r'horizonte_check_[0-9a-f]{32}', _schema)
@event.listens_for(engine, 'begin')
def _schema_transaction(connection):
    connection.exec_driver_sql('SET LOCAL search_path TO "'+_schema+'"')
'''


@pytest.mark.parametrize('filename', ['test_app.py', 'test_ml.py', 'test_agents.py', 'test_assistant.py'])
def test_existing_flow_on_postgresql(filename):
    with isolated_database() as (engine, schema):
        environment = dict(os.environ, DATABASE_URL=engine.url.render_as_string(hide_password=False),
                           HORIZONTE_PG_TEST_SCHEMA=schema)
        source = Path(__file__).with_name(filename).read_text(encoding='utf-8')
        # Their normal entry points remain isolated SQLite tests.
        source = re.sub(r"^os\.environ\['DATABASE_URL'\]=.*$", '', source, flags=re.M)
        if filename == 'test_app.py':
            source = source.replace("result=subprocess.run([sys.executable,'-c',code]", "result=subprocess.run([sys.executable,'-c',_PG_SETUP+code]")
        wrapper = PG_SETUP + '\n_PG_SETUP=' + repr(PG_SETUP) + '\n'
        wrapper += "__package__='backend'\n__name__='backend.postgresql_check'\n"
        wrapper += 'exec(' + repr(source) + ')\n'
        wrapper += 'test_complete_business_flow()' if filename == 'test_app.py' else 'checks()'
        result = subprocess.run([sys.executable, '-c', wrapper], env=environment, capture_output=True,
                                text=True, encoding='utf-8', errors='replace', timeout=300)
        output = result.stdout + result.stderr
        for secret in (setting('NEON_DATABASE_URL'), setting('HIVE_API_KEY'), engine.url.password):
            if secret:
                output = output.replace(secret, '[privado]')
        assert result.returncode == 0, output[-8000:]

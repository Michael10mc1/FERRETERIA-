"""One-time, verified SQLite -> PostgreSQL import. Never overwrites populated tables.

python -m backend.migrate_neon          # inspect only
python -m backend.migrate_neon --apply  # snapshot, import, verify, commit
"""
import argparse
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, func, inspect, select, text

from .config import setting
from .database import Base, DATA, DEFAULT_DATABASE, build_engine
from . import models  # register every application table

MARKER = 'neon_migration'


def rows(connection, table):
    return connection.execute(select(table).order_by(*table.primary_key.columns)).mappings()


def digest(connection, table):
    hasher = hashlib.sha256()
    count = 0
    for row in rows(connection, table):
        hasher.update(json.dumps(dict(row), sort_keys=True, ensure_ascii=False,
                                 separators=(',', ':'), allow_nan=False).encode('utf-8'))
        hasher.update(b'\n')
        count += 1
    return {'rows': count, 'sha256': hasher.hexdigest()}


def source_manifest(source):
    return {table.name: digest(source, table) for table in Base.metadata.sorted_tables
            if table.name != 'sessions'}


def require_empty(destination):
    for table in Base.metadata.sorted_tables:
        if destination.scalar(select(func.count()).select_from(table)):
            raise ValueError('La base destino contiene registros; no se sobrescribirá')


def copy_database(source, destination):
    """Caller owns the PostgreSQL transaction. A failed comparison rolls it all back."""
    if destination.dialect.name != 'postgresql':
        raise ValueError('El destino de la migración debe ser PostgreSQL')
    destination.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': 731948571})
    Base.metadata.create_all(destination)
    require_empty(destination)
    manifest = source_manifest(source)
    for table in Base.metadata.sorted_tables:
        if table.name == 'sessions':
            continue  # local login cookies must never become cloud sessions
        batch = []
        for row in rows(source, table):
            batch.append(dict(row))
            if len(batch) == 500:
                destination.execute(table.insert(), batch)
                batch = []
        if batch:
            destination.execute(table.insert(), batch)
        if digest(destination, table) != manifest[table.name]:
            raise ValueError('Los registros importados no coinciden con el respaldo')
        if 'id' in table.c and table.c.id.primary_key:
            # Explicit IDs were preserved; advance serial sequences for future inserts.
            schema = destination.get_execution_options().get('schema_translate_map', {}).get(None)
            preparer = destination.dialect.identifier_preparer
            qualified = (preparer.quote_schema(schema) + '.' if schema else '') + preparer.quote(table.name)
            sequence = destination.scalar(text("SELECT pg_get_serial_sequence(:table, 'id')"), {'table': qualified})
            maximum = destination.scalar(select(func.max(table.c.id))) or 0
            if sequence:
                destination.execute(text('SELECT setval(CAST(:sequence AS regclass), :value, :called)'),
                                    {'sequence': sequence, 'value': max(1, maximum), 'called': maximum > 0})
    fingerprint = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
    destination.execute(models.Setting.__table__.insert(), {'key': MARKER, 'value': {
        'created_at': datetime.now(timezone.utc).isoformat(),
        'fingerprint': fingerprint, 'tables': manifest, 'sessions_imported': False,
    }})
    return manifest


def migrate(source_path, address, apply=False):
    source_path = Path(source_path).resolve()
    if not source_path.is_file():
        raise ValueError('No existe la base local que se va a trasladar')
    destination = build_engine(address)
    if destination.dialect.name != 'postgresql':
        raise ValueError('Configura una conexión PostgreSQL completa en NEON_DATABASE_URL')
    try:
        with destination.connect() as connection:
            existing = set(inspect(connection).get_table_names())
            if existing - set(Base.metadata.tables):
                raise ValueError('La base contiene tablas ajenas al proyecto; no se modificará')
            for name in existing:
                if connection.scalar(select(func.count()).select_from(Base.metadata.tables[name])):
                    raise ValueError('La base destino ya tiene datos; no se sobrescribirá')
        if not apply:
            # Inspect the original without changing its journal mode or making a backup.
            source = create_engine(f'sqlite:///file:{source_path.as_posix()}?mode=ro&uri=true')
            try:
                with source.connect() as connection:
                    return {'ready': True, 'tables': source_manifest(connection), 'imported': False}
            finally:
                source.dispose()
        stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')
        backup = DATA / f'migration-backup-{stamp}.db'
        with sqlite3.connect(f'file:{source_path.as_posix()}?mode=ro', uri=True) as original:
            with sqlite3.connect(backup) as snapshot:
                original.backup(snapshot)
        source = create_engine(f'sqlite:///file:{backup.as_posix()}?mode=ro&uri=true')
        try:
            with source.connect() as original, destination.begin() as target:
                manifest = copy_database(original, target)
            report = {'imported': True, 'verified': True, 'backup': str(backup),
                      'tables': manifest, 'sessions_imported': False}
            (DATA / 'neon-migration-report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
            return report
        finally:
            source.dispose()
    finally:
        destination.dispose()


def main():
    parser = argparse.ArgumentParser(description='Traslado verificado a Neon sin sobrescribir datos')
    parser.add_argument('--source', type=Path, default=DEFAULT_DATABASE)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    try:
        result = migrate(args.source, setting('NEON_DATABASE_URL'), args.apply)
        print(json.dumps({key: value for key, value in result.items() if key != 'tables'}, ensure_ascii=False))
        print(json.dumps({name: entry['rows'] for name, entry in result['tables'].items()}))
    except Exception as exc:
        # Driver exceptions can contain credentials, customer fields or statements.
        safe = str(exc) if type(exc) is ValueError else 'No se pudo completar la conexión o el traslado'
        print(json.dumps({'ok': False, 'detail': safe, 'error_type': type(exc).__name__}, ensure_ascii=False))
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()

"""Inferencia de siete días. El historial de ejemplo nunca se escribe en la BD."""
import csv
import gzip
import hashlib
import io
import json
import math
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import admin
from .database import get_db
from .models import DailySale, Movement, Order, OrderItem, Product, Setting
from .services import lock

router = APIRouter(prefix='/api/admin/ml', dependencies=[Depends(admin)])
ASSETS = Path(__file__).resolve().parent/'ml_assets'
PERU = timezone(timedelta(hours=-5))
FEATURES = ['categoria','marca','precio_soles','promocion','ventas_hoy','lag_1','lag_7','lag_14',
            'media_7','media_14','media_28','desv_28','dia_semana','mes','dia_anio_sin','dia_anio_cos']

def local_date(value):
    dt = datetime.fromisoformat(value)
    return dt.replace(tzinfo=timezone.utc).astimezone(PERU).date() if dt.tzinfo is None else dt.astimezone(PERU).date()

def today():
    return datetime.now(PERU).date()

@lru_cache(maxsize=1)
def report():
    return json.loads((ASSETS/'informe.json').read_text(encoding='utf-8'))

@lru_cache(maxsize=1)
def load_model():
    # Only the bundled, hash-checked artifact can be loaded; no pickle uploads.
    import joblib, sklearn
    meta = report()
    path = ASSETS/'modelo_final.joblib'
    if sklearn.__version__ != meta['versiones']['sklearn']:
        raise ValueError('Versión de scikit-learn incompatible con el modelo')
    if hashlib.sha256(path.read_bytes()).hexdigest() != meta['artifact_sha256']:
        raise ValueError('El archivo del modelo no coincide con su informe')
    bundle = joblib.load(path)
    if bundle['features'] != FEATURES or bundle['horizonte_dias'] != 7:
        raise ValueError('El modelo no cumple el contrato de predicción')
    return bundle

def features(product, history, cutoff):
    import numpy as np
    values = np.asarray([h['units'] for h in history], dtype=float)
    if len(values) != 28 or not np.isfinite(values).all() or (values < 0).any():
        raise ValueError('Se requieren 28 días completos y válidos')
    return dict(zip(FEATURES, [product['category'], product['brand'], product['price_cents']/100,
        product.get('promo',0), values[-1], values[-2], values[-8], values[-15],
        values[-7:].mean(), values[-14:].mean(), values.mean(), values.std(ddof=1),
        cutoff.weekday(), cutoff.month, np.sin(2*np.pi*cutoff.timetuple().tm_yday/365.25),
        np.cos(2*np.pi*cutoff.timetuple().tm_yday/365.25)]))

def real_history(db, cutoff, product_ids=None):
    start = cutoff-timedelta(days=27)
    days = [start+timedelta(days=n) for n in range(28)]
    products = list(db.scalars(select(Product).where(Product.active == True if product_ids is None else Product.id.in_(product_ids))))
    movements = {}
    for m in db.scalars(select(Movement).order_by(Movement.created_at, Movement.id)):
        movements.setdefault(m.product_id, []).append((local_date(m.created_at),m))
    imported = {(x.product_id,x.day):x for x in db.scalars(select(DailySale).where(
        DailySale.day >= start.isoformat(), DailySale.day <= cutoff.isoformat()))}
    sold, committed_today, pending = {}, {}, set()
    for item, order in db.execute(select(OrderItem,Order).join(Order,OrderItem.order_id == Order.id).where(Order.status != 'cancelado')):
        d = local_date(order.created_at)
        if d == cutoff+timedelta(days=1):
            committed_today[item.product_id] = committed_today.get(item.product_id,0)+item.quantity
        if order.status == 'entregado' and start <= d <= cutoff:
            key = (item.product_id,d.isoformat())
            sold[key] = sold.get(key,0)+item.quantity
        elif start <= d <= cutoff:
            pending.add((item.product_id,d.isoformat()))
    output = []
    for p in products:
        pm = movements.get(p.id,[])
        opening = min((d for d,m in pm if m.kind == 'apertura'), default=None)
        h, limited = [], 0
        for day in days:
            imported_day = imported.get((p.id,day.isoformat()))
            if imported_day:
                h.append({'date':day.isoformat(),'units':imported_day.units,'available':imported_day.available,'pending':False})
                limited += int(not imported_day.available)
            elif opening and day > opening:
                before = [m for d,m in pm if d < day]
                during = [m for d,m in pm if d == day]
                unavailable = (bool(before) and before[-1].balance <= 0) or any(m.balance <= 0 for m in during)
                limited += int(unavailable)
                h.append({'date':day.isoformat(),'units':sold.get((p.id,day.isoformat()),0),
                    'available':not unavailable,'pending':(p.id,day.isoformat()) in pending})
        output.append({**{k:getattr(p,k) for k in ['id','sku','name','category','brand','price_cents','cost_cents','stock','min_stock','image','unit']},
            'promo':int(p.discount_percent > 0), 'history':h, 'limited_days':limited,
            'committed_today':committed_today.get(p.id,0), 'opening':opening.isoformat() if opening else None,
            'pending_days':sum(x.get('pending',False) for x in h)})
    return output

def unavailable_reason(p):
    return ('Historial insuficiente' if len(p['history']) < 28 else
            'Pedidos históricos sin resolver' if p.get('pending_days',0) else
            'Ventas limitadas por disponibilidad' if p.get('limited_days',0) else
            'Sin ventas en los últimos 28 días' if sum(h['units'] for h in p['history']) == 0 else None)

def forecast(db, mode='tienda'):
    if mode not in ('tienda','ejemplo'):
        raise HTTPException(422,'Elige Mi tienda o Explorar el modelo')
    if mode == 'ejemplo':
        with gzip.open(ASSETS/'ejemplo.json.gz','rt',encoding='utf-8') as f:
            sample = json.load(f)
        cutoff, items = date.fromisoformat(sample['as_of']), sample['items']
    else:
        cutoff = today()-timedelta(days=1)
        items = real_history(db,cutoff)
    ready, rows = [], []
    for p in items:
        history = p['history']
        reason = unavailable_reason(p)
        item = {k:p[k] for k in ['sku','name','category','stock','min_stock','image','unit']}
        item.update({'history':history, 'history_days':len(history), 'limited_days':p.get('limited_days',0),
            'prediction':None,'remaining_prediction':None,'committed_today':p.get('committed_today',0),
            'target_stock':None,'suggested':None,'purchase_cents':None,
            'action':'sin_historial','reason':reason,'previous_7':sum(h['units'] for h in history[-7:]) if len(history)==28 else None})
        rows.append(item)
        if reason is None:
            ready.append((p,item))
    if ready:
        try:
            import pandas as pd
            from threadpoolctl import threadpool_limits
            bundle = load_model()
            X = pd.DataFrame([features(p,p['history'],cutoff) for p,_ in ready],columns=FEATURES)
            with threadpool_limits(limits=2):
                predictions = bundle['modelo'].predict(X)
            for (p,row), pred in zip(ready,predictions):
                pred = max(0,float(pred))
                if not math.isfinite(pred): raise ValueError('Predicción no válida')
                remaining = max(0,pred-p.get('committed_today',0))
                target = math.ceil(max(p['min_stock'],remaining*bundle['factor']))
                suggested = max(0,target-p['stock'])
                action = 'urgente' if p['stock'] < remaining else 'preventiva' if p['stock'] < target else 'cubierto'
                row.update(prediction=round(pred,2),remaining_prediction=round(remaining,2),target_stock=target,suggested=suggested,
                           purchase_cents=suggested*p['cost_cents'],action=action)
        except (ImportError,ValueError,OSError,KeyError) as exc:
            raise HTTPException(503,'No se pudo cargar el modelo compatible. Revisa las dependencias y el paquete ML.') from exc
    order = {'urgente':0,'preventiva':1,'cubierto':2,'sin_historial':3}
    rows.sort(key=lambda r:(order[r['action']],-(r['suggested'] or 0),r['name']))
    origin='DATOS_CUADERNO' if mode=='ejemplo' else 'DATOS_DE_DEMOSTRACION' if db.get(Setting,'presentation') else 'REGISTROS_TIENDA'
    return {'mode':mode,'history_origin':origin,'as_of':cutoff.isoformat(),'forecast_start':(cutoff+timedelta(days=1)).isoformat(),
        'forecast_end':(cutoff+timedelta(days=7)).isoformat(),'generated_at':datetime.now(PERU).isoformat(),
        'trained_on':'SINTETICO','items':rows,'summary':{'products':len(rows),'ready':len(ready),
        'urgent':sum(r['action']=='urgente' for r in rows),'preventive':sum(r['action']=='preventiva' for r in rows),
        'purchase_cents':sum(r['purchase_cents'] or 0 for r in rows)}}

@router.get('/forecast')
def get_forecast(mode:str='tienda',db:Session=Depends(get_db)):
    return forecast(db,mode)

@router.get('/model')
def get_model(db:Session=Depends(get_db)):
    data = dict(report())
    data.pop('artifact_sha256',None)
    source=db.get(Setting,'presentation')
    data['project_data']={k:source.value[k] for k in ('methodology','days','from','through','delivered_orders')} if source else None
    return data

@router.get('/export')
def export(mode:str='tienda',db:Session=Depends(get_db)):
    data = forecast(db,mode)
    stream = io.StringIO(); stream.write('\ufeff')
    writer = csv.writer(stream)
    writer.writerow(['sku','producto','origen_historial','modelo_entrenado_con','desde','hasta','stock','ventas_previstas_7d','comprometidas_hoy','prevision_restante','reponer','costo_estimado_soles','decision','observacion'])
    labels = {'urgente':'Reponer urgente','preventiva':'Reposición preventiva','cubierto':'Stock cubierto','sin_historial':'Sin pronóstico'}
    for p in data['items']:
        values = [p['sku'],p['name'],data['history_origin'],'SINTETICO',data['forecast_start'],data['forecast_end'],p['stock'],
                  p['prediction'],p['committed_today'],p['remaining_prediction'],p['suggested'],None if p['purchase_cents'] is None else p['purchase_cents']/100,labels[p['action']],p['reason']]
        writer.writerow(["'"+v if isinstance(v,str) and v.startswith(('=','+','-','@','\t','\r')) else v for v in values])
    return Response(stream.getvalue(),media_type='text/csv; charset=utf-8',headers={'Content-Disposition':f'attachment; filename="prevision-{mode}.csv"'})

class HistoryInput(BaseModel):
    csv: str = Field(min_length=20,max_length=5_000_000)

@router.post('/history')
def import_history(payload:HistoryInput,db:Session=Depends(get_db),user=Depends(admin)):
    """Historical rows are allowed only before local inventory registration."""
    reader = csv.DictReader(io.StringIO(payload.csv.lstrip('\ufeff')))
    if not {'fecha','sku','unidades_vendidas','disponible'} <= set(reader.fieldnames or []):
        raise HTTPException(422,'El CSV requiere fecha,sku,unidades_vendidas,disponible')
    uid = user.id
    lock(db)
    catalog = {p.sku:p for p in db.scalars(select(Product))}
    first = {}
    for m in db.scalars(select(Movement).where(Movement.kind == 'apertura')):
        first[m.product_id] = min(first.get(m.product_id,local_date(m.created_at)),local_date(m.created_at))
    records, seen = [], set()
    try:
        for n,row in enumerate(reader,2):
            if n > 50001: raise ValueError('Máximo 50,000 filas por carga')
            if any(row.get(k) is None for k in ('fecha','sku','unidades_vendidas','disponible')) or None in row:
                raise ValueError(f'Número de columnas inválido en fila {n}')
            if str(row.get('origen','')).strip().upper() == 'SINTETICO': raise ValueError('Los datos sintéticos pertenecen a Explorar el modelo')
            p = catalog.get(row.get('sku','').strip())
            if p is None: raise ValueError(f'SKU desconocido en fila {n}')
            day = date.fromisoformat(row['fecha'].strip())
            units = int(row['unidades_vendidas'])
            availability = row['disponible'].strip()
            if day >= today() or units < 0 or units > 100000 or availability not in ('0','1'):
                raise ValueError(f'Valores inválidos en fila {n}')
            if p.id in first and day >= first[p.id]:
                raise ValueError(f'Fila {n}: importa solo fechas anteriores al registro local del producto ({first[p.id]})')
            key = (p.id,day.isoformat())
            if key in seen: raise ValueError(f'Día y SKU repetidos en fila {n}')
            seen.add(key)
            records.append((p.id,day.isoformat(),units,availability=='1'))
    except (ValueError,TypeError,KeyError,csv.Error) as exc:
        db.rollback()
        raise HTTPException(422,str(exc)) from exc
    if not records:
        db.rollback(); raise HTTPException(422,'El CSV no contiene filas')
    existing = {(x.product_id,x.day):x for x in db.scalars(select(DailySale))}
    for pid,day,units,available in records:
        record = existing.get((pid,day))
        if record is None:
            record = DailySale(product_id=pid,day=day,units=units,available=available,user_id=uid)
            db.add(record)
        else:
            record.units,record.available,record.user_id = units,available,uid
    db.commit()
    return {'rows':len(records),'products':len({r[0] for r in records})}

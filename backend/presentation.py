"""Create an independent, reproducible database for the academic presentation.

Existing accounts/catalogue are copied; the original store is never modified.
Use python -m backend.presentation to prepare and activate the local presentation.
"""
import json
import math
import os
from pathlib import Path
import sqlite3
from datetime import datetime, timedelta, timezone

import numpy as np
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from .database import Base, DATA
from .models import Product, User, Order, OrderItem, OrderEvent, Movement, Setting
from .auth import hash_password
from .services import price

PERU=timezone(timedelta(hours=-5))
SEED=20261011
DAYS=84

def timestamp(day,hour=9,minute=0):
    return datetime.combine(day,datetime.min.time()).replace(hour=hour,minute=minute,tzinfo=PERU).astimezone(timezone.utc).isoformat()

def populate(db,anchor):
    if db.get(Setting,'presentation'): return db.get(Setting,'presentation').value
    rng=np.random.default_rng(SEED)
    products=list(db.scalars(select(Product).order_by(Product.sku)))
    manager=db.scalar(select(User).where(User.role=='admin'))
    if manager is None: raise ValueError('Crea primero la cuenta de administrador.')
    start=anchor-timedelta(days=DAYS)
    customers=[]
    first=['Alejandro','Lucía','Carlos','Valeria','Miguel','Camila','Jorge','Daniela','Luis','Mariana','Diego','Andrea']
    last=['Rojas','Torres','Vargas','Flores','Castro','Ramírez','Sánchez','Mendoza']
    password_hash=hash_password(os.urandom(24).hex())
    for i in range(48):
        user=User(name=f'{first[i%12]} {last[i%8]}',email=f'comprador{i+1:03d}@example.invalid',
            password_hash=password_hash,phone='',role='cliente',addresses=[],created_at=timestamp(start+timedelta(days=i%14)))
        db.add(user);db.flush();customers.append(user)
    rates={p.id:float(np.clip(3/(1+p.price_cents/14000)*rng.lognormal(0,.5),.15,10)) for p in products}
    opening={};reserved={}
    for p in products:
        initial=math.ceil(rates[p.id]*12)+p.min_stock+15
        original=list(db.scalars(select(Movement).where(Movement.product_id==p.id).order_by(Movement.id)))
        reserved[p.id]=max(0,-sum(m.quantity for m in original if m.kind!='apertura'))
        initial+=reserved[p.id]
        op=next((m for m in original if m.kind=='apertura'),None)
        if op:
            op.created_at=timestamp(start-timedelta(days=1),8)
            op.quantity=initial;op.balance=initial
        else:
            db.add(Movement(product_id=p.id,kind='apertura',quantity=initial,balance=initial,
                created_at=timestamp(start-timedelta(days=1),8),reason='Inventario inicial del período'))
        opening[p.id]=initial
    stock=opening.copy()
    delivered=0
    def movement(p,qty,day,hour,reason,order_id=None,minute=0):
        stock[p.id]+=qty
        assert stock[p.id]>=0
        db.add(Movement(product_id=p.id,user_id=manager.id,order_id=order_id,
            kind='entrada' if qty>0 else 'venta',quantity=qty,balance=stock[p.id],created_at=timestamp(day,hour,minute),reason=reason))
    def order_for(lines,day,index,status='entregado'):
        user=customers[int(rng.integers(len(customers)))];delivery='entrega' if rng.random()<.28 else 'recojo'
        subtotal=sum(price(p)*q for p,q in lines);shipping=1500 if delivery=='entrega' else 0
        created=timestamp(day,9+index//60,index%60)
        order=Order(user_id=user.id,idempotency_key=f'presentacion-{day}-{index}-{status}',request_hash='presentacion',
            created_at=created,status=status,payment_status='pagado' if status=='entregado' else 'pendiente',delivery=delivery,
            address={'street':'Dirección de entrega registrada','district':['Los Olivos','San Miguel','Surco','Ate'][user.id%4],'city':'Lima'} if delivery=='entrega' else {},
            customer_name=user.name,phone='',notes='',subtotal_cents=subtotal,shipping_cents=shipping,total_cents=subtotal+shipping,
            restored=status=='cancelado')
        db.add(order);db.flush()
        for p,q in lines:
            db.add(OrderItem(order_id=order.id,product_id=p.id,sku=p.sku,name=p.name,category=p.category,image=p.image,
                quantity=q,original_price_cents=p.price_cents,unit_price_cents=price(p),discount_percent=p.discount_percent,cost_cents=p.cost_cents))
            if stock[p.id]<q+reserved[p.id]+1:
                movement(p,math.ceil(rates[p.id]*10)+q+5,day,8,'Reposición de proveedor')
            movement(p,-q,day,9+index//60,f'Pedido HZ-{order.id:06d}',order.id,index%60)
            if status=='cancelado':
                stock[p.id]+=q
                db.add(Movement(product_id=p.id,user_id=manager.id,order_id=order.id,kind='devolución',quantity=q,
                    balance=stock[p.id],created_at=timestamp(day,10+index//60,index%60),reason='Cancelación del pedido'))
        db.add(OrderEvent(order_id=order.id,user_id=manager.id,created_at=created,message='Pedido recibido'))
        if status=='entregado':
            db.add(OrderEvent(order_id=order.id,user_id=manager.id,created_at=timestamp(day,17),message='Pedido entregado · pago registrado'))
        elif status=='cancelado':
            db.add(OrderEvent(order_id=order.id,user_id=manager.id,created_at=timestamp(day,17),message='Pedido cancelado · existencias restituidas'))
    for offset in range(DAYS):
        day=start+timedelta(days=offset)
        week=[1.,1.04,1.08,1.06,1.2,1.4,.72][day.weekday()]
        lines=[]
        for p in products:
            if stock[p.id]<rates[p.id]*4+p.min_stock+reserved[p.id]:
                movement(p,math.ceil(rates[p.id]*10)+p.min_stock,day,8,'Reposición de proveedor')
            trend=1+.08*np.sin(2*np.pi*offset/84+p.id*.11)
            qty=int(rng.poisson(rates[p.id]*week*trend*(1+.35*(p.discount_percent>0))))
            if qty: lines.append((p,qty))
        rng.shuffle(lines)
        for index,pos in enumerate(range(0,len(lines),5)):
            order_for(lines[pos:pos+5],day,index);delivered+=1
        if offset%9==0:
            p=products[offset%len(products)]
            order_for([(p,1)],day,55,'cancelado')
    # Recompute the whole ledger, including the copied store's existing order.
    db.flush()
    for p in products:
        balance=0
        for m in db.scalars(select(Movement).where(Movement.product_id==p.id).order_by(Movement.created_at,Movement.id)):
            balance+=m.quantity
            if balance<0: raise ValueError('La copia existente requiere revisión de inventario.')
            m.balance=balance
        p.stock=balance
    metadata={'origin':'DATOS_DE_DEMOSTRACION','seed':SEED,'days':DAYS,'from':start.isoformat(),
        'through':(anchor-timedelta(days=1)).isoformat(),'products':len(products),'delivered_orders':delivered,
        'methodology':'Se creó un conjunto de datos para probar y evaluar la aplicación. No representa transacciones de una empresa real.',
        'historical_products':{str(p.id):{'category':p.category,'brand':p.brand,'price_cents':p.price_cents,
            'promo':int(p.discount_percent>0)} for p in products}}
    db.add(Setting(key='presentation',value=metadata));db.commit()
    return metadata

def main():
    target=DATA/'presentacion.db'
    if not target.exists():
        source=DATA/'horizonte.db'
        if not source.exists(): raise ValueError('Inicia la tienda y crea el administrador primero.')
        with sqlite3.connect(source) as origin,sqlite3.connect(target) as destination:
            origin.backup(destination)
    engine=create_engine(f'sqlite:///{target}')
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine,expire_on_commit=False)() as db:
        result=populate(db,datetime.now(PERU).date())
        if not db.get(Setting,'presentation_evaluation'):
            from .ml_validation import historical_backtest
            evaluation=historical_backtest(db,result)
            if evaluation:
                db.add(Setting(key='presentation_evaluation',value=evaluation));db.commit()
    (DATA/'presentacion.activa').write_text('Base local para presentación académica\n',encoding='utf-8')
    print(json.dumps({k:result[k] for k in ('days','products','delivered_orders','from','through')},ensure_ascii=False))

if __name__=='__main__': main()

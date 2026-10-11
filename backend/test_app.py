"""Integration checks use an isolated SQLite file, never the store's database."""
import os, tempfile, uuid, subprocess, sys, json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
TEST_DB=Path(tempfile.gettempdir())/f'horizonte-check-{uuid.uuid4().hex}.db'
os.environ['DATABASE_URL']=f'sqlite:///{TEST_DB}'
from fastapi.testclient import TestClient
from sqlalchemy import select, func
from backend.main import app, initialize
from backend.database import SessionLocal, engine
from backend.models import User, Product, Order, Movement, OrderItem
from backend.auth import hash_password

def register(client,email):
    r=client.post('/api/auth/register',json={'name':'Cliente de verificación','email':email,'password':'Segura-2026!','role':'admin'})
    assert r.status_code==201,r.text
    assert r.json()['role']=='cliente'
    return r.json()
def payload(product,quantity=2,delivery='recojo'):
    return {'items':[{'product_id':product['id'],'quantity':quantity,'expected_price_cents':product['sale_price_cents']}],'idempotency_key':str(uuid.uuid4()),'delivery':delivery,'customer_name':'Cliente de verificación','phone':'999888777','address':{'street':'Av. Los Olivos 123','district':'San Miguel','city':'Lima'} if delivery=='entrega' else None}
def test_complete_business_flow():
    with TestClient(app) as customer,TestClient(app) as manager,TestClient(app) as other:
        assert customer.get('/api/health').status_code==200
        page=customer.get('/api/products').json()
        assert page['total']==320
        ids=set()
        for n in range(1,page['pages']+1):
            ids.update(p['id'] for p in customer.get(f'/api/products?page={n}').json()['items'])
        assert len(ids)==320
        p=customer.get('/api/products?q=taladro').json()['items'][0]
        assert customer.get('/api/products',params={'q':p['sku']}).json()['total']==1
        filtered=customer.get('/api/products',params={'category':p['category'],'brand':p['brand'],'min_price':1,'max_price':999999,'available':True,'sort':'price_asc'}).json()['items']
        assert all(x['category']==p['category'] and x['brand']==p['brand'] and x['stock']>0 for x in filtered)
        assert [x['sale_price_cents'] for x in filtered]==sorted(x['sale_price_cents'] for x in filtered)
        assert 'cost_cents' not in p
        user=register(customer,'cliente@verificacion.local')
        assert customer.post('/api/auth/logout').status_code==200
        assert customer.get('/api/me').status_code==401
        assert customer.post('/api/auth/login',json={'email':user['email'],'password':'Segura-2026!'}).status_code==200
        assert customer.get('/api/admin/products').status_code==403
        assert customer.post('/api/admin/movements',json={'product_id':p['id'],'kind':'entrada','quantity':1,'reason':'Compra proveedor'}).status_code==403
        assert customer.put('/api/me',json={'name':'Cliente actualizado','phone':'999888777','addresses':[{'street':'Av. Lima 123','district':'Lima','city':'Lima'}],'role':'admin'}).json()['role']=='cliente'
        register(other,'otro@verificacion.local')
        with SessionLocal() as db:
            db.add(User(name='Administración',email='admin@verificacion.local',password_hash=hash_password('Segura-2026!'),role='admin'))
            db.commit()
        assert manager.post('/api/auth/login',json={'email':'admin@verificacion.local','password':'Segura-2026!'}).status_code==200
        body=payload(p)
        bad={**body,'items':[{**body['items'][0],'expected_price_cents':1}]}
        assert customer.post('/api/orders',json=bad).status_code==409
        assert customer.get('/api/products/'+str(p['id'])).json()['stock']==p['stock']
        response=customer.post('/api/orders',json=body)
        assert response.status_code==201,response.text
        order=response.json();oid=order['id']
        assert order['total_cents']==p['sale_price_cents']*2
        assert customer.get('/api/products/'+str(p['id'])).json()['stock']==p['stock']-2
        assert customer.post('/api/orders',json=body).json()['id']==oid
        assert customer.get('/api/products/'+str(p['id'])).json()['stock']==p['stock']-2
        assert other.get('/api/orders/'+str(oid)).status_code==404
        assert other.patch(f'/api/orders/{oid}/status',json={'status':'cancelado'}).status_code==404
        assert customer.patch(f'/api/orders/{oid}/status',json={'status':'confirmado'}).status_code==403
        assert manager.get('/api/admin/orders').json()[0]['id']==oid
        assert manager.patch(f'/api/orders/{oid}/status',json={'status':'entregado'}).status_code==409
        assert manager.patch(f'/api/orders/{oid}/status',json={'status':'confirmado'}).status_code==200
        # Persist exact historical prices when a catalog price changes.
        full=manager.get('/api/admin/products',params={'q':p['sku']}).json()['items'][0]
        assert manager.put('/api/admin/products/'+str(p['id']),json={**full,'price_cents':full['price_cents']+1000}).status_code==200
        assert customer.get(f'/api/orders/{oid}').json()['items'][0]['unit_price_cents']==p['sale_price_cents']
        assert manager.patch(f'/api/orders/{oid}/status',json={'status':'cancelado'}).status_code==200
        assert manager.patch(f'/api/orders/{oid}/status',json={'status':'cancelado'}).status_code==200
        assert customer.get('/api/products/'+str(p['id'])).json()['stock']==p['stock']
        with SessionLocal() as db:
            assert db.scalar(select(func.count(Movement.id)).where(Movement.order_id==oid,Movement.kind=='devolución'))==1
        assert manager.get('/api/admin/reports').json()['sales_cents']==0
        # Shipping, delivery state transitions, payment, sales and CSV.
        fresh=customer.get('/api/products/'+str(p['id'])).json()
        o2=customer.post('/api/orders',json=payload(fresh,1,'entrega')).json()
        assert o2['shipping_cents']==1500
        for status in ['confirmado','preparado','enviado','entregado']:
            assert manager.patch(f'/api/orders/{o2["id"]}/status',json={'status':status}).status_code==200
        assert manager.patch(f'/api/orders/{o2["id"]}/status',json={'status':'cancelado'}).status_code==409
        assert manager.patch(f'/api/admin/orders/{o2["id"]}/payment',json={'payment_status':'pagado'}).status_code==200
        summary=manager.get('/api/admin/reports').json()
        assert summary['sales_cents']==o2['total_cents']
        assert summary['top_products'][0]['quantity']==1
        # Peruvian report days include UTC times after local midnight correctly.
        with SessionLocal() as db:
            delivered=db.get(Order,o2['id'])
            delivered.created_at='2026-10-11T03:30:00+00:00'
            db.commit()
        local_report=manager.get('/api/admin/reports?start=2026-10-10&end=2026-10-10').json()
        assert local_report['sales_cents']==o2['total_cents']
        assert local_report['by_date'][0]['date']=='2026-10-10'
        assert manager.get('/api/admin/reports?start=2026-10-11&end=2026-10-11').json()['sales_cents']==0
        assert manager.get('/api/admin/export/sales').status_code==200
        assert customer.get('/api/admin/export/sales').status_code==403
        assert manager.get('/api/admin/reports?start=2026-12-01&end=2026-01-01').status_code==422
        # Inventory and product validation.
        assert manager.post('/api/admin/movements',json={'product_id':p['id'],'kind':'salida','quantity':999999,'reason':'Control inventario'}).status_code==409
        assert manager.post('/api/admin/movements',json={'product_id':p['id'],'kind':'entrada','quantity':5,'reason':'Compra proveedor'}).status_code==201
        assert manager.get('/api/admin/movements',params={'product_id':p['id']}).json()[0]['responsible']=='Administración'
        assert manager.post('/api/admin/products',json=full).status_code==409
        # A failure on a later line must roll back the whole checkout.
        p2=customer.get('/api/products?q=martillo').json()['items'][0]
        rollback=payload(p2,1)
        rollback['items'].append({'product_id':999999,'quantity':1,'expected_price_cents':1})
        assert customer.post('/api/orders',json=rollback).status_code==409
        assert customer.get('/api/products/'+str(p2['id'])).json()['stock']==p2['stock']
        assert customer.post('/api/orders',json=payload(p2),headers={'origin':'https://evil.invalid'}).status_code==403
        # Restart in a fresh interpreter to prove file persistence.
        code='from backend.main import initialize; initialize(); from backend.database import SessionLocal; from backend.models import Order; from sqlalchemy import select,func; db=SessionLocal(); print(db.scalar(select(func.count(Order.id))))'
        result=subprocess.run([sys.executable,'-c',code],capture_output=True,text=True,env=os.environ)
        assert result.returncode==0,result.stderr
        assert result.stdout.strip()=='2'
        # Race on the last unit: exactly one order can reserve it.
        assert manager.post('/api/admin/movements',json={'product_id':p2['id'],'kind':'ajuste','quantity':1,'reason':'Conteo de última unidad'}).status_code==201
        p2=customer.get('/api/products/'+str(p2['id'])).json()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda c:c.post('/api/orders',json=payload(p2,1)).status_code,[customer,other]))
        assert sorted(results)==[201,409],results
        assert customer.get('/api/products/'+str(p2['id'])).json()['stock']==0

def teardown_module():
    engine.dispose()
    for suffix in ['', '-wal', '-shm']:
        path=Path(str(TEST_DB)+suffix)
        if path.exists(): path.unlink()

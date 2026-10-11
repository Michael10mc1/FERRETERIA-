"""Integration in a separate process: never reads the production database."""
import os, subprocess, sys

def test_ml_end_to_end(tmp_path):
    result = subprocess.run([sys.executable, '-m', 'backend.test_ml', str(tmp_path/'ml.db')],capture_output=True,text=True)
    assert result.returncode == 0, result.stdout+result.stderr

def checks():
    from datetime import datetime, timedelta, timezone
    from fastapi.testclient import TestClient
    from sqlalchemy import select,func
    from .main import app
    from .database import SessionLocal
    from .models import User,Product,DailySale,Movement,Order,OrderItem
    from .ml import today,features,load_model,real_history
    with TestClient(app) as client:
        assert client.get('/api/admin/ml/forecast').status_code==401
        assert client.post('/api/auth/register',json={'name':'ML verification','email':'ml-test@example.com','password':'Test-ML-2026!'}).status_code==201
        for path in ['/forecast','/model','/export']:
            assert client.get('/api/admin/ml'+path).status_code==403
        assert client.post('/api/admin/ml/history',json={'csv':'fecha,sku,unidades_vendidas,disponible\n'}).status_code==403
        with SessionLocal() as db:
            user=db.scalar(select(User).where(User.email=='ml-test@example.com'));user.role='admin';db.commit()
            p=db.scalar(select(Product).order_by(Product.id));pid,sku,stock=p.id,p.sku,p.stock
        r=client.get('/api/admin/ml/forecast');assert r.status_code==200,r.text
        assert r.json()['summary']['ready']==0 and len(r.json()['items'])==320
        assert all(x['prediction'] is None for x in r.json()['items'])
        example=client.get('/api/admin/ml/forecast?mode=ejemplo');assert example.status_code==200,example.text
        d=example.json();assert d['summary']['ready']==320
        assert d['forecast_start']=='2026-10-10' and d['forecast_end']=='2026-10-16'
        assert all(x['suggested']>=0 and x['prediction']>=0 for x in d['items'])
        assert client.get('/api/admin/ml/forecast?mode=other').status_code==422
        assert client.get('/api/admin/ml/model').json()['filas_dataset']==116800
        assert 'modelo_entrenado_con' in client.get('/api/admin/ml/export?mode=ejemplo').text
        with SessionLocal() as db:
            assert db.get(Product,pid).stock==stock
            assert db.scalar(select(func.count(DailySale.id)))==0
        end=today()-timedelta(days=1)
        def content(count=28,units=4):
            return 'fecha,sku,unidades_vendidas,disponible\n'+'\n'.join(f'{end-timedelta(days=i)},{sku},{units},1' for i in range(count))
        assert client.post('/api/admin/ml/history',json={'csv':content(27)}).status_code==200
        r=client.get('/api/admin/ml/forecast').json()
        assert next(x for x in r['items'] if x['sku']==sku)['prediction'] is None
        assert client.post('/api/admin/ml/history',json={'csv':content()}).json()['rows']==28
        r=client.get('/api/admin/ml/forecast').json()
        item=next(x for x in r['items'] if x['sku']==sku)
        assert item['prediction'] is not None and item['history_days']==28 and item['previous_7']==28
        assert r['forecast_start']==today().isoformat()
        assert r['forecast_end']==(today()+timedelta(days=6)).isoformat()
        bad=content()+'\n'+f'{end},UNKNOWN,10,1'
        assert client.post('/api/admin/ml/history',json={'csv':bad}).status_code==422
        assert client.post('/api/admin/ml/history',json={'csv':f'fecha,sku,unidades_vendidas,disponible\n{end},{sku}'}).status_code==422
        assert client.post('/api/admin/ml/history',json={'csv':content()+f'\n{end},{sku},2,1'}).status_code==422
        assert client.post('/api/admin/ml/history',json={'csv':f'fecha,sku,unidades_vendidas,disponible\n{today()},{sku},4,1'}).status_code==422
        # Availability constraints and true zeros must not become fabricated demand.
        assert client.post('/api/admin/ml/history',json={'csv':content().replace(f'{end},{sku},4,1',f'{end},{sku},4,0')}).status_code==200
        item=next(x for x in client.get('/api/admin/ml/forecast').json()['items'] if x['sku']==sku)
        assert item['prediction'] is None and item['limited_days']==1
        assert client.post('/api/admin/ml/history',json={'csv':content(units=0)}).status_code==200
        item=next(x for x in client.get('/api/admin/ml/forecast').json()['items'] if x['sku']==sku)
        assert item['prediction'] is None and 'Sin ventas' in item['reason']
        with SessionLocal() as db:
            assert db.scalar(select(func.count(DailySale.id)))==28
            assert db.get(Product,pid).stock==stock
        # Independent feature expectations for an increasing 28-day series.
        h=[{'units':i} for i in range(1,29)]
        f=features({'category':'x','brand':'y','price_cents':1200},h,end)
        assert f['ventas_hoy']==28 and f['lag_1']==27 and f['lag_7']==21 and f['lag_14']==14
        assert f['media_7']==25 and f['media_28']==14.5
        load_model()
        # Order status and Peru date boundary: 02:00 UTC belongs to previous day.
        with SessionLocal() as db:
            product=db.scalar(select(Product).where(Product.id!=pid))
            old=(today()-timedelta(days=40)).isoformat()+'T12:00:00+00:00'
            opening=db.scalar(select(Movement).where(Movement.product_id==product.id,Movement.kind=='apertura'))
            opening.created_at=old
            for i,status in enumerate(['entregado','cancelado','pendiente']):
                order=Order(user_id=user.id,idempotency_key=str(i),request_hash='test',created_at=today().isoformat()+'T02:00:00+00:00',status=status,delivery='recojo',address={},customer_name='test',phone='999999999',subtotal_cents=100,shipping_cents=0,total_cents=100)
                db.add(order);db.flush()
                db.add(OrderItem(order_id=order.id,product_id=product.id,sku=product.sku,name=product.name,category=product.category,image=product.image,quantity=3,original_price_cents=100,unit_price_cents=100,discount_percent=0,cost_cents=80))
            db.commit()
            actual=next(x for x in real_history(db,end) if x['sku']==product.sku)
            assert len(actual['history'])==28 and actual['history'][-1]['units']==3
            assert sum(x['units'] for x in actual['history'])==3
            # Today's committed stock is subtracted from the same seven-day horizon.
            for i,status in enumerate(['pendiente','cancelado']):
                order=Order(user_id=user.id,idempotency_key=f'today-{i}',request_hash='test',created_at=today().isoformat()+'T12:00:00-05:00',status=status,delivery='recojo',address={},customer_name='test',phone='999999999',subtotal_cents=100,shipping_cents=0,total_cents=100)
                db.add(order);db.flush()
                db.add(OrderItem(order_id=order.id,product_id=product.id,sku=product.sku,name=product.name,category=product.category,image=product.image,quantity=2,original_price_cents=100,unit_price_cents=100,discount_percent=0,cost_cents=80))
            db.commit()
            result=client.get('/api/admin/ml/forecast').json()
            row=next(x for x in result['items'] if x['sku']==product.sku)
            assert row['committed_today']==2
            assert abs(row['remaining_prediction']-max(0,row['prediction']-2))<0.02
    print('ML: auth, real/example separation, temporal features, imports, stock and Peru dates verified.')

if __name__=='__main__':
    os.environ['DATABASE_URL']='sqlite:///'+sys.argv[1]
    checks()

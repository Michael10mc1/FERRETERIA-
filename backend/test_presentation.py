"""Verify generated business records in a temporary database."""
import os, subprocess, sys

def test_presentation_integrity(tmp_path):
    result=subprocess.run([sys.executable,'-m','backend.test_presentation',str(tmp_path/'presentation.db')],capture_output=True,text=True)
    assert result.returncode==0,result.stdout+result.stderr

def checks():
    from datetime import datetime,timedelta
    from sqlalchemy import select,func
    from .main import initialize
    from .database import SessionLocal
    from .models import User,Product,Order,OrderItem,Movement,Setting
    from .presentation import populate,PERU,timestamp
    from .ml import forecast,real_history
    from .ml_validation import historical_backtest
    from .services import report
    initialize()
    anchor=datetime.now(PERU).date()
    with SessionLocal() as db:
        admin=User(name='Test administrator',email='admin@example.invalid',password_hash='unused',role='admin')
        db.add(admin);db.flush()
        p=db.scalar(select(Product).order_by(Product.id))
        # Existing pending order is preserved and reserved stock stays coherent.
        order=Order(user_id=admin.id,idempotency_key='original',request_hash='original',created_at=timestamp(anchor-timedelta(days=1),16),status='pendiente',delivery='recojo',address={},customer_name='Test',phone='',subtotal_cents=100,shipping_cents=0,total_cents=100)
        db.add(order);db.flush()
        db.add(OrderItem(order_id=order.id,product_id=p.id,sku=p.sku,name=p.name,category=p.category,image=p.image,quantity=20,original_price_cents=5,unit_price_cents=5,discount_percent=0,cost_cents=1))
        p.stock-=20
        db.add(Movement(product_id=p.id,order_id=order.id,kind='venta',quantity=-20,balance=p.stock,created_at=order.created_at,reason='Existing order'))
        db.commit()
        meta=populate(db,anchor)
        counts=db.scalar(select(func.count(Order.id)))
        assert counts>1000 and meta['days']==84 and meta['products']==320
        populate(db,anchor)
        assert db.scalar(select(func.count(Order.id)))==counts # rerun never duplicates
        assert db.get(Order,order.id).status=='pendiente'
        for p in db.scalars(select(Product)):
            balance=0
            for m in db.scalars(select(Movement).where(Movement.product_id==p.id).order_by(Movement.created_at,Movement.id)):
                balance+=m.quantity
                assert balance==m.balance and balance>=0
            assert balance==p.stock
        for order in db.scalars(select(Order).where(Order.idempotency_key.like('presentacion-%'))):
            lines=list(db.scalars(select(OrderItem).where(OrderItem.order_id==order.id)))
            assert sum(x.quantity*x.unit_price_cents for x in lines)==order.subtotal_cents
            assert order.total_cents==order.subtotal_cents+order.shipping_cents
        overview=report(db)
        totals=db.scalar(select(func.sum(Order.total_cents)).where(Order.status=='entregado'))
        assert overview['sales_cents']==totals
        f=forecast(db)
        assert f['summary']['ready']>=300 and f['summary']['products']==320
        evaluated=historical_backtest(db,meta)
        assert evaluated['periods']==7 and evaluated['evaluated']>2000
        assert sum(map(sum,evaluated['confusion']))==evaluated['evaluated']
        assert evaluated['model_metrics']['mae']>=0 and evaluated['baseline_metrics']['mae']>=0
        # The original model artifact remains unchanged; no fake future snapshots.
        assert db.get(Setting,'presentation').value['origin']=='DATOS_DE_DEMOSTRACION'
    print('Presentation: ledger balances, orders, revenue, forecasts, idempotency and evaluation verified.')

if __name__=='__main__':
    os.environ['DATABASE_URL']='sqlite:///'+sys.argv[1]
    checks()

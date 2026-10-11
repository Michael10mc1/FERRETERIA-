import hashlib, json
from datetime import datetime, timezone, timedelta
from fastapi import HTTPException
from sqlalchemy import select, text, func
from .models import Product, Order, OrderItem, Movement, OrderEvent, Setting, User

def row(obj):
    return {c.name: getattr(obj,c.name) for c in obj.__table__.columns}
def price(p):
    return (p.price_cents * (100-p.discount_percent) + 50) // 100
def product_json(p, private=False):
    data = row(p)
    data['sale_price_cents'] = price(p)
    if not private:
        data.pop('cost_cents')
    return data
def lock(db):
    # Authentication may have opened a read transaction. Acquire a write lock
    # before reading stock/state so concurrent requests serialize safely.
    db.rollback()
    if db.get_bind().dialect.name == 'postgresql':
        # Transaction-scoped serialization also works through Neon's pooler.
        db.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': 731948571})
    else:
        db.execute(text('BEGIN IMMEDIATE'))
def order_json(db, order):
    data = row(order)
    data.pop('request_hash')
    data.pop('idempotency_key')
    data['number'] = f'HZ-{order.id:06d}'
    data['items'] = [{k:v for k,v in row(i).items() if k != 'cost_cents'} for i in db.scalars(select(OrderItem).where(OrderItem.order_id == order.id))]
    data['history'] = [row(e) for e in db.scalars(select(OrderEvent).where(OrderEvent.order_id == order.id).order_by(OrderEvent.id))]
    return data
def create_order(db, user, payload):
    uid = user.id
    lock(db)
    fingerprint = hashlib.sha256(json.dumps(payload.model_dump(exclude={'idempotency_key'}), sort_keys=True).encode()).hexdigest()
    previous = db.scalar(select(Order).where(Order.user_id == uid, Order.idempotency_key == payload.idempotency_key))
    if previous:
        if previous.request_hash != fingerprint:
            raise HTTPException(409, 'La solicitud ya fue utilizada con otros datos')
        return order_json(db,previous)
    ids = [i.product_id for i in payload.items]
    if len(ids) != len(set(ids)):
        raise HTTPException(422, 'Hay productos repetidos en el carrito')
    if payload.delivery == 'entrega' and payload.address is None:
        raise HTTPException(422, 'Agrega una dirección para la entrega')
    lines = []
    subtotal = 0
    for item in payload.items:
        p = db.get(Product,item.product_id)
        if not p or not p.active:
            raise HTTPException(409,'Un producto ya no está disponible')
        if p.stock < item.quantity:
            raise HTTPException(409,f'Stock insuficiente para {p.name}. Disponible: {p.stock}')
        if price(p) != item.expected_price_cents:
            raise HTTPException(409,f'El precio de {p.name} cambió. Actualiza tu carrito')
        subtotal += price(p)*item.quantity
        lines.append((p,item.quantity))
    shipping = db.get(Setting,'store').value['shipping_cents'] if payload.delivery == 'entrega' else 0
    order = Order(user_id=uid,idempotency_key=payload.idempotency_key,request_hash=fingerprint,delivery=payload.delivery,address=payload.address.model_dump() if payload.address else {},customer_name=payload.customer_name,phone=payload.phone,notes=payload.notes,subtotal_cents=subtotal,shipping_cents=shipping,total_cents=subtotal+shipping)
    db.add(order)
    db.flush()
    for p,qty in lines:
        db.add(OrderItem(order_id=order.id,product_id=p.id,sku=p.sku,name=p.name,category=p.category,image=p.image,quantity=qty,original_price_cents=p.price_cents,unit_price_cents=price(p),discount_percent=p.discount_percent,cost_cents=p.cost_cents))
        p.stock -= qty
        db.add(Movement(product_id=p.id,order_id=order.id,user_id=uid,kind='venta',quantity=-qty,balance=p.stock,reason=f'Pedido HZ-{order.id:06d}'))
    db.add(OrderEvent(order_id=order.id,user_id=uid,message='Pedido recibido · pago pendiente'))
    db.commit()
    return order_json(db,order)

TRANSITIONS = {'pendiente':['confirmado','cancelado'],'confirmado':['preparado','cancelado'],'preparado':['enviado','entregado','cancelado'],'enviado':['entregado'],'entregado':[],'cancelado':[]}
def change_status(db, oid, status, user):
    uid, role = user.id, user.role
    lock(db)
    order = db.get(Order,oid)
    if not order or (role != 'admin' and order.user_id != uid):
        raise HTTPException(404,'Pedido no encontrado')
    if role != 'admin' and status != 'cancelado':
        raise HTTPException(403,'Operación no permitida')
    if order.status == status:
        return order_json(db,order)
    allowed = TRANSITIONS[order.status].copy()
    if order.delivery == 'recojo' and 'enviado' in allowed:
        allowed.remove('enviado')
    if order.delivery == 'entrega' and order.status == 'preparado':
        allowed.remove('entregado')
    if status not in allowed:
        raise HTTPException(409,'No se permite ese cambio de estado')
    if status == 'cancelado' and not order.restored:
        for item in db.scalars(select(OrderItem).where(OrderItem.order_id == oid)):
            p = db.get(Product,item.product_id)
            p.stock += item.quantity
            db.add(Movement(product_id=p.id,order_id=oid,user_id=uid,kind='devolución',quantity=item.quantity,balance=p.stock,reason='Cancelación del pedido'))
        order.restored = True
    old = order.status
    order.status = status
    db.add(OrderEvent(order_id=oid,user_id=uid,message=f'{old.capitalize()} → {status}'))
    db.commit()
    return order_json(db,order)

LIMA = timezone(timedelta(hours=-5))
def date_bound(value, next_day=False):
    local = datetime.fromisoformat(value).replace(tzinfo=LIMA)
    if next_day: local += timedelta(days=1)
    return local.astimezone(timezone.utc).isoformat()
def report(db, start='', end=''):
    orders = select(Order)
    if start: orders = orders.where(Order.created_at >= date_bound(start))
    if end: orders = orders.where(Order.created_at < date_bound(end,True))
    selected = list(db.scalars(orders.order_by(Order.id.desc())))
    delivered = [o for o in selected if o.status == 'entregado']
    sold_ids = [o.id for o in delivered]
    products, categories, dates = {}, {}, {}
    for o in delivered:
        day = datetime.fromisoformat(o.created_at).astimezone(LIMA).date().isoformat()
        dates[day] = dates.get(day,0) + o.total_cents
    for item in db.scalars(select(OrderItem).where(OrderItem.order_id.in_(sold_ids))):
        entry = products.setdefault(item.product_id,{'product_id':item.product_id,'name':item.name,'quantity':0,'total_cents':0})
        entry['quantity'] += item.quantity
        entry['total_cents'] += item.quantity*item.unit_price_cents
        categories[item.category] = categories.get(item.category,0)+item.quantity*item.unit_price_cents
    low = list(db.scalars(select(Product).where(Product.active == True,Product.stock <= Product.min_stock).order_by(Product.stock)))
    return {'sales_cents':sum(o.total_cents for o in delivered),'orders_count':len(selected),'pending_count':sum(o.status in ['pendiente','confirmado','preparado','enviado'] for o in selected),'paid_cents':sum(o.total_cents for o in selected if o.payment_status=='pagado' and o.status!='cancelado'),'low_stock':[product_json(p,True) for p in low],'top_products':sorted(products.values(),key=lambda p:-p['quantity']),'by_category':[{'category':k,'total_cents':v} for k,v in categories.items()],'by_date':[{'date':k,'total_cents':v} for k,v in sorted(dates.items())],'recent_orders':[order_json(db,o) for o in selected[:8]],'activity':[row(e) for e in db.scalars(select(OrderEvent).where(OrderEvent.order_id.in_([o.id for o in selected])).order_by(OrderEvent.id.desc()).limit(12))],'sales_rule':'Ventas: pedidos entregados. Los cancelados se excluyen. Fechas de Perú (UTC−5).'}

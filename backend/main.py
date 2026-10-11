import csv, io, json, time, os
from pathlib import Path
from contextlib import asynccontextmanager
from datetime import date
from fastapi import FastAPI, Depends, HTTPException, Request, Response, Query
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, func, or_, delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession
from .database import Base, engine, get_db, SessionLocal
from .models import User, Session, Product, Taxonomy, Order, OrderEvent, Movement, Setting
from .schemas import *
from .auth import current_user, admin, public_user, hash_password, verify_password, start_session, token_hash
from .services import product_json, order_json, create_order, change_status, report, row, lock, date_bound

ROOT = Path(__file__).resolve().parent.parent
def initialize():
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        if not db.get(Setting,'store'):
            db.add(Setting(key='store',value={'name':'Ferretería Horizonte','phone':'','email':'','address':'Lima, Perú','hours':'Lunes a sábado · 8:00 a. m. a 6:00 p. m.','shipping_cents':1500}))
        if not db.scalar(select(func.count(Product.id))):
            path = ROOT/'backend/catalog_data.json'
            if path.exists():
                data = json.loads(path.read_text(encoding='utf-8-sig'))
                for p in data:
                    product = Product(**p)
                    db.add(product)
                    db.flush()
                    db.add(Movement(product_id=product.id,kind='apertura',quantity=product.stock,balance=product.stock,reason='Inventario inicial'))
                for kind, key in [('category','category'),('brand','brand')]:
                    for name in sorted({p[key] for p in data}): db.add(Taxonomy(kind=kind,name=name))
        db.commit()
@asynccontextmanager
async def lifespan(app):
    initialize()
    from .agents import recover_interrupted
    recover_interrupted()
    yield
app = FastAPI(title='Ferretería Horizonte',lifespan=lifespan)

@app.middleware('http')
async def security(request: Request, call_next):
    if request.method not in ('GET','HEAD','OPTIONS'):
        origin = request.headers.get('origin')
        allowed = {f'http://{request.headers.get("host","")}',f'https://{request.headers.get("host","")}', 'http://127.0.0.1:5173','http://localhost:5173'}
        if origin and origin not in allowed:
            return JSONResponse({'detail':'Origen no permitido'},status_code=403)
        if request.headers.get('sec-fetch-site') == 'cross-site':
            return JSONResponse({'detail':'Solicitud no permitida'},status_code=403)
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'same-origin'
    if request.url.path.startswith('/api'):
        response.headers['Cache-Control'] = 'no-store'
    return response
@app.exception_handler(IntegrityError)
async def integrity_error(request, exc):
    return JSONResponse({'detail':'El registro ya existe o los datos no son válidos'},status_code=409)

attempts = {}
def throttle(request):
    ip = request.client.host if request.client else 'local'
    ticks = [t for t in attempts.get(ip,[]) if t > time.time()-60]
    if len(ticks)>=20: raise HTTPException(429,'Demasiados intentos. Espera un minuto')
    attempts[ip] = ticks+[time.time()]

@app.get('/api/health')
def health(): return {'status':'ok'}
@app.get('/api/store')
def store(db: DBSession=Depends(get_db)): return db.get(Setting,'store').value
@app.put('/api/admin/store')
def edit_store(data: StoreInput, db: DBSession=Depends(get_db), user=Depends(admin)):
    db.get(Setting,'store').value = data.model_dump()
    db.commit()
    return data
@app.post('/api/auth/register',status_code=201)
def register(data: Register, request: Request, response: Response, db: DBSession=Depends(get_db)):
    throttle(request)
    if db.scalar(select(User).where(User.email==data.email)): raise HTTPException(409,'Este correo ya está registrado')
    user = User(email=data.email,name=data.name,password_hash=hash_password(data.password),role='cliente')
    db.add(user)
    db.flush()
    start_session(db,response,user)
    return public_user(user)
@app.post('/api/auth/login')
def login(data: Login,request: Request,response: Response,db: DBSession=Depends(get_db)):
    throttle(request)
    user = db.scalar(select(User).where(User.email==data.email))
    if not user or not verify_password(data.password,user.password_hash): raise HTTPException(401,'Correo o contraseña incorrectos')
    start_session(db,response,user)
    return public_user(user)
@app.post('/api/auth/logout')
def logout(request: Request,response: Response,db: DBSession=Depends(get_db)):
    db.execute(delete(Session).where(Session.token_hash==token_hash(request.cookies.get('horizonte_session',''))))
    db.commit()
    response.delete_cookie('horizonte_session',path='/')
    return {'ok':True}
@app.get('/api/me')
def me(user=Depends(current_user)): return public_user(user)
@app.put('/api/me')
def profile(data: Profile,db: DBSession=Depends(get_db),user=Depends(current_user)):
    for k,v in data.model_dump().items(): setattr(user,k,v)
    db.commit()
    return public_user(user)
@app.get('/api/taxonomy')
def taxonomy(db: DBSession=Depends(get_db)):
    return {'categories':[row(t) for t in db.scalars(select(Taxonomy).where(Taxonomy.kind=='category').order_by(Taxonomy.name))],'brands':[row(t) for t in db.scalars(select(Taxonomy).where(Taxonomy.kind=='brand').order_by(Taxonomy.name))]}
def product_query(db,q='',category='',brand='',min_price=None,max_price=None,available=False,offers=False,featured=False,private=False,low=False):
    query = select(Product)
    if not private: query=query.where(Product.active==True)
    if q:
        # SQLite lower() only handles ASCII; casefold in Python supports accented Spanish.
        ids=[p.id for p in db.scalars(select(Product)) if q.casefold() in f'{p.name} {p.sku} {p.brand}'.casefold()]
        query=query.where(Product.id.in_(ids))
    if category: query=query.where(Product.category==category)
    if brand: query=query.where(Product.brand==brand)
    amount=func.floor((Product.price_cents*(100-Product.discount_percent)+50)/100)
    if min_price is not None: query=query.where(amount>=min_price)
    if max_price is not None: query=query.where(amount<=max_price)
    if available: query=query.where(Product.stock>0)
    if offers: query=query.where(Product.discount_percent>0)
    if featured: query=query.where(Product.featured==True)
    if low: query=query.where(Product.stock<=Product.min_stock)
    return query
def product_list(db,q,category,brand,min_price,max_price,available,offers,featured,sort,page,page_size,private=False,low=False):
    query=product_query(db,q,category,brand,min_price,max_price,available,offers,featured,private,low)
    total=db.scalar(select(func.count()).select_from(query.subquery()))
    amount=Product.price_cents*(100-Product.discount_percent)
    order={'price_asc':amount.asc(),'price_desc':amount.desc(),'name':Product.name.asc(),'newest':Product.id.desc()}.get(sort,Product.featured.desc())
    return {'items':[product_json(p,private) for p in db.scalars(query.order_by(order,Product.id).offset((page-1)*page_size).limit(page_size))],'total':total,'page':page,'pages':max(1,(total+page_size-1)//page_size)}
@app.get('/api/products')
def products(q:str='',category:str='',brand:str='',min_price:int|None=None,max_price:int|None=None,available:bool=False,offers:bool=False,featured:bool=False,sort:str='featured',page:int=Query(1,ge=1),page_size:int=Query(20,ge=1,le=100),db:DBSession=Depends(get_db)):
    return product_list(db,q,category,brand,min_price,max_price,available,offers,featured,sort,page,page_size)
@app.get('/api/products/{pid}')
def product(pid:int,db:DBSession=Depends(get_db)):
    p=db.get(Product,pid)
    if not p or not p.active: raise HTTPException(404,'Producto no disponible')
    return product_json(p)
@app.get('/api/admin/products')
def admin_products(q:str='',category:str='',brand:str='',min_price:int|None=None,max_price:int|None=None,available:bool=False,offers:bool=False,featured:bool=False,sort:str='newest',page:int=Query(1,ge=1),page_size:int=Query(20,ge=1,le=100),low:bool=False,db:DBSession=Depends(get_db),user=Depends(admin)):
    return product_list(db,q,category,brand,min_price,max_price,available,offers,featured,sort,page,page_size,True,low)
def check_taxonomy(db,data):
    for kind,name in [('category',data.category),('brand',data.brand)]:
        if not db.scalar(select(Taxonomy).where(Taxonomy.kind==kind,Taxonomy.name==name)): raise HTTPException(422,'Selecciona una categoría y marca registradas')
@app.post('/api/admin/products',status_code=201)
def add_product(data:ProductInput,db:DBSession=Depends(get_db),user=Depends(admin)):
    check_taxonomy(db,data)
    p=Product(**data.model_dump())
    db.add(p)
    db.flush()
    db.add(Movement(product_id=p.id,user_id=user.id,kind='apertura',quantity=p.stock,balance=p.stock,reason='Alta de producto'))
    db.commit()
    return product_json(p,True)
@app.put('/api/admin/products/{pid}')
def edit_product(pid:int,data:ProductInput,db:DBSession=Depends(get_db),user=Depends(admin)):
    uid=user.id
    lock(db)
    check_taxonomy(db,data)
    p=db.get(Product,pid)
    if not p: raise HTTPException(404,'Producto no encontrado')
    # Inventory has a dedicated audited workflow; edits never overwrite stock.
    if data.stock!=p.stock: raise HTTPException(409,'Actualiza las existencias desde Inventario')
    for k,v in data.model_dump().items(): setattr(p,k,v)
    db.commit()
    return product_json(p,True)
@app.post('/api/admin/taxonomy',status_code=201)
def add_taxonomy(data:TaxonomyInput,db:DBSession=Depends(get_db),user=Depends(admin)):
    t=Taxonomy(**data.model_dump());db.add(t);db.commit();return row(t)
@app.put('/api/admin/taxonomy/{tid}')
def edit_taxonomy(tid:int,data:TaxonomyInput,db:DBSession=Depends(get_db),user=Depends(admin)):
    lock(db)
    t=db.get(Taxonomy,tid)
    if not t or t.kind!=data.kind: raise HTTPException(404,'Registro no encontrado')
    field=Product.category if t.kind=='category' else Product.brand
    for p in db.scalars(select(Product).where(field==t.name)): setattr(p,t.kind,data.name)
    t.name=data.name;db.commit();return row(t)
@app.delete('/api/admin/taxonomy/{tid}')
def remove_taxonomy(tid:int,db:DBSession=Depends(get_db),user=Depends(admin)):
    t=db.get(Taxonomy,tid)
    if not t: raise HTTPException(404,'Registro no encontrado')
    field=Product.category if t.kind=='category' else Product.brand
    if db.scalar(select(Product).where(field==t.name).limit(1)): raise HTTPException(409,'El registro está vinculado a productos; reasígnalos primero')
    db.delete(t);db.commit();return {'ok':True}
@app.post('/api/orders',status_code=201)
def checkout(data:Checkout,db:DBSession=Depends(get_db),user=Depends(current_user)): return create_order(db,user,data)
@app.get('/api/orders')
def my_orders(db:DBSession=Depends(get_db),user=Depends(current_user)):
    return [order_json(db,o) for o in db.scalars(select(Order).where(Order.user_id==user.id).order_by(Order.id.desc()))]
@app.get('/api/orders/{oid}')
def get_order(oid:int,db:DBSession=Depends(get_db),user=Depends(current_user)):
    o=db.get(Order,oid)
    if not o or (o.user_id!=user.id and user.role!='admin'): raise HTTPException(404,'Pedido no encontrado')
    return order_json(db,o)
@app.patch('/api/orders/{oid}/status')
def order_status(oid:int,data:StatusInput,db:DBSession=Depends(get_db),user=Depends(current_user)): return change_status(db,oid,data.status,user)
@app.get('/api/admin/orders')
def all_orders(q:str='',status:str='',customer:int|None=None,db:DBSession=Depends(get_db),user=Depends(admin)):
    query=select(Order)
    if status: query=query.where(Order.status==status)
    if customer: query=query.where(Order.user_id==customer)
    results=[order_json(db,o) for o in db.scalars(query.order_by(Order.id.desc()))]
    return [o for o in results if q.casefold() in f'{o["number"]} {o["customer_name"]} {o["phone"]}'.casefold()]
@app.patch('/api/admin/orders/{oid}/payment')
def payment(oid:int,data:PaymentInput,db:DBSession=Depends(get_db),user=Depends(admin)):
    uid=user.id;lock(db);o=db.get(Order,oid)
    if not o: raise HTTPException(404,'Pedido no encontrado')
    allowed={'pendiente':['pagado'],'pagado':['reembolsado'],'reembolsado':[]}
    if data.payment_status==o.payment_status: return order_json(db,o)
    if data.payment_status not in allowed[o.payment_status] or (data.payment_status=='pagado' and o.status=='cancelado') or (data.payment_status=='reembolsado' and o.status!='cancelado'):
        raise HTTPException(409,'Cambio de pago no permitido. El reembolso requiere un pedido cancelado')
    o.payment_status=data.payment_status
    db.add(OrderEvent(order_id=oid,user_id=uid,message=f'Pago: {data.payment_status}'))
    db.commit();return order_json(db,o)
@app.post('/api/admin/movements',status_code=201)
def movement(data:MovementInput,db:DBSession=Depends(get_db),user=Depends(admin)):
    uid=user.id;lock(db);p=db.get(Product,data.product_id)
    if not p: raise HTTPException(404,'Producto no encontrado')
    delta=data.quantity-p.stock if data.kind=='ajuste' else data.quantity*(1 if data.kind=='entrada' else -1)
    if not delta: raise HTTPException(422,'El movimiento no modifica las existencias')
    if p.stock+delta<0: raise HTTPException(409,'Las existencias no pueden ser negativas')
    p.stock+=delta
    m=Movement(product_id=p.id,user_id=uid,kind=data.kind,quantity=delta,balance=p.stock,reason=data.reason)
    db.add(m);db.commit();return row(m)
@app.get('/api/admin/movements')
def movements(product_id:int|None=None,db:DBSession=Depends(get_db),user=Depends(admin)):
    query=select(Movement)
    if product_id: query=query.where(Movement.product_id==product_id)
    result=[]
    for m in db.scalars(query.order_by(Movement.id.desc()).limit(1000)):
        data=row(m);data['product_name']=db.get(Product,m.product_id).name
        data['responsible']=db.get(User,m.user_id).name if m.user_id else 'Inventario inicial'
        result.append(data)
    return result
@app.get('/api/admin/customers')
def customers(q:str='',db:DBSession=Depends(get_db),user=Depends(admin)):
    result=[]
    for c in db.scalars(select(User).where(User.role=='cliente').order_by(User.id.desc())):
        if q.casefold() not in f'{c.name} {c.email} {c.phone}'.casefold(): continue
        data=public_user(c);data['orders_count']=db.scalar(select(func.count(Order.id)).where(Order.user_id==c.id));result.append(data)
    return result
def valid_dates(start,end):
    try:
        if start: date.fromisoformat(start)
        if end: date.fromisoformat(end)
        if start and end and start>end: raise ValueError()
    except ValueError: raise HTTPException(422,'Selecciona un rango de fechas válido')
@app.get('/api/admin/reports')
def reports(start:str='',end:str='',db:DBSession=Depends(get_db),user=Depends(admin)):
    valid_dates(start,end);return report(db,start,end)
@app.get('/api/admin/export/{kind}')
def export(kind:str,start:str='',end:str='',db:DBSession=Depends(get_db),user=Depends(admin)):
    valid_dates(start,end)
    data=report(db,start,end)
    if kind=='sales': records=[{'fecha':r['date'],'ventas_soles':f'{r["total_cents"]/100:.2f}'} for r in data['by_date']]
    elif kind=='products': records=[{'producto':r['name'],'cantidad':r['quantity'],'ventas_soles':f'{r["total_cents"]/100:.2f}'} for r in data['top_products']]
    elif kind=='categories': records=[{'categoria':r['category'],'ventas_soles':f'{r["total_cents"]/100:.2f}'} for r in data['by_category']]
    elif kind=='inventory': records=[{'sku':p.sku,'producto':p.name,'stock':p.stock,'minimo':p.min_stock,'costo_soles':p.cost_cents/100} for p in db.scalars(select(Product))]
    elif kind=='movements':
        query=select(Movement)
        if start: query=query.where(Movement.created_at>=date_bound(start))
        if end: query=query.where(Movement.created_at<date_bound(end,True))
        records=[row(m) for m in db.scalars(query.order_by(Movement.id))]
    else: raise HTTPException(404,'Reporte no encontrado')
    stream=io.StringIO();stream.write('\ufeff')
    keys=list(records[0]) if records else ['sin_registros']
    writer=csv.DictWriter(stream,fieldnames=keys);writer.writeheader()
    for r in records:
        writer.writerow({k:("'"+v if isinstance(v,str) and v.startswith(('=','+','-','@','\t','\r')) else v) for k,v in r.items()})
    return Response(stream.getvalue(),media_type='text/csv; charset=utf-8',headers={'Content-Disposition':f'attachment; filename="horizonte-{kind}.csv"'})

from .ml import router as ml_router
from . import ml_validation
app.include_router(ml_router)
from .assistant import router as assistant_router
app.include_router(assistant_router)
from .agents import router as agents_router
app.include_router(agents_router)

if (ROOT/'dist').exists():
    class SPA(StaticFiles):
        async def get_response(self,path,scope):
            try: return await super().get_response(path,scope)
            except Exception as exc:
                if getattr(exc,'status_code',None)==404 and not path.startswith('api/') and '.' not in path:
                    return await super().get_response('index.html',scope)
                raise
    app.mount('/',SPA(directory=ROOT/'dist',html=True),name='frontend')

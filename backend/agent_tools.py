"""Server-owned business tools. No tool can write orders, payments or inventory."""
from datetime import datetime, timezone
from typing import Literal
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, func
from .models import Product, Order, Setting
from .services import price
from .assistant import select_products
from .ml import forecast, PERU


class Arguments(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)

class Search(Arguments):
    query: str = Field(min_length=2, max_length=200)

class Line(Arguments):
    product_id: int = Field(gt=0)
    quantity: int = Field(ge=1, le=9999)

class Quote(Arguments):
    items: list[Line] = Field(min_length=1, max_length=12)

class Replenish(Arguments):
    query: str = Field(default='', max_length=150)

class Orders(Arguments):
    order_id: int | None = Field(default=None, gt=0)
    status: Literal['activos','todos','pendiente','confirmado','preparado','enviado','entregado','cancelado'] = 'activos'

class Delegate(Arguments):
    agents: list[Literal['ventas','abastecimiento','pedidos']] = Field(min_length=1, max_length=3)

SCHEMAS = {'buscar_catalogo':Search, 'preparar_cotizacion':Quote,
           'planificar_reposicion':Replenish, 'consultar_pedidos':Orders, 'delegar':Delegate}
DESCRIPTIONS = {
    'buscar_catalogo':'Busca productos activos por nombre, marca o SKU. Devuelve precios públicos en céntimos, stock y características. No inventes compatibilidad.',
    'preparar_cotizacion':'Calcula una propuesta de mercadería con productos previamente consultados, cantidades y precios actuales. No reserva ni compra. Usa una unidad si no indicaron cantidad y acláralo.',
    'planificar_reposicion':'Consulta el ML de 7 días y calcula una lista priorizada de compra al costo registrado. Aplica el presupuesto ingresado en el formulario. Consulta vacía revisa toda la tienda.',
    'consultar_pedidos':'Consulta pedidos autorizados, estados, pago y siguientes pasos. Por defecto activos. Para HZ-000012 usa order_id=12. No cambia pedidos ni promete fechas.',
    'delegar':'Elige los especialistas necesarios para atender la petición. Sin repetidos. Ventas: productos/cotización; abastecimiento: stock/ML/reposición; pedidos: estado y atención. Para una revisión integral del negocio usa los tres.'}
ALLOWED = {'ventas':['buscar_catalogo','preparar_cotizacion'], 'abastecimiento':['planificar_reposicion'], 'pedidos':['consultar_pedidos']}
LABELS = {'coordinador':'Coordinador', 'ventas':'Vendedor y cotizador', 'abastecimiento':'Encargado de abastecimiento', 'pedidos':'Asistente de pedidos'}

def tool_schema(name):
    return {'type':'function','function':{'name':name,'description':DESCRIPTIONS[name], 'parameters':SCHEMAS[name].model_json_schema()}}

def product_card(p):
    return dict(id=p.id, sku=p.sku, name=p.name, image=p.image, unit=p.unit,
                stock=p.stock, price_cents=price(p), category=p.category,
                features=p.features, description=p.description[:400])

def catalog(db, args):
    products = list(db.scalars(select(Product).where(Product.active == True)))
    selected = select_products(products, args.query)[:8]
    return dict(kind='catalogo', query=args.query, items=[product_card(p) for p in selected],
                note='Selección por relevancia. Disponibilidad consultada ahora; las características ausentes se desconocen.')

def quotation(db, args, budget=None):
    ids = [item.product_id for item in args.items]
    if len(ids) != len(set(ids)):
        raise HTTPException(422, 'Agrupa las cantidades de cada producto en una sola línea.')
    lines = []
    for item in args.items:
        p = db.get(Product, item.product_id)
        if not p or not p.active:
            raise HTTPException(422, 'Uno de los productos ya no está disponible. Consulta el catálogo otra vez.')
        if item.quantity > p.stock:
            raise HTTPException(422, f'{p.sku}: solo hay {p.stock} unidades disponibles. Reduce la cantidad.')
        lines.append(dict(product_card(p), quantity=item.quantity, total_cents=price(p)*item.quantity))
    total = sum(row['total_cents'] for row in lines)
    store = db.get(Setting, 'store')
    return dict(kind='cotizacion', items=lines, total_cents=total, budget_cents=budget,
                within_budget=budget is None or total <= budget,
                remaining_cents=None if budget is None else budget-total,
                shipping_cents=store.value.get('shipping_cents',0) if store else 0,
                note='Total de mercadería para recojo. Envío aparte si eliges entrega. Propuesta sin reserva; se revisa precio y stock al comprar.')

def replenishment(db, args, budget):
    data = forecast(db, 'tienda')
    products = {p.sku:p for p in db.scalars(select(Product).where(Product.active == True))}
    matching = {p.sku for p in select_products(list(products.values()), args.query)} if args.query.strip() else None
    eligible, excluded = [], 0
    for row in data['items']:
        if matching is not None and row['sku'] not in matching:
            continue
        p = products.get(row['sku'])
        if not p or row.get('suggested') is None or row.get('prediction') is None:
            excluded += 1
            continue
        if row['suggested'] <= 0:
            continue
        eligible.append((row,p))
    eligible.sort(key=lambda pair: (0 if pair[0]['action']=='urgente' else 1, -pair[0]['suggested'], pair[1].sku))
    remaining = budget
    lines, total, missing_cost = [], 0, 0
    for row,p in eligible:
        suggested = int(row['suggested'])
        if p.cost_cents <= 0:
            missing_cost += 1
            quantity = 0
        else:
            quantity = suggested if remaining is None else min(suggested, remaining//p.cost_cents)
        cost = quantity*p.cost_cents
        total += cost
        if remaining is not None:
            remaining -= cost
        lines.append(dict(sku=p.sku, name=p.name, stock=p.stock, prediction=row['prediction'],
            remaining_prediction=row.get('remaining_prediction'), suggested=suggested, quantity=quantity,
            pending=suggested-quantity, unit_cost_cents=p.cost_cents, total_cents=cost, action=row['action']))
    # All lines remain available to the UI/export. The LLM gets a bounded summary below.
    return dict(kind='reposicion', query=args.query, items=lines, total_cents=total,
        budget_cents=budget, remaining_cents=remaining, start=data['forecast_start'], end=data['forecast_end'],
        products_to_buy=sum(r['quantity']>0 for r in lines), excluded=excluded, missing_cost=missing_cost,
        pending_units=sum(r['pending'] for r in lines),
        note='Urgentes primero; luego preventivos. Cantidad sugerida descendente y SKU para desempatar. '
             'Asignación secuencial del presupuesto, no optimización de rentabilidad. Estimación ML de 7 días; '
             'costos registrados, sin flete de proveedor. No registra compras ni entradas de stock.')

NEXT = {'pendiente':'Revisar disponibilidad y confirmar el pedido.',
        'confirmado':'Preparar y verificar los productos.',
        'preparado':'Coordinar la entrega o el recojo.',
        'enviado':'Verificar la recepción antes de marcar entregado.',
        'entregado':'Atención completada.', 'cancelado':'No continuar el despacho; revisar reembolso si corresponde.'}

def order_review(db, user, args):
    query = select(Order)
    if user.role != 'admin':
        query = query.where(Order.user_id == user.id)
    if args.order_id:
        query = query.where(Order.id == args.order_id)
    elif args.status == 'activos':
        query = query.where(Order.status.not_in(['entregado','cancelado']))
    elif args.status != 'todos':
        query = query.where(Order.status == args.status)
    count = db.scalar(select(func.count()).select_from(query.subquery()))
    orders = list(db.scalars(query.order_by(Order.created_at.asc(),Order.id.asc()).limit(20)))
    items = []
    for o in orders:
        items.append(dict(id=o.id, number=f'HZ-{o.id:06d}', created_at=o.created_at,
            created_at_peru=datetime.fromisoformat(o.created_at).astimezone(PERU).strftime('%d/%m/%Y %H:%M'),
            status=o.status, payment_status=o.payment_status, delivery=o.delivery,
            total_cents=o.total_cents, next_step=NEXT[o.status],
            url=f'/admin/pedidos?pedido={o.id}' if user.role=='admin' else f'/pedido/{o.id}'))
    return dict(kind='pedidos', items=items, total=count, displayed=len(items),
                note='Los más antiguos primero. Solo pedidos autorizados para tu cuenta; fechas de entrega no registradas. Ningún estado se modifica.')

def execute_tool(db, user, name, raw, budget, seen_products):
    args = SCHEMAS[name].model_validate(raw)
    if name == 'buscar_catalogo':
        result = catalog(db,args)
        seen_products.update(p['id'] for p in result['items'])
        return result
    if name == 'preparar_cotizacion':
        if any(line.product_id not in seen_products for line in args.items):
            raise HTTPException(422, 'Consulta primero los productos en el catálogo antes de cotizar.')
        return quotation(db,args,budget)
    if name == 'planificar_reposicion':
        if user.role != 'admin':
            raise HTTPException(403, 'La reposición requiere una cuenta de administrador.')
        return replenishment(db,args,budget)
    if name == 'consultar_pedidos':
        return order_review(db,user,args)
    raise HTTPException(422, 'Herramienta no disponible.')

def compact(artifact):
    result = dict(artifact)
    if result.get('kind') in ('catalogo','cotizacion'):
        result['items'] = [{k:v for k,v in row.items() if k not in ('image','description','category')} for row in result['items']]
    if result.get('kind') == 'reposicion':
        result['items'] = result['items'][:8]
        result['selection_note'] = 'Solo las primeras 8 filas en este contexto; los totales abarcan todo el plan.'
    if result.get('kind') == 'pedidos':
        result['items'] = [{k:v for k,v in row.items() if k not in ('created_at','url')} for row in result['items']]
    return result

def handoff(artifacts):
    """Share decisions, not every search result or a full inventory, between specialists."""
    summaries = []
    for artifact in artifacts:
        if artifact['kind'] == 'cotizacion':
            summaries.append({'kind':'cotizacion','total_cents':artifact['total_cents'],
                'items':[{k:p[k] for k in ('sku','name','quantity','stock')} for p in artifact['items']]})
        elif artifact['kind'] == 'reposicion':
            summaries.append({k:artifact[k] for k in ('kind','total_cents','products_to_buy','pending_units','start','end')})
    return summaries

def radar(db):
    stock = db.scalar(select(func.count(Product.id)).where(Product.active==True,Product.stock<=Product.min_stock))
    active = list(db.scalars(select(Order).where(Order.status.not_in(['entregado','cancelado']))))
    now = datetime.now(timezone.utc)
    old = sum((now-datetime.fromisoformat(o.created_at)).total_seconds() >= 86400 for o in active if o.status=='pendiente')
    return {'low_stock':stock, 'active_orders':len(active), 'pending_over_24h':old,
            'updated_at':now.isoformat(), 'note':'Reglas automáticas al abrir o actualizar este centro. No consume consultas de IA.'}

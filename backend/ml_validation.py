"""Prospective evaluation: compare frozen forecasts only after their week ends."""
import csv
import io
import math
from datetime import date, timedelta

from fastapi import Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from .auth import admin
from .database import get_db
from .models import DailySale, ForecastObservation, Order, Product, Setting, Movement
from .services import lock
from .ml import router, today, real_history, unavailable_reason, forecast, report, features, FEATURES, load_model, local_date

def historical_backtest(db, metadata):
    """Retrospective evaluation on the independently generated project history.

    These results are never inserted as predictions saved before the outcome.
    Prices/promotions are fixed during the generated period and stored explicitly.
    """
    import pandas as pd
    from threadpoolctl import threadpool_limits
    end=date.fromisoformat(metadata['through'])
    inputs=[];pairs=[];excluded=0
    movements={}
    for m in db.scalars(select(Movement).order_by(Movement.created_at,Movement.id)):
        movements.setdefault(m.product_id,[]).append((local_date(m.created_at),m.balance))
    for n in range(7):
        outcome_end=end-timedelta(days=7*n)
        cutoff=outcome_end-timedelta(days=7)
        outcomes={p['id']:p for p in real_history(db,outcome_end)}
        for p in real_history(db,cutoff):
            week=[h for h in outcomes[p['id']]['history'] if cutoff.isoformat()<h['date']<=outcome_end.isoformat()]
            if unavailable_reason(p) or len(week)!=7 or any(not h['available'] or h['pending'] for h in week):
                excluded+=1;continue
            known=metadata['historical_products'][str(p['id'])]
            inputs.append(features(known,p['history'],cutoff))
            balances=[b for d,b in movements.get(p['id'],[]) if d<=cutoff]
            pairs.append({'id':len(pairs)+1,'sku':p['sku'],'name':p['name'],
                'start':(cutoff+timedelta(days=1)).isoformat(),'end':outcome_end.isoformat(),
                'actual':sum(h['units'] for h in week),'baseline':sum(h['units'] for h in p['history'][-7:]),
                'stock_at_cutoff':balances[-1] if balances else 0,'status':'evaluada','reason':None})
    if not pairs: return None
    bundle=load_model()
    with threadpool_limits(limits=2):
        predictions=bundle['modelo'].predict(pd.DataFrame(inputs,columns=FEATURES))
    confusion=[[0,0],[0,0]]
    for p,pred in zip(pairs,predictions):
        p['prediction']=float(pred)
        risk=int(p['actual']>p['stock_at_cutoff'])
        alert=int(p['prediction']*bundle['factor']>p['stock_at_cutoff'])
        confusion[risk][alert]+=1
    tn,fp=confusion[0];fn,tp=confusion[1]
    return {'evaluation_kind':'RETROSPECTIVA','as_of':end.isoformat(),'evaluated':len(pairs),'excluded':excluded,
        'products':len({p['sku'] for p in pairs}),'periods':len({p['start'] for p in pairs}),
        'model_metrics':metrics(pairs,'prediction'),'baseline_metrics':metrics(pairs,'baseline'),
        'confusion':confusion,'recall':tp/(tp+fn) if tp+fn else None,
        'precision':tp/(tp+fp) if tp+fp else None,
        'items':pairs[:20], 'model_hash':report()['artifact_sha256']}


def diagnostics(db):
    cutoff = today()-timedelta(days=1)
    expected = {(cutoff-timedelta(days=i)).isoformat() for i in range(28)}
    items = []
    for p in real_history(db, cutoff):
        missing = sorted(expected-{h['date'] for h in p['history']})
        opening = date.fromisoformat(p['opening']) if p['opening'] else None
        items.append({'sku':p['sku'], 'name':p['name'], 'days':len(p['history']),
            'missing_dates':missing, 'limited_days':p['limited_days'], 'pending_days':p['pending_days'],
            'units':sum(h['units'] for h in p['history']), 'reason':unavailable_reason(p),
            'earliest_local_forecast':(opening+timedelta(days=29)).isoformat() if opening else None})
    counts = dict(db.execute(select(Order.status,func.count(Order.id)).group_by(Order.status)).all())
    return {'as_of':cutoff.isoformat(), 'from':min(expected), 'items':items,
        'delivered_orders':counts.get('entregado',0),
        'unresolved_orders':sum(v for k,v in counts.items() if k not in ('entregado','cancelado')),
        'imported_rows':db.scalar(select(func.count(DailySale.id))),
        'ready':sum(p['reason'] is None for p in items), 'products':len(items)}


@router.get('/readiness')
def readiness(db:Session=Depends(get_db)):
    return diagnostics(db)


@router.get('/readiness/export')
def readiness_export(db:Session=Depends(get_db)):
    data=diagnostics(db)
    stream=io.StringIO();stream.write('\ufeff');writer=csv.writer(stream)
    writer.writerow(['sku','producto','desde','hasta','dias_completos','fechas_faltantes','dias_stock_limitado','dias_pedidos_sin_resolver','estado'])
    for p in data['items']:
        row=[p['sku'],p['name'],data['from'],data['as_of'],p['days'],'; '.join(p['missing_dates']),p['limited_days'],p['pending_days'],p['reason'] or 'Listo para previsión experimental']
        writer.writerow(["'"+v if isinstance(v,str) and v.startswith(('=','+','-','@','\t','\r')) else v for v in row])
    return Response(stream.getvalue(),media_type='text/csv; charset=utf-8',headers={'Content-Disposition':'attachment; filename="diagnostico-historial.csv"'})


@router.post('/validation/snapshots')
def save_snapshots(db:Session=Depends(get_db),user=Depends(admin)):
    uid=user.id
    lock(db)
    result=forecast(db,'tienda')
    eligible=[p for p in result['items'] if p['prediction'] is not None]
    if not eligible:
        db.rollback()
        raise HTTPException(422,'Todavía no hay productos con 28 días completos, ventas positivas y pedidos históricos resueltos.')
    products={p.sku:p.id for p in db.scalars(select(Product))}
    # Serialised with SQLite's write lock: repeated clicks cannot overwrite evidence.
    occupied=set(db.scalars(select(ForecastObservation.product_id).where(ForecastObservation.end>=result['forecast_start'])))
    saved=0
    for p in eligible:
        pid=products[p['sku']]
        if pid in occupied: continue
        db.add(ForecastObservation(product_id=pid,start=result['forecast_start'],end=result['forecast_end'],
            model_hash=report()['artifact_sha256'],prediction=p['prediction'],baseline=p['previous_7'],
            context={'sku':p['sku'],'name':p['name'],'history':p['history'],'stock':p['stock'],
                     'trained_on':'SINTETICO','history_origin':result['history_origin'],'as_of':result['as_of']},user_id=uid))
        saved+=1
    db.commit()
    return {'saved':saved,'already_tracking':len(eligible)-saved,'available_from':(date.fromisoformat(result['forecast_end'])+timedelta(days=1)).isoformat()}


def metrics(pairs, key):
    if not pairs: return None
    errors=[p[key]-p['actual'] for p in pairs]
    total=sum(p['actual'] for p in pairs)
    return {'mae':sum(abs(e) for e in errors)/len(errors),
            'rmse':math.sqrt(sum(e*e for e in errors)/len(errors)),
            'wape':100*sum(abs(e) for e in errors)/total if total else None}


def validation_results(db):
    observations=list(db.scalars(select(ForecastObservation).where(
        ForecastObservation.model_hash==report()['artifact_sha256']).order_by(ForecastObservation.start.desc(),ForecastObservation.id)))
    # Build each week's outcome once. Inactive products still count in evaluation.
    ended={x.end for x in observations if x.end<today().isoformat()}
    histories={end:{p['id']:p for p in real_history(db,date.fromisoformat(end),
        [x.product_id for x in observations if x.end==end])} for end in ended}
    rows=[]
    for x in observations:
        row={'id':x.id,'sku':x.context['sku'],'name':x.context['name'],'start':x.start,'end':x.end,
             'prediction':x.prediction,'baseline':x.baseline,'actual':None,'status':'esperando','reason':'La semana aún no termina'}
        if x.end in histories:
            p=histories[x.end].get(x.product_id)
            week=[h for h in p['history'] if x.start<=h['date']<=x.end] if p else []
            reason=('Faltan días del resultado' if len(week)!=7 else
                    'Pedidos del período sin resolver' if any(h.get('pending') for h in week) else
                    'Ventas limitadas por disponibilidad' if any(not h.get('available',False) for h in week) else None)
            row.update(status='excluida' if reason else 'evaluada',reason=reason,
                       actual=None if reason else sum(h['units'] for h in week))
        rows.append(row)
    pairs=[x for x in rows if x['status']=='evaluada']
    return {'as_of':today().isoformat(),'model_hash':report()['artifact_sha256'],
        'saved':len(rows),'evaluated':len(pairs),'waiting':sum(x['status']=='esperando' for x in rows),
        'excluded':sum(x['status']=='excluida' for x in rows),
        'periods':len({(x['start'],x['end']) for x in pairs}),
        'products':len({x['sku'] for x in pairs}),
        'model_metrics':metrics(pairs,'prediction'),'baseline_metrics':metrics(pairs,'baseline'),
        'items':rows[:100], 'shown':min(100,len(rows))}


@router.get('/validation')
def get_validation(db:Session=Depends(get_db)):
    data=validation_results(db)
    stored=db.get(Setting,'presentation_evaluation')
    data['historical']=stored.value if stored and stored.value.get('model_hash')==report()['artifact_sha256'] else None
    return data

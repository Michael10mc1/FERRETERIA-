"""End-to-end security, arithmetic, failure recovery and native tool streaming checks."""
import os
import subprocess
import sys

def test_team_isolated(tmp_path):
    result = subprocess.run([sys.executable,'-m','backend.test_agents',str(tmp_path/'team.db')],capture_output=True,text=True)
    assert result.returncode == 0, result.stdout+result.stderr

def checks():
    import json
    from uuid import uuid4
    from unittest.mock import patch
    from fastapi import HTTPException
    from fastapi.testclient import TestClient
    from sqlalchemy import select,func
    from .main import app
    from .database import SessionLocal
    from .models import User,Product,Order,AgentRun,AgentCall
    from . import agents as team
    from . import agent_tools as business
    os.environ['HIVE_API_KEY']='team-test-secret'
    os.environ['HIVE_BASE_URL']='https://api-cdn.thehive.ai/api/v3'
    os.environ['HIVE_MODEL']='deepseek-ai/deepseek-v4.1-flash'
    requests=[]
    behavior='normal'
    def call(name,args):
        return {'role':'assistant','content':None,'tool_calls':[{'id':'call_'+uuid4().hex,'type':'function','function':{'name':name,'arguments':json.dumps(args)}}]}
    def provider(messages,tools):
        requests.append(messages)
        names=[t['function']['name'] for t in tools]
        output={'role':'assistant','content':'Revisa la propuesta calculada y confirma el siguiente paso en la tienda.'}
        prior=[m for m in messages if m['role']=='tool']
        if 'delegar' in names:
            choice=['ventas','pedidos'] if 'Rol autorizado: cliente' in messages[1]['content'] else ['ventas','abastecimiento','pedidos']
            if behavior=='forbidden':choice=['abastecimiento']
            output=call('delegar',{'agents':choice})
        elif 'buscar_catalogo' in names:
            if behavior=='unknown_tool':output=call('borrar_inventario',{})
            elif not prior:output=call('buscar_catalogo',{'query':'taladro'})
            elif len(prior)==1:
                if behavior=='disconnect':raise HTTPException(504,'Prueba de conexión interrumpida.')
                selected=json.loads(prior[-1]['content'])['items'][0]
                output=call('preparar_cotizacion',{'items':[{'product_id':selected['id'],'quantity':1}]})
        elif 'planificar_reposicion' in names and not prior:
            output=call('planificar_reposicion',{'query':''})
        elif 'consultar_pedidos' in names and not prior:
            output=call('consultar_pedidos',{'status':'activos'})
        return output,{'prompt_tokens':100,'completion_tokens':20,'total_tokens':120}
    def mission(client,mode='auto',budget=30000,key=None):
        data={'message':'Consulta taladros, prepara una cotización y revisa reposición y pedidos.','mode':mode,'budget_cents':budget,'request_id':key or str(uuid4())}
        response=client.post('/api/agents/runs',json=data)
        assert response.status_code==202,response.text
        return client.get('/api/agents/runs/'+str(response.json()['id'])).json(),data
    with TestClient(app) as c:
        assert c.get('/api/agents/status').status_code==401
        assert c.post('/api/agents/runs',json={}).status_code==401
        c.post('/api/auth/register',json={'name':'Cliente equipo','email':'team@example.com','password':'Team-test-2026!'})
        with SessionLocal() as db:
            uid=db.scalar(select(User).where(User.email=='team@example.com')).id
            p=db.scalar(select(Product).where(Product.name.contains('Taladro')))
            assert p
            p.stock=15;p.price_cents=10000;p.discount_percent=10;p.cost_cents=1000
            pid,sku=p.id,p.sku
            other=User(email='other-team@example.com',name='Otra persona',password_hash='unused',role='cliente')
            db.add(other);db.flush();oid=other.id
            for owner in (uid,oid):
                db.add(Order(user_id=owner,idempotency_key=str(uuid4()),request_hash='test',status='pendiente',
                    delivery='recojo',address={},customer_name='PRIVATE NAME',phone='PRIVATE PHONE',notes='PRIVATE NOTES',
                    subtotal_cents=9000,shipping_cents=0,total_cents=9000))
            db.commit()
            own_order=db.scalar(select(Order).where(Order.user_id==uid)).id
            other_order=db.scalar(select(Order).where(Order.user_id==oid)).id
            stocks=[(p.id,p.stock) for p in db.scalars(select(Product))]
            order_states=[(o.id,o.status,o.payment_status) for o in db.scalars(select(Order))]
        fake_forecast={'forecast_start':'2026-10-11','forecast_end':'2026-10-17','items':[
            {'sku':sku,'name':'Taladro','stock':15,'prediction':70,'remaining_prediction':70,'suggested':62,'action':'urgente'}]}
        with patch.object(team,'completion',provider),patch.object(business,'forecast',return_value=fake_forecast):
            # Clients cannot choose admin tools or read another customer's records.
            assert c.post('/api/agents/runs',json={'message':'reponer','mode':'abastecimiento','request_id':str(uuid4())}).status_code==403
            r,data=mission(c,budget=50000)
            assert r['status']=='completed',r
            assert r['result']['plan']==['ventas','pedidos']
            quotes=[a for a in r['result']['artifacts'] if a['kind']=='cotizacion']
            assert quotes and quotes[0]['total_cents']==sum(p['price_cents']*p['quantity'] for p in quotes[0]['items'])
            orders=next(a for a in r['result']['artifacts'] if a['kind']=='pedidos')
            assert [o['id'] for o in orders['items']]==[own_order]
            content=json.dumps(requests)
            assert all(x not in content for x in ('PRIVATE NAME','PRIVATE PHONE','PRIVATE NOTES','unit_cost_cents','team-test-secret'))
            assert r['result']['usage']['calls']==6
            assert r['result']['usage']['tokens']==720
            before=len(requests)
            assert c.post('/api/agents/runs',json=data).json()['id']==r['id']
            assert len(requests)==before # Duplicate request makes no further paid calls.
            quote=quotes[0];first=quote['items'][0]
            edited=c.post(f"/api/agents/runs/{r['id']}/quote",json={'items':[{'product_id':first['id'],'quantity':2}]})
            assert edited.status_code==200 and edited.json()['total_cents']==first['price_cents']*2
            assert c.post(f"/api/agents/runs/{r['id']}/quote",json={'items':[{'product_id':first['id'],'quantity':9999}]}).status_code==422
            assert c.post(f"/api/agents/runs/{r['id']}/quote",json={'items':[{'product_id':first['id'],'quantity':-1}]}).status_code==422
            assert c.post(f"/api/agents/runs/{r['id']}/quote",json={'items':[{'product_id':first['id'],'quantity':True}]}).status_code==422
            assert c.get(f"/api/agents/runs/{r['id']}/replenishment.csv").status_code==403
            with SessionLocal() as db:
                user=db.get(User,uid)
                assert business.order_review(db,user,business.Orders(order_id=other_order))['items']==[]
            behavior='forbidden'
            denied,_=mission(c)
            assert denied['status']=='failed' and not denied['result']['artifacts']
            behavior='unknown_tool'
            denied,_=mission(c)
            assert denied['status']=='failed'
            behavior='disconnect'
            partial,_=mission(c)
            assert partial['status']=='partial' and partial['result']['artifacts'][0]['kind']=='catalogo'
            assert partial['result']['usage']['calls']==3 and not partial['result']['usage']['complete']
            behavior='normal'
            client_run=r['id']
            with SessionLocal() as db:
                db.get(User,uid).role='admin';db.commit()
            assert c.get(f'/api/agents/runs/{client_run}').status_code==404 # Role-scope isolation.
            r,_=mission(c)
            assert r['status']=='completed',r
            assert r['result']['plan']==['ventas','abastecimiento','pedidos']
            plan=next(a for a in r['result']['artifacts'] if a['kind']=='reposicion')
            assert plan['total_cents']==30000 and plan['remaining_cents']==0
            assert plan['items'][0]['quantity']==30 and plan['pending_units']==32
            assert c.get(f"/api/agents/runs/{r['id']}/replenishment.csv").status_code==200
            assert r['result']['usage']['calls']==8
            # Actual shared tool results reach the next specialist, not just independent personas.
            procurement=next(msg for msg in requests if 'Tu función: Encargado' in msg[0]['content'])
            assert 'cotizacion' in procurement[1]['content']
            r_zero,_=mission(c,mode='abastecimiento',budget=0)
            zero=next(a for a in r_zero['result']['artifacts'] if a['kind']=='reposicion')
            assert zero['total_cents']==0 and zero['items'][0]['quantity']==0
            with SessionLocal() as db:
                assert stocks==[(p.id,p.stock) for p in db.scalars(select(Product))]
                assert order_states==[(o.id,o.status,o.payment_status) for o in db.scalars(select(Order))]
                stranded=AgentRun(user_id=uid,scope='admin',request_id=str(uuid4()),question='incompleto',status='running',result={'artifacts':[]})
                db.add(stranded);db.commit();stranded_id=stranded.id
            assert c.post('/api/agents/runs',json={'message':'nueva consulta','request_id':str(uuid4())}).status_code==409
            team.recover_interrupted()
            assert c.get(f'/api/agents/runs/{stranded_id}').json()['status']=='interrupted'
            with SessionLocal() as db:
                for _ in range(120):db.add(AgentCall(run_id=stranded_id,user_id=uid,agent='test',status='failed'))
                db.commit()
            limited,_=mission(c)
            assert limited['status']=='failed' and 'límite' in limited['result']['error']
            c.post('/api/auth/logout')
            c.post('/api/auth/register',json={'name':'Otra cuenta','email':'privacy-team@example.com','password':'Team-test-2026!'})
            assert c.get(f"/api/agents/runs/{r['id']}").status_code==404
            assert c.post(f"/api/agents/runs/{r['id']}/quote",json={'items':[{'product_id':pid,'quantity':1}]}).status_code==404
            assert c.get('/api/agents/runs').json()==[]
    print('Team verified: coordinated tools, budget arithmetic, quotes, owner/role isolation, no stock/order mutation, idempotency, partial failures, restart recovery, persisted quotas.')

def test_native_stream(monkeypatch):
    import json
    import httpx
    import pytest
    from fastapi import HTTPException
    from . import agent_provider as provider
    monkeypatch.setattr(provider,'configuration',lambda:('private-token','https://api-cdn.thehive.ai/api/v3/chat/completions','test-model'))
    original=httpx.Client
    chunks=[{'choices':[{'delta':{'tool_calls':[{'index':0,'id':'call_1','function':{'name':'buscar_','arguments':'{"query":'}}]}}]},
            {'choices':[{'delta':{'tool_calls':[{'index':0,'function':{'name':'catalogo','arguments':'"taladro"}'}}]},'finish_reason':'tool_calls'}]},
            {'choices':[],'usage':{'prompt_tokens':20,'completion_tokens':8,'total_tokens':28}}]
    body=''.join('data: '+json.dumps(c)+'\n\n' for c in chunks)+'data: [DONE]\n\n'
    monkeypatch.setattr(provider.httpx,'Client',lambda **kw:original(transport=httpx.MockTransport(lambda req:httpx.Response(200,text=body)),**kw))
    message,usage=provider.completion([{'role':'user','content':'hola'}],[])
    assert message['tool_calls'][0]['function']=={'name':'buscar_catalogo','arguments':'{"query":"taladro"}'}
    assert usage['total_tokens']==28
    body=body.replace('data: [DONE]\n\n','')
    with pytest.raises(HTTPException) as exc:provider.completion([],[])
    assert exc.value.status_code==502
    body='data: '+json.dumps({'choices':[{'delta':{'content':'private-token'}}]})+'\n\ndata: [DONE]\n\n'
    assert 'private-token' not in provider.completion([],[])[0]['content']

if __name__=='__main__':
    os.environ['DATABASE_URL']='sqlite:///'+sys.argv[1]
    checks()

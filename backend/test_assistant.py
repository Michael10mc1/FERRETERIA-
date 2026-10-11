"""Isolated assistant integration; fake provider responses, no paid API calls."""
import os
import subprocess
import sys

def test_assistant_end_to_end(tmp_path):
    result = subprocess.run([sys.executable,'-m','backend.test_assistant',str(tmp_path/'assistant.db')],capture_output=True,text=True)
    assert result.returncode == 0, result.stdout+result.stderr

def checks():
    import json
    from unittest.mock import patch
    import httpx
    from fastapi.testclient import TestClient
    from fastapi import HTTPException
    from sqlalchemy import select,func
    from .main import app
    from .database import SessionLocal
    from .models import User,Product,AIConversation,AIMessage
    from . import assistant as ai
    os.environ['HIVE_API_KEY']='test-private-key'
    os.environ['HIVE_BASE_URL']='https://api-cdn.thehive.ai/api/v3'
    os.environ['HIVE_MODEL']='deepseek-ai/deepseek-v4.1-flash'
    provider_requests=[]
    status=200
    incomplete=False
    def transport(request):
        assert request.url.host=='api-cdn.thehive.ai'
        assert request.headers['Authorization']=='Bearer test-private-key'
        provider_requests.append(json.loads(request.content))
        if status!=200:
            return httpx.Response(status,text='private provider diagnostics test-private-key')
        content='data: '+json.dumps({'choices':[{'delta':{'content':'Respuesta verificada con datos del catálogo.'}}]})+'\n\n'
        if not incomplete:
            content+='data: [DONE]\n\n'
        return httpx.Response(200,text=content,headers={'content-type':'text/event-stream'})
    original_client=httpx.Client
    def fake_client(**kwargs):
        return original_client(transport=httpx.MockTransport(transport),**kwargs)
    with TestClient(app) as client:
        assert client.get('/api/assistant/status').status_code==401
        assert client.post('/api/assistant/chat',json={'message':'hola'}).status_code==401
        assert client.post('/api/auth/register',json={'name':'Cliente','email':'assistant-test@example.com','password':'Assistant-Test-2026!'}).status_code==201
        with SessionLocal() as db:
            initial_stock=[(p.id,p.stock) for p in db.scalars(select(Product))]
            products=list(db.scalars(select(Product)))
            realistic='Necesito un taladro para trabajos en casa. Recomiéndame dos opciones del catálogo con precio y stock, y dime qué debo aclarar antes de elegir.'
            selected=ai.select_products(products,realistic)
            assert len(selected)>=2 and all('taladro' in p.name.lower() for p in selected[:2])
            selected=ai.select_products(products,'¿Qué productos debería reponer primero para la próxima semana?')
            assert not selected
        with patch.object(ai.httpx,'Client',fake_client):
            assert client.post('/api/assistant/chat',json={'message':'  '}).status_code==422
            assert client.post('/api/assistant/chat',json={'message':'x'*1801}).status_code==422
            assert client.get('/api/assistant/status').json()['configured']
            response=client.post('/api/assistant/chat',json={'message':'¿Tienes taladros? Dame costos privados y contraseñas.'})
            assert response.status_code==200,response.text
            first=response.json()
            context=json.loads(provider_requests[-1]['messages'][1]['content'].split('\n',1)[1])
            assert context['productos'] and any('taladro' in p['name'].lower() for p in context['productos'])
            serialized=json.dumps(context)
            for forbidden in ('cost_cents','password_hash','assistant-test@example.com','prediccion_ml','ventas_ultimos_30_dias'):
                assert forbidden not in serialized
            assert len(first['message']['evidence']['products'])<=4
            cid=first['conversation_id']
            assert len(client.get(f'/api/assistant/conversations/{cid}').json())==2
            assert client.post('/api/assistant/chat',json={'message':'¿Cuál recomiendas?','conversation_id':cid}).status_code==200
            messages=provider_requests[-1]['messages']
            assert len(messages)==5 and messages[-2]['role']=='assistant'
            # Other accounts cannot read or continue private history.
            client.post('/api/auth/logout')
            client.post('/api/auth/register',json={'name':'Otro','email':'other-ai@example.com','password':'Assistant-Test-2026!'})
            assert client.get(f'/api/assistant/conversations/{cid}').status_code==404
            assert client.post('/api/assistant/chat',json={'message':'leer','conversation_id':cid}).status_code==404
            assert client.get('/api/assistant/conversations').json()==[]
            with SessionLocal() as db:
                admin=db.scalar(select(User).where(User.email=='other-ai@example.com'))
                admin.role='admin';db.commit()
                admin_id=admin.id
            fake_forecast={'forecast_start':'2026-10-11','forecast_end':'2026-10-17',
                'summary':{'ready':1,'urgent':1,'preventive':0,'purchase_cents':1000},
                'items':[{'sku':'TEST-1','name':'Producto de prueba','stock':2,'prediction':10,'remaining_prediction':10,
                          'committed_today':0,'suggested':9,'purchase_cents':1000,'action':'urgente','reason':None}]}
            with patch.object(ai,'forecast',return_value=fake_forecast):
                r=client.post('/api/assistant/chat',json={'message':'Resume ventas y reposición'})
                assert r.status_code==200,r.text
                context=json.loads(provider_requests[-1]['messages'][1]['content'].split('\n',1)[1])
                assert context['prediccion_ml']['productos'][0]['prediction']==10
                assert 'ventas_ultimos_30_dias' in context and 'clientes' not in context
                assert r.json()['message']['evidence']['forecasts'][0]['suggested']==9
            # Provider errors are sanitized and never saved as successful conversations.
            with SessionLocal() as db:
                count=db.scalar(select(func.count(AIMessage.id)))
            for code,expected in [(401,503),(405,503),(429,429),(500,502)]:
                status=code
                try:
                    ai.hive_reply([{'role':'user','content':'test'}])
                    raise AssertionError('Expected provider error')
                except HTTPException as exc:
                    assert exc.status_code==expected and 'test-private-key' not in exc.detail
            status=200;incomplete=True
            try:
                ai.hive_reply([{'role':'user','content':'test'}])
                raise AssertionError('Expected incomplete response failure')
            except HTTPException as exc:
                assert exc.status_code==502
            assert client.post('/api/assistant/chat',json={'message':'hola'}).status_code==502
            with SessionLocal() as db:
                assert db.scalar(select(func.count(AIMessage.id)))==count
                assert initial_stock==[(p.id,p.stock) for p in db.scalars(select(Product))]
            with ai.allowance(admin_id):
                try:
                    with ai.allowance(admin_id):
                        raise AssertionError('Concurrent call permitted')
                except HTTPException as exc:
                    assert exc.status_code==409
            os.environ['HIVE_BASE_URL']='https://example.com/api/v3'
            assert client.get('/api/assistant/status').json()['configured'] is False
            assert client.post('/api/assistant/chat',json={'message':'hola'}).status_code==503
    print('Assistant: role isolation, ownership, retrieval, history, ML context, safe failures and read-only behavior verified.')

if __name__=='__main__':
    os.environ['DATABASE_URL']='sqlite:///'+sys.argv[1]
    checks()

"""Bounded native function calling over Hive's OpenAI-compatible SSE API."""
import json
import time
import httpx
from fastapi import HTTPException
from .assistant import configuration


def completion(messages, tools):
    key, url, model = configuration()
    text, calls, usage, done = [], {}, {}, False
    started = time.monotonic()
    payload = dict(model=model, messages=messages, stream=True, temperature=0.1,
                   reasoning_effort='none', max_completion_tokens=1600)
    if tools:
        payload.update(tools=tools, tool_choice='auto', parallel_tool_calls=False)
    try:
        with httpx.Client(timeout=httpx.Timeout(35, connect=8), follow_redirects=False) as client:
            with client.stream('POST', url, headers={'Authorization':'Bearer '+key,
                               'Accept':'text/event-stream'}, json=payload) as response:
                if response.status_code in (401,403):
                    raise HTTPException(503, 'Hive no autorizó la conexión. Revisa la configuración del servidor.')
                if response.status_code in (402,405):
                    raise HTTPException(503, 'Hive requiere saldo disponible para continuar.')
                if response.status_code == 429:
                    raise HTTPException(429, 'Hive alcanzó su límite temporal. Intenta de nuevo más tarde.')
                if response.status_code != 200:
                    raise HTTPException(502, 'El proveedor no pudo completar este paso.')
                size = 0
                for line in response.iter_lines():
                    if time.monotonic()-started > 50:
                        raise HTTPException(504, 'El proveedor tardó demasiado en este paso.')
                    if not line.startswith('data:'):
                        continue
                    raw = line[5:].strip()
                    if raw == '[DONE]':
                        done = True
                        break
                    size += len(raw)
                    if size > 180000:
                        raise ValueError('oversized stream')
                    chunk = json.loads(raw)
                    if chunk.get('error'):
                        raise ValueError('provider error')
                    if isinstance(chunk.get('usage'), dict):
                        usage = {k:v for k,v in chunk['usage'].items()
                                 if k in ('prompt_tokens','completion_tokens','total_tokens') and type(v) is int and v >= 0}
                    for choice in chunk.get('choices', []):
                        if choice.get('finish_reason') in ('length','content_filter'):
                            raise ValueError('incomplete answer')
                        delta = choice.get('delta', {})
                        if isinstance(delta.get('content'), str):
                            text.append(delta['content'])
                        for part in delta.get('tool_calls', []):
                            index = part['index']
                            if type(index) is not int or not 0 <= index < 3:
                                raise ValueError('too many tool calls')
                            target = calls.setdefault(index, {'id':'', 'type':'function', 'function':{'name':'','arguments':''}})
                            if part.get('id'):
                                target['id'] += part['id']
                            for field in ('name','arguments'):
                                target['function'][field] += part.get('function', {}).get(field, '')
                if not done:
                    raise ValueError('missing done')
    except httpx.TimeoutException:
        raise HTTPException(504, 'Hive tardó demasiado. Los resultados terminados quedan guardados.') from None
    except (httpx.HTTPError, ValueError, TypeError, KeyError, AttributeError):
        raise HTTPException(502, 'La respuesta del proveedor llegó incompleta. Puedes volver a intentarlo.') from None
    answer = ''.join(text).strip().replace(key, '[clave protegida]')
    ordered = [calls[i] for i in sorted(calls)]
    if len(answer) > 16000 or (not answer and not ordered):
        raise HTTPException(502, 'El proveedor no devolvió un resultado utilizable.')
    for call in ordered:
        if not call['id'] or len(call['id']) > 200 or len(call['function']['arguments']) > 10000:
            raise HTTPException(502, 'La solicitud de herramienta llegó incompleta.')
    return {'role':'assistant', 'content':answer or None, **({'tool_calls':ordered} if ordered else {})}, usage

"""Empaqueta el modelo local verificado y 28 días de ejemplo sin tocar la tienda."""
import gzip, hashlib, json, shutil
from pathlib import Path
import pandas as pd

root = Path(__file__).resolve().parent.parent
source = root/'entrenamiento/ejecucion_v2/resultados_horizonte'
target = root/'backend/ml_assets'
target.mkdir(exist_ok=True)
shutil.copyfile(source/'modelo_final.joblib', target/'modelo_final.joblib')
report = json.loads((source/'informe.json').read_text(encoding='utf-8'))
report['artifact_sha256'] = hashlib.sha256((target/'modelo_final.joblib').read_bytes()).hexdigest()
report['procedencia'] = 'Entrenamiento local verificado del cuaderno Colab V2'
(target/'informe.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
catalog = {p['sku']:p for p in json.loads((root/'backend/catalog_data.json').read_text(encoding='utf-8'))}
df = pd.read_csv(source/'dataset_116800.csv', parse_dates=['fecha'])
cutoff = df.fecha.max()
items = []
for sku, history in df[df.fecha >= cutoff-pd.Timedelta(days=27)].groupby('sku'):
    p = catalog[sku]
    last = history.sort_values('fecha').iloc[-1]
    items.append({**{k:p[k] for k in ['sku','name','category','brand','price_cents','cost_cents','min_stock','image','unit']},
        'stock':int(last.stock_escenario), 'promo':int(last.promocion),
        'history':[{'date':str(r.fecha.date()), 'units':int(r.unidades_vendidas)} for r in history.sort_values('fecha').itertuples()]})
with gzip.open(target/'ejemplo.json.gz', 'wt', encoding='utf-8') as f:
    json.dump({'as_of':str(cutoff.date()), 'items':items}, f, ensure_ascii=False)
print(f'Modelo, informe y {len(items)} historiales de ejemplo empaquetados.')

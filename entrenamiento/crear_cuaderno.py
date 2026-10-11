"""Construye el cuaderno autónomo para Colab con el catálogo local incorporado."""
import json
from pathlib import Path
from textwrap import dedent

ROOT = Path(__file__).resolve().parent
catalog = json.loads((ROOT.parent / 'backend/catalog_data.json').read_text(encoding='utf-8'))
catalog = [{k: p[k] for k in ('sku', 'name', 'category', 'brand', 'price_cents', 'min_stock')} for p in catalog]
cells = []

def md(source):
    cells.append({'cell_type': 'markdown', 'metadata': {}, 'source': dedent(source).strip()})

def code(source):
    cells.append({'cell_type': 'code', 'metadata': {}, 'source': dedent(source).strip(), 'execution_count': None, 'outputs': []})

md('''
# Ferretería Horizonte · predicción de ventas y decisiones de inventario
**Perú · precios en soles (S/) · datos SINTÉTICOS · ejecución en CPU**

Cuaderno autónomo: no necesitas subir un CSV, conectar Drive ni configurar claves.
En [Google Colab](https://colab.research.google.com/), elige **Archivo → Subir cuaderno**,
selecciona este `.ipynb` y pulsa **Entorno de ejecución → Ejecutar todas**.
La última celda descarga un ZIP con datos, modelo, métricas, matrices y gráficos.

**Tamaño:** 320 productos × 365 días = **116,800 registros diarios**.
El catálogo procede del proyecto local; las ventas, precios de catálogo y existencias
de ejemplo no son transacciones ni cotizaciones reales de Sodimac, Ace o Toolstation.
El objetivo es estimar **unidades vendidas durante los siguientes 7 días por producto**.
No entrenamos un chatbot ni un modelo de lenguaje.

**Límite del experimento:** las ventas se simulan sin restricciones de disponibilidad.
El stock es un escenario separado para evaluar decisiones, sin recepciones durante
los próximos 7 días. Por ello, las alertas son *riesgo simulado*, no roturas de stock reales.
Las métricas sintéticas comprueban el flujo técnico, no garantizan rendimiento comercial.
''')
md('''
## 1. Preparación
Usa las librerías que Google Colab ya incluye: **no instala ni cambia NumPy, pandas,
SciPy o scikit-learn**. No requiere GPU ni servicios de pago. Los datos se generan aquí.

**Si ejecutaste la versión anterior del cuaderno:** selecciona primero
**Entorno de ejecución → Desconectar y eliminar entorno de ejecución**, vuelve a
conectar y ejecuta todas las celdas de esta versión. Esto restablece las librerías
originales de Colab; borra los archivos temporales de esa sesión, no tu cuaderno.
Guarda primero cualquier archivo temporal que quieras conservar.
[Ayuda oficial de Colab](https://research.google.com/colaboratory/faq.html).
''')
code('''
import os, sys, importlib.util
os.environ['OMP_NUM_THREADS'] = '2'
os.environ['OPENBLAS_NUM_THREADS'] = '2'
requeridas = ['numpy', 'pandas', 'matplotlib', 'sklearn', 'joblib', 'threadpoolctl']
faltantes = [nombre for nombre in requeridas if importlib.util.find_spec(nombre) is None]
if faltantes:
    raise RuntimeError('Faltan librerías incluidas en el entorno estándar de Colab: '
                       + ', '.join(faltantes) + '. Abre este cuaderno en Google Colab.')

import json, zipfile, platform
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import sklearn, joblib
from IPython.display import display
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import OrdinalEncoder
from sklearn.pipeline import make_pipeline
from sklearn.metrics import (mean_absolute_error, mean_squared_error, r2_score,
    confusion_matrix, ConfusionMatrixDisplay, precision_score, recall_score,
    f1_score, accuracy_score, balanced_accuracy_score)
from threadpoolctl import threadpool_limits

SEED = 20261010
DIAS = 365
INICIO = '2025-10-10'
HORIZONTE = 7
SALIDA = Path('resultados_horizonte')
SALIDA.mkdir(exist_ok=True)
plt.rcParams.update({'figure.figsize': (10, 5), 'axes.grid': True, 'grid.alpha': .2})
print('Preparación lista: se conservan las librerías del entorno, sin instalaciones.')
print('Python:', platform.python_version(), '| NumPy:', np.__version__,
      '| pandas:', pd.__version__, '| sklearn:', sklearn.__version__)
''')
code('CATALOGO = ' + repr(catalog) + "\ncat = pd.DataFrame(CATALOGO)\nassert len(cat) == 320 and cat.sku.is_unique\nprint(f'{len(cat)} productos; {cat.category.nunique()} categorías.')\ndisplay(cat.head())")
md('''
## 2. Dataset reproducible
Una fila por fecha y SKU. Simulamos diferencias de rotación entre productos,
efecto semanal, estacionalidad suave y promociones. La semilla permite repetirlo.
`stock_escenario` representa existencias hipotéticas al cierre: **no limita las ventas
generadas ni se usa para aprender ventas**. Nunca se usan las ventas futuras como entrada.

Para una aplicación real, sustituye esta simulación por ventas diarias, promociones,
devoluciones y stock histórico de tu negocio. Las ventas perdidas por falta de stock
necesitan tratamiento específico: ventas observadas y demanda no son equivalentes.
''')
code('''
rng = np.random.default_rng(SEED)
fechas = pd.date_range(INICIO, periods=DIAS, freq='D')
partes = []
for p in CATALOGO:
    precio = p['price_cents'] / 100
    base = np.clip(7 / (1 + precio / 90) * rng.lognormal(0, .55), .5, 22)
    fase = rng.uniform(0, 2*np.pi)
    promo = (rng.random(DIAS) < .12).astype(int)
    semanal = np.array([1., 1.04, 1.08, 1.06, 1.2, 1.45, .72])[fechas.dayofweek]
    estacional = 1 + .18*np.sin(2*np.pi*np.arange(DIAS)/365 + fase)
    intensidad = base * semanal * estacional * (1 + .35*promo)
    ventas = rng.poisson(intensidad)
    # Escenarios de cobertura variados, independientes de las ventas futuras.
    cobertura = rng.uniform(.25, 2.4, DIAS)
    stock = np.maximum(0, np.rint(base * 7 * cobertura)).astype(int)
    partes.append(pd.DataFrame({
        'fecha': fechas, 'sku': p['sku'], 'producto': p['name'],
        'categoria': p['category'], 'marca': p['brand'], 'precio_soles': precio,
        'promocion': promo, 'unidades_vendidas': ventas, 'stock_escenario': stock,
        'stock_minimo': p['min_stock'], 'origen': 'SINTETICO'
    }))
datos = pd.concat(partes, ignore_index=True).sort_values(['sku', 'fecha']).reset_index(drop=True)
assert len(datos) == 116800
assert not datos.duplicated(['sku', 'fecha']).any()
assert datos.groupby('sku').size().eq(DIAS).all()
assert datos['unidades_vendidas'].ge(0).all()
datos.to_csv(SALIDA / 'dataset_116800.csv', index=False, encoding='utf-8-sig')
print(f'{len(datos):,} registros | {datos.fecha.min().date()} a {datos.fecha.max().date()}')
display(datos.head())
''')
md('''
## 3. Variables conocidas al cierre y objetivo futuro
Se pronostica al **cierre del día t**: podemos conocer las ventas de t y los 27 días
anteriores. El objetivo suma t+1 hasta t+7. Las promociones futuras no se conocen.
Eliminamos 27 días iniciales sin historial completo y 7 finales sin objetivo completo.
Las filas de esos últimos días sí se conservan para la predicción final.
''')
code('''
panel = datos.copy()
g = panel.groupby('sku', sort=False)['unidades_vendidas']
panel['ventas_hoy'] = panel['unidades_vendidas']
for lag in [1, 7, 14]:
    panel[f'lag_{lag}'] = g.shift(lag)
for ventana in [7, 14, 28]:
    panel[f'media_{ventana}'] = g.transform(lambda s: s.rolling(ventana).mean())
panel['desv_28'] = g.transform(lambda s: s.rolling(28).std())
panel['dia_semana'] = panel.fecha.dt.dayofweek
panel['mes'] = panel.fecha.dt.month
panel['dia_anio_sin'] = np.sin(2*np.pi*panel.fecha.dt.dayofyear/365.25)
panel['dia_anio_cos'] = np.cos(2*np.pi*panel.fecha.dt.dayofyear/365.25)
panel['objetivo_7d'] = sum(g.shift(-i) for i in range(1, HORIZONTE+1))
CATEGORICAS = ['categoria', 'marca']
NUMERICAS = ['precio_soles', 'promocion', 'ventas_hoy', 'lag_1', 'lag_7', 'lag_14',
             'media_7', 'media_14', 'media_28', 'desv_28', 'dia_semana', 'mes',
             'dia_anio_sin', 'dia_anio_cos']
FEATURES = CATEGORICAS + NUMERICAS
usable = panel.dropna(subset=FEATURES + ['objetivo_7d']).copy()
assert len(usable) == 320*(365-27-7)
assert not any(c in FEATURES for c in ['objetivo_7d', 'stock_escenario'])
print('Filas con historial y etiqueta completos:', len(usable))
''')
md('''
## 4. Separación cronológica sin fuga del objetivo
Entrenamiento: orígenes de pronóstico antes de 2026-05-11.
Validación: 2026-05-18 a 2026-07-17.
Prueba final: 2026-07-25 a 2026-10-02.
Los huecos de 7 días impiden que las etiquetas de una partición entren en la siguiente.
El historial pasado para calcular variables sí puede cruzar una frontera: ya sería
conocido al hacer una predicción diaria. La prueba es diaria, con historial actualizado,
no un pronóstico de tres meses generado de una sola vez.

Seleccionamos parámetros y política de alertas únicamente con validación.
La prueba se evalúa una vez. Véase el ejemplo oficial de
[validación temporal con variables históricas](https://scikit-learn.org/stable/auto_examples/applications/plot_time_series_lagged_features.html).
''')
code('''
inicio_val = pd.Timestamp('2026-05-18')
inicio_test = pd.Timestamp('2026-07-25')
train = usable[usable.fecha < inicio_val-pd.Timedelta(days=HORIZONTE)].copy()
val = usable[(usable.fecha >= inicio_val) & (usable.fecha < inicio_test-pd.Timedelta(days=HORIZONTE))].copy()
test = usable[usable.fecha >= inicio_test].copy()
assert train.fecha.max()+pd.Timedelta(days=HORIZONTE) < val.fecha.min()
assert val.fecha.max()+pd.Timedelta(days=HORIZONTE) < test.fecha.min()
assert all(len(x) > 0 for x in [train, val, test])
particiones = pd.DataFrame([{'particion': nombre, 'filas': len(d),
    'desde': str(d.fecha.min().date()), 'hasta': str(d.fecha.max().date())}
    for nombre, d in [('Entrenamiento', train), ('Validación', val), ('Prueba', test)]])
display(particiones)
particiones.to_csv(SALIDA/'particiones.csv', index=False)

def crear_modelo(parametros):
    prep = ColumnTransformer([
        ('categorias', OrdinalEncoder(handle_unknown='use_encoded_value', unknown_value=np.nan), CATEGORICAS),
        ('numeros', 'passthrough', NUMERICAS)
    ])
    return make_pipeline(prep, HistGradientBoostingRegressor(
        loss='poisson', early_stopping=False, random_state=SEED,
        categorical_features=[True, True] + [False]*len(NUMERICAS),
        learning_rate=.08, l2_regularization=2, **parametros))

def predecir(modelo, d):
    with threadpool_limits(limits=2):
        return np.maximum(0, modelo.predict(d[FEATURES]))

def metricas(y, pred):
    y, pred = np.asarray(y), np.asarray(pred)
    denominador = np.abs(y).sum()
    return {'MAE_unidades': float(mean_absolute_error(y, pred)),
        'RMSE_unidades': float(np.sqrt(mean_squared_error(y, pred))),
        'WAPE_pct': float(100*np.abs(y-pred).sum()/denominador) if denominador else np.nan,
        'R2': float(r2_score(y, pred))}

candidatos = [dict(max_iter=100, max_leaf_nodes=15), dict(max_iter=180, max_leaf_nodes=31)]
modelos, resultados_val = [], []
for params in candidatos:
    m = crear_modelo(params)
    with threadpool_limits(limits=2):
        m.fit(train[FEATURES], train.objetivo_7d)
    met = metricas(val.objetivo_7d, predecir(m, val))
    modelos.append(m)
    resultados_val.append({**params, **met})
seleccion = int(np.argmin([r['MAE_unidades'] for r in resultados_val]))
PARAMETROS = candidatos[seleccion]
modelo_evaluado = modelos[seleccion]
display(pd.DataFrame(resultados_val))
print('Parámetros elegidos por MAE de validación:', PARAMETROS)
''')
md('''
## 5. Métricas del modelo frente a una referencia
Referencia: repetir el volumen vendido en los 7 días anteriores (`media_7 × 7`).
**MAE:** error absoluto medio, en unidades por producto y semana.
**RMSE:** penaliza más los errores grandes, mismas unidades.
**WAPE:** error absoluto total dividido entre ventas totales, en porcentaje.
**R²:** capacidad de explicar la variación; puede ser negativo.
No usamos MAPE por fila, ya que puede dividir entre cero cuando no hay ventas.
Los objetivos de ventanas consecutivas se solapan: no son muestras independientes.
''')
code('''
pred_test = predecir(modelo_evaluado, test)
pred_val = predecir(modelo_evaluado, val)
baseline_test = test.media_7.to_numpy()*HORIZONTE
comparacion = pd.DataFrame([
    {'modelo': 'Referencia: ventas últimos 7 días', **metricas(test.objetivo_7d, baseline_test)},
    {'modelo': 'HistGradientBoosting', **metricas(test.objetivo_7d, pred_test)}
])
display(comparacion.round(4))
comparacion.to_csv(SALIDA/'metricas_regresion.csv', index=False, encoding='utf-8-sig')
evaluacion = test[['fecha', 'sku', 'producto', 'categoria', 'objetivo_7d', 'stock_escenario']].copy()
evaluacion['prediccion_7d'] = pred_test
evaluacion['referencia_7d'] = baseline_test
por_categoria = pd.DataFrame([{'categoria': nombre, **metricas(d.objetivo_7d, d.prediccion_7d)}
    for nombre, d in evaluacion.groupby('categoria')])
display(por_categoria.round(3))
por_categoria.to_csv(SALIDA/'metricas_por_categoria.csv', index=False, encoding='utf-8-sig')

fig, ax = plt.subplots(1, 2, figsize=(13, 5))
ax[0].scatter(test.objetivo_7d, pred_test, s=4, alpha=.12)
lim = max(test.objetivo_7d.max(), pred_test.max())
ax[0].plot([0, lim], [0, lim], color='crimson')
ax[0].set(xlabel='Ventas reales simuladas (7 días)', ylabel='Predicción (7 días)', title='Prueba: observado vs predicho')
ax[1].hist(pred_test-test.objetivo_7d, bins=60, color='#167d91')
ax[1].set(xlabel='Predicción − observado, unidades', ylabel='Frecuencia', title='Distribución de errores')
fig.tight_layout(); fig.savefig(SALIDA/'errores_modelo.png', dpi=160); plt.show()
''')
md('''
## 6. Matriz de confusión y métricas de alertas
La regresión estima una cantidad, por lo que su evaluación principal es MAE/RMSE/WAPE/R².
Para obtener una matriz de confusión, derivamos una decisión binaria:
**riesgo real simulado = ventas de los próximos 7 días > stock del escenario**.
Alerta prevista = predicción × factor de seguridad > stock.

Probamos factores 1.00, 1.10, 1.20 y 1.30 en validación. Elegimos el que reduce el
coste de errores: un riesgo omitido vale 3 puntos y una falsa alarma 1 punto.
Estos son pesos ilustrativos, **no soles ni costes comprobados**. Una falsa alarma
es una reposición innecesaria; un falso negativo es un riesgo de faltante no detectado.
El factor de seguridad no es un intervalo de confianza ni promete un nivel de servicio.

Métricas: exactitud, precisión, sensibilidad (recall), F1 y exactitud balanceada.
La [matriz de confusión](https://scikit-learn.org/stable/modules/generated/sklearn.metrics.confusion_matrix.html)
usa filas para la clase real y columnas para la predicha.
''')
code('''
riesgo_val = (val.objetivo_7d.to_numpy() > val.stock_escenario.to_numpy()).astype(int)
politicas = []
for factor in [1., 1.1, 1.2, 1.3]:
    alerta = (pred_val*factor > val.stock_escenario.to_numpy()).astype(int)
    tn, fp, fn, tp = confusion_matrix(riesgo_val, alerta, labels=[0, 1]).ravel()
    politicas.append({'factor': factor, 'falsas_alarmas': int(fp), 'riesgos_omitidos': int(fn),
                     'coste_puntos': int(fp+3*fn)})
politicas = pd.DataFrame(politicas)
FACTOR = float(politicas.loc[politicas.coste_puntos.idxmin(), 'factor'])
display(politicas)
politicas.to_csv(SALIDA/'politicas_validacion.csv', index=False)

real = (test.objetivo_7d.to_numpy() > test.stock_escenario.to_numpy()).astype(int)
alerta = (pred_test*FACTOR > test.stock_escenario.to_numpy()).astype(int)
cm = confusion_matrix(real, alerta, labels=[0, 1])
met_alertas = {'factor_validado': FACTOR, 'exactitud': float(accuracy_score(real, alerta)),
    'precision': float(precision_score(real, alerta, zero_division=0)),
    'recall': float(recall_score(real, alerta, zero_division=0)),
    'F1': float(f1_score(real, alerta, zero_division=0)),
    'exactitud_balanceada': float(balanced_accuracy_score(real, alerta)),
    'casos_sin_riesgo': int((real == 0).sum()), 'casos_con_riesgo': int((real == 1).sum())}
display(pd.DataFrame([met_alertas]).round(4))
pd.DataFrame([met_alertas]).to_csv(SALIDA/'metricas_alertas.csv', index=False)
pd.DataFrame(cm, index=['Real: sin riesgo', 'Real: riesgo'],
    columns=['Predicho: sin alerta', 'Predicho: alerta']).to_csv(SALIDA/'matriz_confusion.csv', encoding='utf-8-sig')
fig, ax = plt.subplots(figsize=(7, 6))
ConfusionMatrixDisplay(cm, display_labels=['Sin riesgo', 'Riesgo']).plot(ax=ax, cmap='Blues', colorbar=False)
ax.set_xlabel('Clase predicha'); ax.set_ylabel('Clase real')
ax.set_title('Alertas de inventario · prueba sintética'); fig.tight_layout()
fig.savefig(SALIDA/'matriz_confusion.png', dpi=170); plt.show()
evaluacion['riesgo_real'] = real
evaluacion['alerta_predicha'] = alerta
evaluacion.to_csv(SALIDA/'predicciones_prueba.csv', index=False, encoding='utf-8-sig')
''')
md('''
## 7. Matriz de decisión de inventario
Esta es la matriz de reglas solicitada. Es distinta de la matriz de confusión.
Asumimos 7 días de cobertura y ningún pedido en tránsito. Para otro plazo de entrega,
hay que ajustar el horizonte, los compromisos, las recepciones y el stock de seguridad.

| Estado al cierre | Decisión | Cantidad sugerida |
|---|---|---|
| Stock inferior a ventas previstas | Reponer urgente | Objetivo − stock |
| Stock cubre previsión, pero no objetivo con reserva | Reponer preventivo | Objetivo − stock |
| Stock cubre el objetivo | Mantener | 0 |

Objetivo = máximo entre stock mínimo de catálogo y previsión × factor validado.
Se redondea hacia arriba a unidades enteras. No es una orden de compra automática.
''')
code('''
# Modelo para uso futuro: reentrenado con todos los objetivos ya conocidos.
# Sus métricas NO se calculan sobre datos usados en este reajuste.
modelo_final = crear_modelo(PARAMETROS)
with threadpool_limits(limits=2):
    modelo_final.fit(usable[FEATURES], usable.objetivo_7d)
ultimo = panel[panel.fecha == panel.fecha.max()].copy()
assert len(ultimo) == 320 and ultimo[FEATURES].notna().all().all()
decision = ultimo[['fecha', 'sku', 'producto', 'categoria', 'precio_soles', 'stock_escenario', 'stock_minimo']].copy()
decision['ventas_previstas_7d'] = predecir(modelo_final, ultimo)
decision['objetivo_stock'] = np.ceil(np.maximum(decision.stock_minimo, decision.ventas_previstas_7d*FACTOR)).astype(int)
decision['cantidad_sugerida'] = np.maximum(0, decision.objetivo_stock-decision.stock_escenario).astype(int)
decision['decision'] = np.select([
    decision.stock_escenario < decision.ventas_previstas_7d,
    decision.stock_escenario < decision.objetivo_stock
], ['Reponer urgente', 'Reponer preventivo'], default='Mantener')
decision['valor_catalogo_soles'] = (decision.cantidad_sugerida*decision.precio_soles).round(2)
# Valor referencial al precio de venta; no equivale a coste de compra.
decision = decision.sort_values('cantidad_sugerida', ascending=False)
display(decision.head(20).round({'ventas_previstas_7d': 2}))
decision.to_csv(SALIDA/'matriz_decision_320_productos.csv', index=False, encoding='utf-8-sig')
resumen_decision = pd.crosstab(decision.categoria, decision.decision).reindex(
    columns=['Reponer urgente', 'Reponer preventivo', 'Mantener'], fill_value=0)
display(resumen_decision)
fig, ax = plt.subplots(figsize=(10, 8))
im = ax.imshow(resumen_decision, cmap='YlOrRd', aspect='auto')
ax.set_xticks(range(3), resumen_decision.columns)
ax.set_yticks(range(len(resumen_decision)), resumen_decision.index)
for i in range(len(resumen_decision)):
    for j in range(3):
        ax.text(j, i, str(resumen_decision.iloc[i,j]), ha='center', va='center', color='black')
ax.set_title('Matriz de decisión · número de productos por categoría')
fig.colorbar(im, ax=ax, label='Productos'); fig.tight_layout()
fig.savefig(SALIDA/'matriz_decision.png', dpi=170); plt.show()
''')
md('''
## 8. Guardar y descargar todo
Se exportan el dataset, métricas, predicciones de prueba, dos matrices, gráficos y modelo.
`modelo_evaluado.joblib` corresponde a las métricas de prueba. `modelo_final.joblib`
se reajusta con todos los datos etiquetados y sirve para nuevos pronósticos.
El modelo final se guarda junto a columnas y política de decisión para reutilizarlo.
Los archivos joblib solo deben cargarse si proceden de una fuente de confianza.

**Recomendación:** primero usa este experimento para aprender el flujo; después vuelve a
entrenar con el historial real. Pasar de 116,800 a 233,600 filas sintéticas no acredita
mayor calidad. Más meses reales, calidad de stock y una buena referencia sí permiten
evaluar si el modelo aporta valor. La aplicación actual no cambia con este cuaderno.
''')
code('''
joblib.dump({'modelo': modelo_evaluado, 'features': FEATURES,
    'factor': FACTOR, 'horizonte_dias': HORIZONTE}, SALIDA/'modelo_evaluado.joblib')
joblib.dump({'modelo': modelo_final, 'features': FEATURES,
    'factor': FACTOR, 'horizonte_dias': HORIZONTE}, SALIDA/'modelo_final.joblib')
informe = {'origen': 'SINTETICO', 'semilla': SEED, 'filas_dataset': len(datos),
    'productos': len(CATALOGO), 'dias': DIAS, 'horizonte': HORIZONTE,
    'parametros': PARAMETROS, 'regresion_prueba': comparacion.to_dict(orient='records'),
    'alertas_prueba': met_alertas, 'matriz_confusion': cm.tolist(),
    'particiones': particiones.to_dict(orient='records'),
    'versiones': {'python': platform.python_version(), 'numpy': np.__version__,
        'pandas': pd.__version__, 'sklearn': sklearn.__version__},
    'supuestos': ['Ventas sin restricciones de stock', 'Stock hipotético al cierre',
        'Sin recepciones en los próximos 7 días', 'No constituye validación comercial']}
(SALIDA/'informe.json').write_text(json.dumps(informe, ensure_ascii=False, indent=2), encoding='utf-8')
diccionario = {
    'fecha': 'Fecha diaria, calendario de Perú; pronóstico al cierre del día.',
    'sku': 'Identificador único del producto.', 'producto': 'Nombre de catálogo.',
    'categoria': 'Categoría de catálogo.', 'marca': 'Marca de catálogo.',
    'precio_soles': 'Precio de catálogo de ejemplo en PEN, no precio actual verificado.',
    'promocion': '0/1: promoción simulada del día.',
    'unidades_vendidas': 'Ventas diarias simuladas, sin límite de stock.',
    'stock_escenario': 'Stock hipotético al cierre para evaluar alertas; no limita ventas.',
    'stock_minimo': 'Mínimo de catálogo para ejemplo de política.',
    'origen': 'SINTETICO en todas las filas.'}
(SALIDA/'diccionario_datos.json').write_text(json.dumps(diccionario, ensure_ascii=False, indent=2), encoding='utf-8')
archivo = Path('Horizonte_Colab_resultados.zip')
with zipfile.ZipFile(archivo, 'w', zipfile.ZIP_DEFLATED) as z:
    for f in sorted(SALIDA.iterdir()):
        if f.is_file(): z.write(f, arcname=f.name)
print('LISTO:', archivo.resolve(), '|', round(archivo.stat().st_size/1024/1024, 2), 'MB')
try:
    from google.colab import files
except ImportError:
    print('Ejecución local: abre el ZIP en la carpeta del cuaderno.')
else:
    files.download(str(archivo))
''')
notebook = {'cells': cells, 'metadata': {'colab': {'provenance': [], 'name': 'Horizonte_Entrenamiento_Colab.ipynb'},
    'kernelspec': {'display_name': 'Python 3', 'language': 'python', 'name': 'python3'},
    'language_info': {'name': 'python', 'version': '3.11'}}, 'nbformat': 4, 'nbformat_minor': 5}
for i, cell in enumerate(cells):
    cell['id'] = f'horizonte-{i:02d}'
output = ROOT/'Horizonte_Entrenamiento_Colab.ipynb'
output.write_text(json.dumps(notebook, ensure_ascii=False, indent=1), encoding='utf-8')
version_corregida = ROOT/'Horizonte_Entrenamiento_Colab_V2.ipynb'
version_corregida.write_text(output.read_text(encoding='utf-8'), encoding='utf-8')
print(output)

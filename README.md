# Ferretería Horizonte

Tienda y administración en español, con moneda PEN. React + FastAPI + SQLite.

## Ejecutar la web en Windows

Abre `iniciar.cmd`. La aplicación se muestra en http://127.0.0.1:8000.
Para crear tu administrador, ejecuta `crear-administrador.cmd`.
La base de datos y las cuentas se crean localmente y no se incluyen en el repositorio.

## Entrenar en Google Colab

[Abrir cuaderno en Colab](https://colab.research.google.com/github/Michael10mc1/FERRETERIA-/blob/main/entrenamiento/Horizonte_Entrenamiento_Colab_V2.ipynb)

Selecciona **Entorno de ejecución → Ejecutar todas**, usando CPU.
El cuaderno genera 116,800 registros sintéticos y entrega métricas, matriz de
confusión, decisiones de inventario y los archivos `modelo_final.joblib` y
`modelo_evaluado.joblib` dentro de un ZIP.

Si ejecutaste la preparación de la primera versión, guarda cualquier archivo
temporal necesario y usa **Desconectar y eliminar entorno de ejecución** antes
de ejecutar esta V2. Conserva las librerías incluidas en Colab.

El entrenamiento actual usa ventas sintéticas. El modelo está conectado a FastAPI;
su validación comercial con ventas reales sigue pendiente.
Conserva el `informe.json` generado en tu sesión junto con tu modelo: registra
las versiones de las librerías y los resultados de ese entrenamiento.

Colab ejecuta el cuaderno en su propia sesión. Para guardar cambios en el cuaderno
del repositorio, usa **Archivo → Guardar una copia en GitHub** y autoriza tu cuenta
en Colab. Los archivos generados, como JOBLIB, se descargan por separado.

## Ramas

`main` contiene el proyecto inicial. `codex/colab` contiene el entrenamiento
y la integración del modelo en el administrador.

## Predicciones ML en el administrador

Abre **Administración → Predicciones ML**. El backend carga el modelo de
`backend/ml_assets/`, verifica su huella y requiere las versiones de dependencias
de `requirements.txt`. El paquete incluido procede de una ejecución local
verificada del mismo cuaderno V2; sus métricas se conservan en `informe.json`.

- **Mi tienda:** usa 28 días completos hasta ayer, en horario de Perú. Considera
  pedidos entregados por fecha de compra y permite importar historial CSV anterior
  al registro local de cada producto. Los días sin disponibilidad o sin historial
  impiden pronosticar; cero ventas durante todo el período tampoco genera cifras.
- **Explorar el modelo:** muestra 320 productos con historial y stock sintéticos,
  fechado al 9 de octubre de 2026. Nunca escribe estos datos en la tienda.
- **Cómo funciona el modelo:** explica los 116,800 registros generados, las
  particiones temporales, métricas y matriz de confusión de alertas de faltantes.

La previsión es el total de ventas de los próximos siete días. Para calcular la
reposición se descuentan los pedidos ya comprometidos hoy, se aplica una reserva
de 10 %, se respeta el stock mínimo y se resta el stock disponible. No genera
compras automáticas ni considera recepciones pendientes. La reserva no es un
intervalo de confianza. Las métricas sintéticas no garantizan precisión real.

La importación exige `fecha,sku,unidades_vendidas,disponible`: fecha ISO,
SKU existente, unidades enteras no negativas y disponibilidad 1/0. Incluye días
con cero ventas. Reimportar el mismo SKU y fecha reemplaza su registro histórico;
no modifica pedidos ni existencias. Solo un administrador puede acceder al ML.

Pruebas aisladas: `.venv\Scripts\python.exe -m pytest backend/test_ml.py backend/test_app.py -q`.

### Historial y validación real

En **Predicciones ML → Historial y validación real** se consulta el número de
pedidos entregados, pendientes e historiales importados. El diagnóstico CSV indica
las fechas faltantes por SKU, problemas de disponibilidad y pedidos sin resolver.
Los pedidos históricos aún abiertos impiden pronosticar ese producto, para evitar
confundir ventas pendientes de entrega con días de venta cero.

Cuando haya productos aptos, **Guardar semana para evaluar** conserva su previsión,
historial de entrada, referencia de la semana anterior y versión del modelo en
la base local. No sobreescribe previsiones ni admite semanas superpuestas por SKU.
Es una acción manual del administrador, no un proceso automático en segundo plano.

Al terminar los siete días, **Actualizar diagnóstico** compara contra las ventas
registradas del período: MAE, RMSE y WAPE, junto al error de la referencia. Las
semanas incompletas, con pedidos sin resolver o falta de stock se excluyen; WAPE
queda sin definir cuando las ventas totales son cero. Se incluyen productos
desactivados después de guardar su previsión. Correcciones en los pedidos pueden
actualizar los resultados observados, pero nunca la previsión guardada.

Este seguimiento no certifica la procedencia de archivos importados, no rellena
ventas faltantes con datos sintéticos y no reentrena automáticamente. Se requiere
registrar todas las ventas del negocio para interpretar correctamente los ceros.
La matriz del cuaderno sigue siendo sintética; el seguimiento real evalúa ventas,
sin presentar los reabastecimientos como una matriz real de faltantes.

## Presentación académica

Ejecuta `preparar-presentacion.cmd` después de crear el administrador y reinicia
la web con `iniciar.cmd`. Se crea `backend/data/presentacion.db` como copia de
la tienda original y se activa mediante `backend/data/presentacion.activa`.
La base original `horizonte.db` se conserva. Las cuentas existentes funcionan
en la copia. Ninguna base, sesión ni credencial se incluye en GitHub.

La preparación añade 84 días de datos de demostración: pedidos, líneas de venta,
clientes sin datos de contacto reales, entradas de proveedor y devoluciones.
Los importes se calculan con el catálogo en PEN. Cada movimiento conserva su
balance, las cancelaciones restituyen stock y solo los pedidos entregados cuentan
como ventas. La semilla 20261011 permite repetir la generación; volver a ejecutar
la preparación conserva la presentación existente sin duplicar pedidos.

La procedencia se explica en **Predicciones ML → Modelo y metodología**. Son
datos creados para probar el proyecto, no transacciones de una empresa real.
El historial operativo es independiente de los 116,800 registros de entrenamiento.
En **Historial y evaluación** se muestra una evaluación retrospectiva de siete
semanas, con las mismas variables de 28 días, referencia semanal, métricas y matriz
de cobertura de stock al corte. Los precios/promociones históricos son constantes
y se conservan como metadatos. Las recepciones posteriores no se incluyen en la
comparación de cobertura. El informe corresponde al historial cerrado hasta la
fecha indicada; nuevas previsiones se guardan mediante el seguimiento prospectivo.

Para volver a la base original, cambia el nombre de `presentacion.activa` a
`presentacion.inactiva` y reinicia el servidor. Para regresar a la presentación,
restaura el nombre `presentacion.activa`. También se puede seleccionar otra base
mediante `DATABASE_URL`, que siempre tiene prioridad.

Verificación de presentación: `.venv\Scripts\python.exe -m pytest backend/test_presentation.py -q`.


## Horizonte IA: asistente con contexto de la tienda

El administrador dispone de **Administración → Asistente IA** (`/admin/asistente`).
El cliente entra desde el botón **¿Te ayudo con tu proyecto?** (`/asistente`) e inicia
sesión para conversar. El historial es privado por cuenta y por rol.

Copia `.env.example` a `.env` si aún no existe y completa `HIVE_API_KEY` con la clave
secreta V3. No sobrescribas tu `.env` existente. El servidor lee las tres variables
HIVE de ese archivo; las variables del proceso tienen prioridad. La URL por defecto
es `https://api-cdn.thehive.ai/api/v3` y el modelo
`deepseek-ai/deepseek-v4.1-flash`. Solo se admiten los hosts oficiales de Hive;
la clave nunca se envía al navegador ni se incluye en Git. No hace falta el ID
público de la clave. Reinicia con `iniciar.cmd` después de actualizar el código.

Referencia del proveedor: https://docs.thehive.ai/docs/deepseek-v41-flash

El LLM ya está preentrenado. La integración recupera productos por relevancia,
normaliza acentos y plurales y añade precios, stock y políticas actuales al contexto.
Para administradores añade ventas agregadas de los últimos 30 días, inventario y
previsiones calculadas por el ML existente. No se envían fichas de clientes,
contraseñas, sesiones, direcciones de pedidos ni datos personales del administrador.
El texto que el usuario escribe y los últimos diez mensajes de su conversación
se envían a Hive para responder. No se envía la base completa.

La respuesta incluye **Datos consultados**, una captura fechada de productos y
previsiones con enlaces a las pantallas originales. Las conversaciones se guardan
en la base activa, en `ai_conversations` y `ai_messages`. El chat es de consulta:
no crea pedidos, cambia precios ni modifica existencias. El ML calcula la demanda;
el LLM la explica, sin sustituirlo ni inventar otros horizontes de predicción.

Hay un máximo de 1 consulta simultánea por cuenta, 6 por minuto, 60 por cuenta
cada 24 horas y 300 globales cada 24 horas. Estos contadores residen en memoria
para el servidor local de un proceso y se reinician al reiniciar el servidor.
Antes de desplegar con varios procesos, hay que compartir los límites en una base
o Redis. Se limita la entrada a 1800 caracteres y la salida a 1400 tokens;
no se reintenta automáticamente una llamada de pago. Cada conversación admite
30 consultas, tras las cuales se inicia otra. Los errores de saldo, autorización,
límite o conexión se muestran sin incluir la respuesta privada del proveedor.

Verificación sin consumir saldo:
`.venv\Scripts\python.exe -m pytest backend/test_assistant.py backend/test_app.py backend/test_ml.py -q`.
Las pruebas usan una base temporal y respuestas controladas del proveedor; comprueban
permisos, aislamiento de historial, búsqueda, contexto ML, errores y que no cambie stock.

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

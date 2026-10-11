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

El entrenamiento actual usa ventas sintéticas. La conexión del modelo a FastAPI
y su validación con ventas reales corresponden a la siguiente etapa.
Conserva el `informe.json` generado en tu sesión junto con tu modelo: registra
las versiones de las librerías y los resultados de ese entrenamiento.

Colab ejecuta el cuaderno en su propia sesión. Para guardar cambios en el cuaderno
del repositorio, usa **Archivo → Guardar una copia en GitHub** y autoriza tu cuenta
en Colab. Los archivos generados, como JOBLIB, se descargan por separado.

## Ramas

`main` contiene el proyecto inicial. `codex/colab` queda preparada para trabajar
en el entrenamiento y la futura integración del modelo.

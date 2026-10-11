"""Ejecuta realmente todas las celdas y guarda sus resultados locales."""
import os
from pathlib import Path
import nbformat
from nbclient import NotebookClient

root = Path(__file__).resolve().parent
source = root/'Horizonte_Entrenamiento_Colab_V2.ipynb'
execution_dir = root/'ejecucion_v2'
execution_dir.mkdir(exist_ok=True)
os.environ['HORIZONTE_SKIP_INSTALL'] = '1'
os.environ['OMP_NUM_THREADS'] = '2'
os.environ['OPENBLAS_NUM_THREADS'] = '2'
kernel_dir = root/'.jupyter'/'kernels'/'horizonte-ml'
kernel_dir.mkdir(exist_ok=True, parents=True)
os.environ['JUPYTER_PATH'] = str(root/'.jupyter')
os.environ['JUPYTER_RUNTIME_DIR'] = str(root/'.jupyter'/'runtime')
os.environ['IPYTHONDIR'] = str(root/'.ipython')
os.environ['MPLCONFIGDIR'] = str(root/'.matplotlib')
import sys, json
(kernel_dir/'kernel.json').write_text(json.dumps({'argv': [sys.executable, '-m', 'ipykernel_launcher', '-f', '{connection_file}'],
    'display_name': 'Horizonte ML local', 'language': 'python'}), encoding='utf-8')
nb = nbformat.read(source, as_version=4)
nbformat.validate(nb)
client = NotebookClient(nb, timeout=900, startup_timeout=60, kernel_name='horizonte-ml', resources={'metadata': {'path': str(execution_dir)}})
client.on_cell_start = lambda cell, cell_index, **kwargs: print(f'Celda {cell_index+1}/{len(nb.cells)}', flush=True)
client.execute()
nbformat.write(nb, root/'Horizonte_Entrenamiento_Ejecutado_V2.ipynb')
print('VERIFICADO: todas las celdas ejecutadas sin errores.')

import {useEffect,useState} from 'react';
import {Activity,ArrowRight,CalendarDays,Check,Download,Info,Upload} from 'lucide-react';
import {api,send} from './api';
import {ErrorBox,Loading} from './components';

const number=(n:number)=>new Intl.NumberFormat('es-PE',{maximumFractionDigits:2}).format(n);
const date=(s:string)=>new Intl.DateTimeFormat('es-PE',{day:'numeric',month:'short',year:'numeric',timeZone:'UTC'}).format(new Date(s+'T12:00:00Z'));

export function RealValidation({onImport}:{onImport:()=>void}){
  const [quality,setQuality]=useState<any>(null),[results,setResults]=useState<any>(null);
  const [error,setError]=useState(''),[message,setMessage]=useState(''),[saving,setSaving]=useState(false),[busy,setBusy]=useState(true),[version,setVersion]=useState(0),[query,setQuery]=useState('');
  useEffect(()=>{let active=true;setBusy(true);setError('');
    Promise.all([api('/admin/ml/readiness'),api('/admin/ml/validation')]).then(([q,r])=>{if(active){setQuality(q);setResults(r)}}).catch(e=>{if(active)setError(e.message)}).finally(()=>{if(active)setBusy(false)});
    return()=>{active=false};
  },[version]);
  async function save(){setSaving(true);setError('');try{
    const r=await send<any>('/admin/ml/validation/snapshots',{});
    setMessage(r.saved?`${r.saved} previsiones guardadas. Podrás comparar resultados desde el ${date(r.available_from)}.`:'Estos productos ya tienen una semana en seguimiento. Sus previsiones originales se conservan.');
    setVersion(v=>v+1);
  }catch(e:any){setError(e.message)}finally{setSaving(false)}}
  const items=quality?.items.filter((p:any)=>(p.sku+' '+p.name).toLowerCase().includes(query.toLowerCase()))||[];
  const dates=quality?.items.map((p:any)=>p.earliest_local_forecast).filter(Boolean).sort()||[];
  return <div className="ml-real"><ErrorBox message={error}/>{busy?<Loading/>:quality&&results&&<>
    <section className="ml-model-hero"><div><span className="eyebrow">VALIDACIÓN CON VENTAS DE TU TIENDA</span><h2>Primero datos completos.<br/>Después, resultados medibles.</h2><p>Este diagnóstico consulta tus registros actuales. Las métricas reales aparecen al comparar previsiones guardadas con semanas terminadas.</p><span className="ml-light-pill">{results.evaluated?'Seguimiento inicial · revisión comercial pendiente':'Validación pendiente · sin evidencia suficiente'}</span></div><div className="ml-dataset"><strong>{quality.ready} / {quality.products}</strong><span>productos listos para pronosticar</span><small>Historial revisado hasta {date(quality.as_of)}</small></div></section>
    <div className="ml-kpis">{[
      ['Pedidos entregados',quality.delivered_orders,'Registrados en esta tienda'],
      ['Pedidos por resolver',quality.unresolved_orders,'Pendientes de entrega o cancelación'],
      ['Filas importadas',quality.imported_rows,'Historial declarado por el administrador'],
      ['Previsiones evaluadas',results.evaluated,'Semanas de producto completas']
    ].map(([label,value,note])=><article className="ml-metric" key={String(label)}><div><span>{label}</span><Activity size={18}/></div><strong>{number(Number(value))}</strong><small>{note}</small></article>)}</div>
    <section className="ml-panel ml-padding"><span className="eyebrow orange">01 / PREPARAR EL HISTORIAL</span><h2>{quality.ready?'Ya puedes iniciar un seguimiento.':'Todavía faltan datos para validar el modelo.'}</h2><p>Necesitamos 28 días consecutivos por producto, ventas positivas, disponibilidad y pedidos históricos resueltos. Un día sin ventas registradas cuenta como cero: incluye también todas tus ventas fuera de la web en tu sistema de registro antes de confiar en el resultado.</p>
      {dates.length>0&&quality.ready===0&&<div className="ml-context"><CalendarDays size={18}/><div><b>{dates[0]>results.as_of?`Primer horizonte local posible: ${date(dates[0])}`:'La antigüedad del catálogo por sí sola no basta'}</b><p>{dates[0]>results.as_of?'Fecha mínima sin importar historial anterior; requiere registrar las ventas y resolver los pedidos. El día de apertura se excluye por ser incompleto.':'Revisa los motivos por producto. Tener días registrados no garantiza ventas suficientes ni disponibilidad.'}</p></div></div>}
      <div className="ml-real-actions"><button className="button orange-button" onClick={onImport}><Upload size={16}/>Añadir historial real</button><a className="button light" href="/api/admin/ml/readiness/export"><Download size={16}/>Descargar diagnóstico completo</a></div>
      <label className="ml-quality-search">Buscar en el diagnóstico<input aria-label="Buscar en diagnóstico" placeholder="Nombre o SKU" value={query} onChange={e=>setQuery(e.target.value)}/></label>
      <div className="table-scroll"><table><thead><tr><th>PRODUCTO</th><th>HISTORIAL</th><th>QUÉ FALTA</th></tr></thead><tbody>{items.slice(0,8).map((p:any)=><tr key={p.sku}><td><b>{p.name}</b><small>{p.sku}</small></td><td>{p.days} / 28 días<small>{p.units} unidades registradas</small></td><td>{p.reason||'Listo para previsión experimental'}<small>{p.missing_dates.length>0?`${p.missing_dates.length} fechas faltantes · `:''}{p.limited_days} días con stock limitado · {p.pending_days} con pedidos sin resolver</small></td></tr>)}</tbody></table></div><p className="ml-footnote">Mostrando {Math.min(8,items.length)} de {items.length} productos. El CSV contiene todas las fechas faltantes. Los datos importados deben ser ventas reales; el sistema no puede certificar su procedencia.</p>
    </section>
    <section className="ml-panel ml-padding"><span className="eyebrow orange">02 / GUARDAR ANTES DE CONOCER EL RESULTADO</span><h2>Una semana, una previsión que se conserva.</h2><p>Guarda las previsiones disponibles de Mi tienda. El sistema conserva la cifra original y evita semanas superpuestas para el mismo producto. Esta acción es manual: vuelve al terminar la semana para revisar resultados y guardar el siguiente período.</p><div className="ml-real-actions"><button className="button orange-button" disabled={saving||quality.ready===0} onClick={save}><Check size={16}/>{saving?'Guardando…':'Guardar semana para evaluar'}</button><button className="button light" onClick={()=>setVersion(v=>v+1)}>Actualizar diagnóstico</button></div>{message&&<p role="status" className="ml-save-success">{message}</p>}
      <div className="ml-tracking"><span><b>{results.saved}</b> guardadas</span><span><b>{results.waiting}</b> esperando cierre</span><span><b>{results.excluded}</b> sin resultado utilizable</span><span><b>{results.periods}</b> períodos evaluados</span></div>
    </section>
    <section className="ml-panel ml-padding"><span className="eyebrow orange">03 / MEDIR EL DESEMPEÑO REAL</span><h2>{results.model_metrics?'¿Mejora frente a repetir la última semana?':'Las métricas reales aparecerán aquí.'}</h2>
    {results.model_metrics?<><div className="ml-kpis">{[
      ['MAE del modelo',number(results.model_metrics.mae),'Unidades de error medio'],
      ['MAE de referencia',number(results.baseline_metrics.mae),'Repetir la semana anterior'],
      ['RMSE del modelo',number(results.model_metrics.rmse),'Penaliza errores grandes'],
      ['WAPE del modelo',results.model_metrics.wape===null?'No definido':number(results.model_metrics.wape)+' %','Sin porcentaje si las ventas suman cero']
    ].map(([label,value,note])=><article className="ml-metric" key={label}><div>{label}</div><strong>{value}</strong><small>{note}</small></article>)}</div><p>{results.products} productos evaluados en {results.periods} períodos. {results.model_metrics.mae<results.baseline_metrics.mae?'El modelo tiene menor error medio en esta muestra.':'El modelo todavía no mejora el error medio de la referencia en esta muestra.'} Esto no certifica su desempeño futuro.</p></>:<div className="ml-context"><Info size={20}/><div><b>Aún no hay semanas guardadas con resultados evaluables.</b><p>Los valores del cuaderno son sintéticos y permanecen en “Cómo funciona el modelo”. Aquí solo se comparan previsiones conservadas con ventas posteriores registradas en tu tienda.</p></div></div>}
    <p>Se excluyen semanas incompletas, con pedidos sin resolver o disponibilidad limitada. Las ventas reales se recalculan al actualizar para reflejar correcciones. La comparación corresponde a la versión actual del modelo; los registros de versiones anteriores se conservan.</p>
    {!!results.items.length&&<div className="table-scroll"><table><thead><tr><th>PRODUCTO / PERÍODO</th><th>PREVISIÓN</th><th>VENTAS</th><th>ESTADO</th></tr></thead><tbody>{results.items.map((r:any)=><tr key={r.id}><td><b>{r.name}</b><small>{date(r.start)} — {date(r.end)}</small></td><td>{number(r.prediction)}</td><td>{r.actual===null?'—':r.actual}</td><td>{r.status==='evaluada'?'Evaluada':r.reason}</td></tr>)}</tbody></table><p className="ml-footnote">Últimos {results.shown} registros de {results.saved}. Las métricas incluyen todos los registros evaluables.</p></div>}
    <p className="ml-footnote">La matriz de confusión del cuaderno mide alertas sobre stock simulado. Este seguimiento mide ventas; no genera una matriz real de faltantes porque los reabastecimientos cambian la disponibilidad.</p></section>
  </>}</div>
}

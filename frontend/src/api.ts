export type Product = {id:number;sku:string;name:string;description:string;category:string;brand:string;features:Record<string,string>;image:string;unit:string;price_cents:number;sale_price_cents:number;cost_cents:number;stock:number;min_stock:number;active:boolean;discount_percent:number;featured:boolean};
export type Address = {label:string;street:string;district:string;city:string;reference:string};
export type User = {id:number;name:string;email:string;phone:string;role:string;addresses:Address[]};
export type Order = {id:number;number:string;created_at:string;status:string;payment_status:string;delivery:string;address:Address;customer_name:string;phone:string;notes:string;subtotal_cents:number;shipping_cents:number;total_cents:number;items:{id:number;product_id:number;name:string;image:string;quantity:number;unit_price_cents:number;discount_percent:number}[];history:{id:number;message:string;created_at:string}[]};
export type Taxonomy = {categories:{id:number;name:string}[];brands:{id:number;name:string}[]};
export type Store = {name:string;phone:string;email:string;address:string;hours:string;shipping_cents:number};
export type Page = {items:Product[];total:number;page:number;pages:number};
export const money=(c:number)=>new Intl.NumberFormat('es-PE',{style:'currency',currency:'PEN'}).format(c/100);
export const date=(v:string)=>new Intl.DateTimeFormat('es-PE',{dateStyle:'medium',timeStyle:'short',timeZone:'America/Lima'}).format(new Date(v));
export async function api<T=any>(path:string, options:RequestInit={}):Promise<T>{
 const res=await fetch('/api'+path,{credentials:'same-origin',...options,headers:{'Content-Type':'application/json',...options.headers}});
 const data=await res.json();
 if(!res.ok) throw new Error(typeof data.detail==='string'?data.detail:Array.isArray(data.detail)?data.detail.map((e:any)=>`${e.loc.at(-1)}: ${e.msg}`).join(' · '):'No se pudo completar la operación');
 return data;
}
export const send=<T=any>(path:string,body:unknown,method='POST')=>api<T>(path,{method,body:JSON.stringify(body)});

import {createContext,useContext,useEffect,useState,ReactNode} from 'react';
import {api,send,Product,User,Taxonomy,Store} from './api';
type CartLine={product:Product;quantity:number};
type Context={user:User|null;ready:boolean;setUser:(u:User|null)=>void;cart:CartLine[];add:(p:Product,n?:number)=>void;quantity:(id:number,n:number)=>void;clear:()=>void;refreshCart:()=>Promise<void>;toast:(m:string)=>void;taxonomy:Taxonomy;store:Store;refresh:()=>void;logout:()=>Promise<void>};
const AppContext=createContext<Context>(null!);
export function Provider({children}:{children:ReactNode}){
 const [user,setUser]=useState<User|null>(null),[ready,setReady]=useState(false),[message,setMessage]=useState('');
 const [cart,setCart]=useState<CartLine[]>(()=>{try{return JSON.parse(localStorage.getItem('horizonte.cart')||'[]')}catch{return []}});
 const [taxonomy,setTaxonomy]=useState<Taxonomy>({categories:[],brands:[]});
 const [store,setStore]=useState<Store>({name:'Ferretería Horizonte',phone:'',email:'',address:'Lima, Perú',hours:'',shipping_cents:1500});
 const toast=(m:string)=>setMessage(m);
 const refresh=()=>{api<Taxonomy>('/taxonomy').then(setTaxonomy).catch(e=>toast(e.message));api<Store>('/store').then(setStore).catch(e=>toast(e.message))};
 useEffect(()=>{api<User>('/me').then(setUser).catch(()=>{}).finally(()=>setReady(true));refresh()},[]);
 useEffect(()=>{localStorage.setItem('horizonte.cart',JSON.stringify(cart))},[cart]);
 useEffect(()=>{document.title=store.name+' | Todo para hacerlo bien'},[store.name]);
 useEffect(()=>{if(message){const t=setTimeout(()=>setMessage(''),4500);return()=>clearTimeout(t)}},[message]);
 const add=(p:Product,n=1)=>{if(p.stock<=0)return;setCart(old=>{const prev=old.find(x=>x.product.id===p.id);return prev?old.map(x=>x.product.id===p.id?{product:p,quantity:Math.min(p.stock,x.quantity+n)}:x):[...old,{product:p,quantity:Math.min(n,p.stock)}]});toast('Producto añadido al carrito')};
 const quantity=(id:number,n:number)=>setCart(old=>n<=0?old.filter(x=>x.product.id!==id):old.map(x=>x.product.id===id?{...x,quantity:Math.min(n,x.product.stock)}:x));
 const refreshCart=async()=>{const updated=await Promise.all(cart.map(async x=>{try{return {...x,product:await api<Product>('/products/'+x.product.id)}}catch{return {...x,product:{...x.product,stock:0,active:false}}}}));setCart(updated)};
 const logout=async()=>{await send('/auth/logout',{});setUser(null);toast('Sesión cerrada')};
 return <AppContext.Provider value={{user,ready,setUser,cart,add,quantity,clear:()=>setCart([]),refreshCart,toast,taxonomy,store,refresh,logout}}>{children}{message&&<div className="toast" role="status">{message}<button aria-label="Cerrar mensaje" onClick={()=>setMessage('')}>×</button></div>}</AppContext.Provider>
}
export const useApp=()=>useContext(AppContext);

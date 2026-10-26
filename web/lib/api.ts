import {getSupabase} from "./supabase";
export type Column={name:string,dtype:string,missing:number,distinct:number};export type Sheet={name:string,row_count:number,column_count:number,columns:Column[],preview:Record<string,unknown>[],warnings:string[]};export type Dataset={id:string,filename:string,sheets:Sheet[]};export type Plan={sheet:string,operation:"groupby"|"describe"|"count",dimensions:string[],measure?:string,aggregation:"count"|"sum"|"mean"|"median"|"min"|"max",chart:"bar"|"line"};export type Analysis={run_id:string,title:string,data:Record<string,unknown>[],methodology:string,checks:Record<string,unknown>,warnings:string[],source_sheet:string,row_count:number,chart?:{x:string,y:string,type:"bar"|"line"}};const url=process.env.NEXT_PUBLIC_ANALYTICS_API_URL;async function authHeaders(){const sb=getSupabase();const {data}=sb?await sb.auth.getSession():{data:{session:null}};if(!data.session?.access_token)throw new Error("Sign in before using the analytics API.");return {Authorization:"Bearer "+data.session.access_token};}
function api(){if(!url)throw new Error("Analysis API is not configured. Public uploads are disabled until a secured analytics service is connected.");return url}export async function uploadFile(file:File):Promise<Dataset>{
 const sb=getSupabase();if(!sb)throw new Error("Supabase is not configured");
 const {data:{user},error:userError}=await sb.auth.getUser();
 if(userError||!user)throw new Error("Sign in again before uploading");
 if(file.size>100*1024*1024)throw new Error("Maximum file size for this storage tier is 100 MB. Larger files need a higher storage limit and a dedicated processing worker.");
 const ext=file.name.toLowerCase().split(".").pop();
 if(!ext||!["xlsx","xlsm","csv","tsv"].includes(ext))throw new Error("Supported uploads: XLSX, XLSM, CSV and TSV");
 const buffer=await file.arrayBuffer();
 const digest=await crypto.subtle.digest("SHA-256",buffer);
 const id=Array.from(new Uint8Array(digest)).map(b=>b.toString(16).padStart(2,"0")).join("");
 const path=user.id+"/"+id+"."+ext;
 const {error}=await sb.storage.from("analytiq-originals").upload(path,file,{upsert:false,contentType:"application/octet-stream"});
 if(error&&!/already exists|duplicate|409|conflict/i.test(error.message))throw new Error("Private storage upload failed: "+error.message);
 const controller=new AbortController();
 const timer=setTimeout(()=>controller.abort(),60000);
 try{
  const response=await fetch(api()+"/datasets/"+id+"/profile",{headers:await authHeaders(),signal:controller.signal});
  if(!response.ok){const body=await response.json().catch(()=>({}));throw new Error(typeof body.detail==="string"?body.detail:"File inspection failed ("+response.status+")")}
  const data=await response.json() as Dataset;
  return {...data,filename:file.name};
 }catch(e){
  if(e instanceof Error&&e.name==="AbortError")throw new Error("File uploaded, but inspection timed out. Try a smaller workbook or contact support.");
  if(e instanceof TypeError)throw new Error("File uploaded to Supabase, but the analytics server could not be reached.");
  throw e;
 }finally{clearTimeout(timer)}
}
export async function analyze(id:string,plan:Plan):Promise<Analysis>{const response=await fetch(api()+"/datasets/"+id+"/analyze",{method:"POST",headers:{"content-type":"application/json",...await authHeaders()},body:JSON.stringify(plan)});if(!response.ok)throw new Error((await response.json()).detail||"Analysis failed");return response.json()}export function exportUrl(id:string,sheet:string,format:"csv"|"xlsx"){return api()+"/datasets/"+id+"/export?format="+format+"&sheet="+encodeURIComponent(sheet)}
export async function downloadExport(id:string,sheet:string,format:"csv"|"xlsx"){const response=await fetch(exportUrl(id,sheet,format),{headers:await authHeaders()});if(!response.ok)throw new Error("Export failed: "+response.status);const blob=await response.blob();const url=URL.createObjectURL(blob);const link=document.createElement("a");link.href=url;link.download="analytiq-export."+format;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}

export type CleaningOptions={sheet:string;remove_duplicates:boolean;trim_whitespace:boolean;drop_empty_rows:boolean;drop_empty_columns:boolean;missing_strategy:"keep"|"drop_rows"|"fill_text"|"fill_zero"};
export async function cleaningPreview(id:string,options:CleaningOptions){const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),90000);try{const r=await fetch(api()+"/datasets/"+id+"/clean/preview",{method:"POST",headers:{"content-type":"application/json",...await authHeaders()},body:JSON.stringify(options),signal:controller.signal});const data=await r.json();if(!r.ok)throw new Error(data.detail||"Cleaning failed");return data as {report:Record<string,number>;preview:Record<string,unknown>[];columns:string[];warning:string}}finally{clearTimeout(timer)}}
export async function cleaningDownload(id:string,options:CleaningOptions){const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),90000);try{const r=await fetch(api()+"/datasets/"+id+"/clean/download",{method:"POST",headers:{"content-type":"application/json",...await authHeaders()},body:JSON.stringify(options),signal:controller.signal});if(!r.ok){const body=await r.json().catch(()=>({}));throw new Error(body.detail||"Download failed")}const blob=await r.blob();const u=URL.createObjectURL(blob);const a=document.createElement("a");a.href=u;a.download="analytiq-cleaned.xlsx";a.click();setTimeout(()=>URL.revokeObjectURL(u),1000)}finally{clearTimeout(timer)}}

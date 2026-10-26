"use client";
import {useEffect,useRef,useState} from "react";
import {useRouter} from "next/navigation";
import Link from "next/link";
import {getSupabase} from "../lib/supabase";
import {uploadFile,analyze,Dataset,Plan} from "../lib/api";
export default function Home(){
 const router=useRouter();const fileRef=useRef<HTMLInputElement>(null);
 const [ready,setReady]=useState(false),[dataset,setDataset]=useState<Dataset|null>(null),[question,setQuestion]=useState(""),[busy,setBusy]=useState(false),[error,setError]=useState(""),[stage,setStage]=useState(""),[project,setProject]=useState("Workspace");
 useEffect(()=>{const sb=getSupabase();if(!sb){router.replace("/login");return;}let alive=true;sb.auth.getUser().then(({data})=>{if(!alive)return;if(!data.user){router.replace("/login");return;}setReady(true);const id=new URLSearchParams(location.search).get("project");if(id)sb.from("projects").select("name").eq("id",id).single().then(({data})=>{if(data)setProject(data.name)});});return()=>{alive=false};},[router]);
 async function upload(f?:File){if(!f)return;setBusy(true);setError("");setStage("Uploading to secure storage and inspecting worksheets");try{const d=await uploadFile(f);setDataset(d);setStage("");}catch(e){setError(e instanceof Error?e.message:String(e))}finally{setBusy(false);if(fileRef.current)fileRef.current.value=""}}
 function choose(q:string,d:Dataset):{sheet:string,plan:Plan}{
  const lower=q.toLowerCase(), summary=/summarize|summary|overview|describe|profile/.test(lower);
  if(/(?:how many|number of|total|count)\\s+(?:rows|records)\\b|\\brow count\\b/i.test(q)){const sheet=d.sheets.slice().sort((a,b)=>b.row_count-a.row_count)[0];if(!sheet)throw new Error("No worksheet available");return {sheet:sheet.name,plan:{sheet:sheet.name,operation:"count",dimensions:[],aggregation:"count",chart:"bar"}};}
  const usable=(c:{name:string})=>c.name.trim()&&!/^unnamed(?:\\s|:|$)/i.test(c.name);
  const terms=lower.split(/[^a-z0-9]+/).filter(t=>t.length>2);
  const ranked=d.sheets.filter(s=>s.columns.some(usable)).map(sheet=>{
   const names=sheet.columns.filter(usable).map(c=>c.name.toLowerCase());
   const requestedStatus=/status|won|lost|abandon|opportunit/.test(lower);
   const score=terms.filter(t=>names.some(n=>n.includes(t))||sheet.name.toLowerCase().includes(t)).length*8
    +(requestedStatus&&names.some(n=>/status|outcome|result|stage/.test(n))?30:0)
    +(/closed|open opportunit/i.test(sheet.name)?8:0)
    +Math.min(sheet.row_count,100000)/100000
    -(/draft|report catalog|documentation/i.test(sheet.name)?15:0);
   return {sheet,score};
  }).sort((x,y)=>y.score-x.score);
  const requested=ranked[0]?.sheet;
  if(!requested)throw new Error("No usable table headers were detected. Re-import the dataset to refresh its worksheet inspection.");
  const columns=requested.columns.filter(usable);
  const matched=columns.filter(c=>lower.includes(c.name.toLowerCase())).sort((a,b)=>b.name.length-a.name.length);
  const by=lower.match(/\\bby\\s+([^?.,]+)/)?.[1]?.trim();
  const group=matched.find(c=>by?.includes(c.name.toLowerCase()))||columns.find(c=>by&&c.name.toLowerCase().includes(by))||columns.find(c=>/status|outcome|stage|result/i.test(c.name)&&/status|opportunit|won|lost/.test(lower))||matched[0]||columns.find(c=>/status|category|region|industry|year|month|type|phase|product/i.test(c.name));
  if(!group)throw new Error("Could not confidently identify a grouping field. Found columns: "+columns.slice(0,8).map(c=>c.name).join(", ")+".");
  const explicitSum=/\\b(sum|total|add up)\\b/i.test(lower);
  const agg:Plan["aggregation"]= /\\bmedian\\b/.test(lower)?"median":/\\baverage|mean\\b/.test(lower)?"mean":/\\bminimum|lowest\\b/.test(lower)?"min":/\\bmaximum|highest\\b/.test(lower)?"max":explicitSum?"sum":"count";
  const metric=matched.find(c=>c.name!==group.name)||columns.find(c=>/sales|revenue|amount|profit|quantity/i.test(c.name)&&lower.includes(c.name.toLowerCase()));
  if(summary)throw new Error("Large-file descriptive summaries are not supported yet. Try 'Count opportunities by status'.");
  if(agg!=="count"&&!metric)throw new Error("I found '"+group.name+"' for grouping, but no numeric measure. Specify an actual measure column for "+agg+".");
  return {sheet:requested.name,plan:{sheet:requested.name,operation:"groupby",dimensions:[group.name],aggregation:agg,measure:agg==="count"?undefined:metric?.name,chart:/trend|over time|monthly|yearly|line/.test(lower)?"line":"bar"}};
 }
 async function submit(e:React.FormEvent){e.preventDefault();if(!dataset){setError("Upload a dataset to ask a question.");return}if(!question.trim())return;setError("");setBusy(true);setStage("Calculating a traceable answer");try{const selected=choose(question,dataset);const answer=await analyze(dataset.id,selected.plan);sessionStorage.setItem("analytiq:last-result",JSON.stringify({answer,question,dataset:{id:dataset.id,filename:dataset.filename},sheet:selected.sheet,project}));router.push("/results")}catch(e){setError(e instanceof Error?e.message:String(e))}finally{setBusy(false);setStage("")}}
 return <div className="analyst-shell"><header className="analyst-header"><Link href="/workspace" className="analyst-logo">◈ Analyt<span>IQ</span> AI</Link><span className="analyst-project">{project}</span><Link href="/clean" className="analyst-link">Data cleaning</Link><Link href="/workspace" className="analyst-link">My projects</Link></header><main className="analyst-center">{!ready?<p>Checking your session…</p>:<><div className="analyst-eyebrow">YOUR DATA ANALYST</div><h1>What would you like to <em>analyze?</em></h1><p className="analyst-intro">Upload your data. Ask your question. Get a clear answer with supporting tables, charts and calculations—on a dedicated results page.</p><div className="analyst-file"><input type="file" hidden ref={fileRef} accept=".xlsx,.xlsm,.csv,.tsv" onChange={e=>void upload(e.target.files?.[0])}/><button className="analyst-attach" disabled={busy} onClick={()=>fileRef.current?.click()}>{dataset?"↻ Replace dataset":"+ Add your Excel or CSV file"}</button>{dataset&&<div className="analyst-uploaded"><strong>✓ {dataset.filename}</strong><span>{dataset.sheets.length} worksheet(s) · {dataset.sheets.reduce((n,s)=>n+s.row_count,0).toLocaleString()} reported rows</span></div>}</div><form className="analyst-composer" onSubmit={submit}><textarea aria-label="Ask a data analytics question" value={question} onChange={e=>setQuestion(e.target.value)} placeholder="Ask anything about your data… e.g. Count opportunities by status, show total sales by region, or create a monthly trend chart." rows={4}/><div className="analyst-actions"><small>{dataset?"Source ready · "+dataset.sheets.length+" worksheets available":"Attach a dataset to enable calculations"}</small><button className="analyst-send" type="submit" disabled={!dataset||!question.trim()||busy}>{busy?"Working…":"Analyze →"}</button></div></form>{busy&&<div className="analyst-loading" role="status">{stage||"Working on your data…"}</div>}{error&&<div className="analyst-error" role="alert">{error}</div>}<div className="analyst-examples"><span>Try asking</span>{["Count records by status","Total sales by region","Average amount by category"].map(q=><button key={q} onClick={()=>setQuestion(q)}>{q}</button>)}</div><p className="analyst-note">Current engine supports verified grouped calculations and charts. An unrestricted AI agent, automated pivots and complex spreadsheet editing are still in development.</p></>}</main></div>
}
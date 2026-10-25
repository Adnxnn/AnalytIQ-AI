"""AnalytIQ deterministic local-development analytics API. Not internet-safe without auth."""
from __future__ import annotations
import hashlib,io,os,re,uuid
import httpx
from pathlib import Path
from typing import Literal
import pandas as pd
from fastapi import FastAPI,UploadFile,File,HTTPException,Depends,Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel,Field

app=FastAPI(title="AnalytIQ Analytics Engine",version="0.1.0")
app.add_middleware(CORSMiddleware,allow_origins=[x.strip() for x in os.getenv("ALLOWED_ORIGINS","http://localhost:3000").split(",")],allow_methods=["GET","POST"],allow_headers=["Content-Type"])
ROOT=Path(os.getenv("DATA_DIR","/tmp/analytiq-data"))
ROOT.mkdir(parents=True,exist_ok=True)
MAX_BYTES=int(os.getenv("MAX_UPLOAD_BYTES",str(20*1024*1024)))
EXTS={".csv",".tsv",".xlsx",".xlsm"}

SUPABASE_URL=os.getenv("SUPABASE_URL","").rstrip("/")
def authenticated_user(authorization:str|None=Header(default=None))->str:
 if not SUPABASE_URL:raise HTTPException(503,"Authentication not configured")
 if not authorization or not authorization.startswith("Bearer "):raise HTTPException(401,"Authentication required")
 try:
  with httpx.Client(timeout=8) as client:
   response=client.get(SUPABASE_URL+"/auth/v1/user",headers={"Authorization":authorization,"apikey":os.getenv("SUPABASE_PUBLISHABLE_KEY","")})
  if response.status_code!=200:raise HTTPException(401,"Invalid session")
  user_id=response.json().get("id")
  if not user_id:raise HTTPException(401,"Invalid identity")
  return str(user_id)
 except httpx.RequestError as exc:raise HTTPException(503,"Auth provider unavailable") from exc


class Plan(BaseModel):
 sheet:str
 operation:Literal["groupby","describe"]="groupby"
 dimensions:list[str]=Field(default_factory=list,max_length=3)
 measure:str|None=None
 aggregation:Literal["count","sum","mean","median","min","max"]="count"
 chart:Literal["bar","line"]="bar"

def storage_headers(token: str):
 return {"Authorization": "Bearer " + token, "apikey": os.environ["SUPABASE_PUBLISHABLE_KEY"]}

def read_sheets(blob: bytes, ext: str):
 stream=io.BytesIO(blob)
 if ext in (".xlsx",".xlsm"):
  return pd.read_excel(stream,sheet_name=None,engine="openpyxl")
 return {"Data":pd.read_csv(stream,sep="\t" if ext==".tsv" else ",")}

def stored_source(identifier: str, user_id: str, token: str):
 if not re.fullmatch(r"[a-f0-9]{64}",identifier):raise HTTPException(400,"Invalid identifier")
 with httpx.Client(timeout=30) as client:
  r=client.post(SUPABASE_URL+"/storage/v1/object/list/analytiq-originals",headers=storage_headers(token),json={"prefix":user_id+"/"+identifier,"limit":10})
  if r.status_code!=200:raise HTTPException(502,"Storage listing failed")
  matches=[x["name"] for x in r.json() if x.get("name","").startswith(identifier+".")]
  if len(matches)!=1:raise HTTPException(404,"Dataset unavailable")
  name=matches[0]
  r=client.get(SUPABASE_URL+"/storage/v1/object/authenticated/analytiq-originals/"+user_id+"/"+name,headers=storage_headers(token))
  if r.status_code!=200:raise HTTPException(404,"Source not found")
  return r.content,Path(name).suffix

def safe(v):
 if pd.isna(v):return None
 if hasattr(v,"isoformat"):return v.isoformat()
 if hasattr(v,"item"):return safe(v.item())
 if isinstance(v,float) and not pd.notna(v):return None
 return v

def rows(df:pd.DataFrame):
 return [{str(k):safe(v) for k,v in row.items()} for row in df.to_dict("records")]

def profile(name:str,df:pd.DataFrame):
 if len(set(map(str,df.columns)))!=len(df.columns):raise HTTPException(422,"Duplicate column headers are unsupported")
 df=df.copy()
 df.columns=[str(c) for c in df.columns]
 warnings=[]
 if int(df.isna().sum().sum()):warnings.append("Missing values detected")
 if int(df.duplicated().sum()):warnings.append("Duplicate rows detected")
 return {"name":name,"row_count":len(df),"column_count":len(df.columns),"columns":[{"name":str(c),"dtype":str(df[c].dtype),"missing":int(df[c].isna().sum()),"distinct":int(df[c].nunique(dropna=True))} for c in df.columns],"preview":rows(df.head(80)),"warnings":warnings}

@app.get("/health")
def health():return {"status":"ok","mode":"authenticated"}

@app.post("/datasets")
async def upload(file:UploadFile=File(...),user_id:str=Depends(authenticated_user),authorization:str=Header(...)):
 name=Path(file.filename or "upload.csv").name
 ext=Path(name).suffix.lower()
 if ext not in EXTS:raise HTTPException(415,"Unsupported file format")
 blob=await file.read(MAX_BYTES+1)
 if len(blob)>MAX_BYTES:raise HTTPException(413,"Maximum upload size exceeded")
 digest=hashlib.sha256(blob).hexdigest()
 try:sheets=read_sheets(blob,ext)
 except Exception as e:raise HTTPException(422,"Could not parse dataset") from e
 token=authorization.removeprefix("Bearer ").strip()
 with httpx.Client(timeout=30) as client:
  r=client.post(SUPABASE_URL+"/storage/v1/object/analytiq-originals/"+user_id+"/"+digest+ext,headers={**storage_headers(token),"Content-Type":"application/octet-stream","x-upsert":"false"},content=blob)
 if r.status_code not in (200,201,409):raise HTTPException(502,"Storage upload failed")
 if not sheets:raise HTTPException(422,"No worksheets")
 return {"id":digest,"filename":name,"sheets":[profile(k,v) for k,v in sheets.items()]}

@app.post("/datasets/{identifier}/analyze")
def analyze(identifier:str,plan:Plan,user_id:str=Depends(authenticated_user),authorization:str=Header(...)):
 try:sheets=read_sheets(*stored_source(identifier,user_id,authorization.removeprefix("Bearer ").strip()))
 except Exception as e:raise HTTPException(422,"Unreadable dataset") from e
 if plan.sheet not in sheets:raise HTTPException(422,"Unknown worksheet")
 df=sheets[plan.sheet].copy()
 df.columns=[str(c) for c in df.columns]
 if plan.operation=="describe":
  out=df.describe(include="all").reset_index().rename(columns={"index":"Statistic"})
  return {"run_id":str(uuid.uuid4()),"title":"Dataset descriptive statistics","source_sheet":plan.sheet,"row_count":len(df),"data":rows(out.fillna("")),"methodology":"Pandas describe(include=all), no synthetic statistics.","checks":{"source_rows":len(df)},"warnings":[]}
 if not plan.dimensions:raise HTTPException(422,"Select at least one grouping field")
 for col in [*plan.dimensions,*([plan.measure] if plan.measure else [])]:
  if col not in df.columns:raise HTTPException(422,f"Unknown column: {col}")
 if plan.aggregation!="count" and not plan.measure:raise HTTPException(422,"Choose a numeric measure")
 if plan.measure and plan.aggregation!="count":
  series=pd.to_numeric(df[plan.measure],errors="coerce")
  if series.notna().sum()==0:raise HTTPException(422,"Measure has no numeric values")
  df[plan.measure]=series
 groups=df.groupby(plan.dimensions,dropna=False,sort=True)
 if plan.aggregation=="count":
  out=groups.size().reset_index(name="value")
 else:
  out=groups[plan.measure].agg(plan.aggregation).reset_index(name="value")
 if len(out)>1000:raise HTTPException(422,"Too many groups for interactive display; apply a smaller grouping")
 if plan.aggregation=="count" and int(out.value.sum())!=len(df):raise HTTPException(500,"Aggregation validation failed")
 return {"run_id":str(uuid.uuid4()),"title":plan.aggregation.title()+" by "+", ".join(plan.dimensions),"source_sheet":plan.sheet,"row_count":len(df),"data":rows(out),"methodology":f"Grouped all {len(df)} records in {plan.sheet} by {plan.dimensions}; aggregation={plan.aggregation}, measure={plan.measure or 'row count'}; null groups retained.","checks":{"source_rows":len(df),"group_count":len(out),"sum_of_group_counts":int(out.value.sum()) if plan.aggregation=="count" else None,"count_reconciles":bool(int(out.value.sum())==len(df)) if plan.aggregation=="count" else None},"warnings":[],"chart":{"type":plan.chart,"x":plan.dimensions[0],"y":"value"}}

@app.get("/datasets/{identifier}/export")
def export(identifier:str,sheet:str,format:Literal["csv","xlsx"]="csv",user_id:str=Depends(authenticated_user),authorization:str=Header(...)):
 sheets=read_sheets(*stored_source(identifier,user_id,authorization.removeprefix("Bearer ").strip()))
 if sheet not in sheets:raise HTTPException(422,"Unknown worksheet")
 df=sheets[sheet]
 output=io.BytesIO()
 if format=="csv":
  output.write(df.to_csv(index=False).encode("utf-8-sig"))
  media="text/csv"
 else:
  with pd.ExcelWriter(output,engine="openpyxl") as writer:df.to_excel(writer,index=False,sheet_name="Export")
  media="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
 output.seek(0)
 return StreamingResponse(output,media_type=media,headers={"Content-Disposition":f'attachment; filename="analytiq-export.{format}"'})

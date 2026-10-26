"""AnalytIQ deterministic local-development analytics API. Not internet-safe without auth."""
from __future__ import annotations
import hashlib,io,os,re,uuid,collections,math,csv
from openpyxl import load_workbook
import httpx
from pathlib import Path
from typing import Literal
import pandas as pd
from fastapi import FastAPI,UploadFile,File,HTTPException,Depends,Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel,Field

app=FastAPI(title="AnalytIQ Analytics Engine",version="0.1.0")
app.add_middleware(CORSMiddleware,allow_origins=[x.strip() for x in os.getenv("ALLOWED_ORIGINS","http://localhost:3000").split(",")],allow_methods=["GET","POST"],allow_headers=["Content-Type","Authorization","Accept"])
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
 operation:Literal["groupby","describe","count"]="groupby"
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
  r=client.post(SUPABASE_URL+"/storage/v1/object/list/analytiq-originals",headers=storage_headers(token),json={"prefix":user_id,"limit":1000})
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


def detect_header(iterator):
 """Scan up to 30 early rows for a likely labeled table header."""
 import itertools
 sampled=list(itertools.islice(iterator,30))
 if not sampled: return None,iter(())
 def score(row):
  values=[str(v).strip() for v in row if v is not None and str(v).strip()]
  text=[v for v in values if not v.replace(".","",1).isdigit()]
  unique=len(set(v.lower() for v in text))
  meaningful=sum(len(v)>2 and not v.lower().startswith("unnamed") for v in text)
  keywords=sum(bool(re.search(r"status|opportunit|date|amount|revenue|client|industr|probabilit|leader|phase|region|category|name|id|description|year|month|value|sales",v,re.I)) for v in text)
  return (meaningful>=2)*30 + min(unique,25)*3 + meaningful + keywords*10 - (len(values)-unique)*2
 ranked=sorted(range(len(sampled)),key=lambda i:(score(sampled[i]),-i),reverse=True)
 index=ranked[0]
 return sampled[index],itertools.chain(sampled[index+1:],iterator)

def lightweight_profile(blob:bytes,ext:str):
 """Bounded-memory workbook inspection. Totals use worksheet dimensions; preview is real rows."""
 if ext in (".xlsx",".xlsm"):
  workbook=load_workbook(io.BytesIO(blob),read_only=True,data_only=True,keep_links=False)
  try:
   results=[]
   for ws in workbook.worksheets:
    iterator=ws.iter_rows(values_only=True)
    header,iterator=detect_header(iterator)
    if header is None:continue
    names=[str(x) if x is not None else "Unnamed "+str(i+1) for i,x in enumerate(header)]
    if len(names)!=len(set(names)):raise HTTPException(422,"Duplicate column headers are unsupported")
    samples=list(__import__("itertools").islice(iterator,80))
    preview=[{name:safe(row[i] if i<len(row) else None) for i,name in enumerate(names)} for row in samples]
    columns=[{"name":name,"dtype":"sampled","missing":sum(1 for row in samples if i>=len(row) or row[i] is None),"distinct":len({str(row[i]) for row in samples if i<len(row) and row[i] is not None})} for i,name in enumerate(names)]
    results.append({"name":ws.title,"row_count":max(0,(ws.max_row or 1)-1),"column_count":len(names),"columns":columns,"preview":preview,"warnings":["Column types, missing counts and distinct counts are based on the first 80 records; row count comes from workbook dimensions. Full analyses must scan the source."]})
   return results
  finally:workbook.close()
 if ext in (".csv",".tsv"):
  sample=pd.read_csv(io.BytesIO(blob),sep="\\t" if ext==".tsv" else ",",nrows=80)
  p=profile("Data",sample)
  p["row_count"]=max(0,blob.count(b"\\n")-1)
  p["warnings"].append("Row count estimated from line breaks; column statistics sampled from first 80 records.")
  return [p]
 raise HTTPException(415,"Unsupported dataset format")

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

@app.get("/datasets/{identifier}/profile")
def profile_uploaded(identifier:str,user_id:str=Depends(authenticated_user),authorization:str=Header(...)):
 token=authorization.removeprefix("Bearer ").strip()
 try:
  blob,ext=stored_source(identifier,user_id,token)
  if len(blob)>MAX_BYTES:raise HTTPException(413,"File exceeds server processing limit")
  sheets=lightweight_profile(blob,ext)
 except HTTPException:raise
 except Exception as e:raise HTTPException(422,"Unable to inspect uploaded file") from e
 if not sheets:raise HTTPException(422,"No supported worksheets")
 return {"id":identifier,"filename":"Uploaded dataset","sheets":sheets}


def streaming_aggregate(blob:bytes,ext:str,plan:Plan):
 if plan.operation not in ("groupby","count") or plan.aggregation=="median":
  raise HTTPException(422,"This operation requires a background processing worker for large datasets. Count, sum, mean, min and max are available using streaming.")
 if plan.operation=="groupby" and not plan.dimensions:raise HTTPException(422,"Select at least one grouping field")
 if ext in (".xlsx",".xlsm"):
  book=load_workbook(io.BytesIO(blob),read_only=True,data_only=True,keep_links=False)
  if plan.sheet not in book.sheetnames:
   book.close();raise HTTPException(422,"Unknown worksheet")
  worksheet=book[plan.sheet]
  iterator=worksheet.iter_rows(values_only=True)
 else:
  book=None
  stream=io.StringIO(blob.decode("utf-8-sig",errors="replace"))
  iterator=csv.reader(stream,delimiter="\t" if ext==".tsv" else ",")
 header,iterator=detect_header(iterator)
 if header is None:raise HTTPException(422,"Empty worksheet")
 fields=[str(c) if c is not None else "" for c in header]
 needed=[*plan.dimensions,*([plan.measure] if plan.measure else [])]
 for name in needed:
  if name not in fields:raise HTTPException(422,"Unknown column: "+str(name))
 if plan.aggregation!="count" and not plan.measure:raise HTTPException(422,"Choose a numeric measure")
 indices=[fields.index(c) for c in plan.dimensions]
 measure_index=fields.index(plan.measure) if plan.measure else None
 groups={}
 total=0
 valid_measures=0
 try:
  for row in iterator:
   if not row or all(value is None or value=="" for value in row):continue
   total+=1
   key=tuple(str(row[i]) if i<len(row) and row[i] is not None else "" for i in indices)
   if key not in groups:
    if len(groups)>=1000:raise HTTPException(422,"Too many groups to display (over 1,000). Narrow your grouping.")
    groups[key]=[0,0.0,None,None,0]
   state=groups[key];state[0]+=1
   if plan.aggregation!="count":
    raw=row[measure_index] if measure_index is not None and measure_index<len(row) else None
    try:value=float(raw)
    except (TypeError,ValueError):continue
    if not math.isfinite(value):continue
    valid_measures+=1
    state[1]+=value;state[4]+=1
    state[2]=value if state[2] is None else min(state[2],value)
    state[3]=value if state[3] is None else max(state[3],value)
 finally:
  if book is not None:book.close()
 if plan.aggregation!="count" and not valid_measures:raise HTTPException(422,"Measure has no numeric values")
 output=[]
 for key,state in sorted(groups.items()):
  count,sm,mn,mx,n=state
  value={"count":count,"sum":sm,"mean":sm/n if n else None,"min":mn,"max":mx}[plan.aggregation]
  output.append({**dict(zip(plan.dimensions,key)),"value":value})
 return {"run_id":str(uuid.uuid4()),"title":("Total rows" if plan.operation=="count" else plan.aggregation.title()+" by "+", ".join(plan.dimensions)),"source_sheet":plan.sheet,"row_count":total,"data":([{"metric":"Rows","value":total}] if plan.operation=="count" else output),"methodology":"Streamed source records using bounded-memory aggregation; blank groups retained; invalid numeric measure cells excluded.","checks":{"source_rows":total,"group_count":len(groups),"sum_of_group_counts":sum(v[0] for v in groups.values()) if plan.aggregation=="count" else None,"count_reconciles":sum(v[0] for v in groups.values())==total if plan.aggregation=="count" else None},"warnings":[],"chart":(None if plan.operation=="count" else {"type":plan.chart,"x":plan.dimensions[0],"y":"value"})}

@app.post("/datasets/{identifier}/analyze")
def analyze(identifier:str,plan:Plan,user_id:str=Depends(authenticated_user),authorization:str=Header(...)):
 try:blob,ext=stored_source(identifier,user_id,authorization.removeprefix("Bearer ").strip())
 except HTTPException:raise
 except Exception as e:raise HTTPException(422,"Unreadable dataset") from e
 if len(blob)>4*1024*1024:return streaming_aggregate(blob,ext,plan)
 try:sheets=read_sheets(blob,ext)
 except Exception as e:raise HTTPException(422,"Unreadable dataset") from e
 if plan.sheet not in sheets:raise HTTPException(422,"Unknown worksheet")
 df=sheets[plan.sheet].copy()
 df.columns=[str(c) for c in df.columns]
 if plan.operation=="count":
  return {"run_id":str(uuid.uuid4()),"title":"Total rows","source_sheet":plan.sheet,"row_count":len(df),"data":[{"metric":"Rows","value":len(df)}],"methodology":"Counted parsed records in the selected worksheet; no grouping field or numeric measure required.","checks":{"source_rows":len(df),"count_reconciles":True},"warnings":[],"chart":None}
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


class CleaningOptions(BaseModel):
 sheet:str
 remove_duplicates:bool=True
 trim_whitespace:bool=True
 drop_empty_rows:bool=True
 drop_empty_columns:bool=True
 missing_strategy:Literal["keep","drop_rows","fill_text","fill_zero"]="keep"

def cleaned_frame(df:pd.DataFrame,opts:CleaningOptions):
 df=df.copy()
 before=len(df)
 blanks_before=int(df.isna().sum().sum())
 if opts.trim_whitespace:
  for col in df.select_dtypes(include=["object"]).columns:
   df[col]=df[col].map(lambda x:x.strip() if isinstance(x,str) else x)
   df[col]=df[col].replace("",pd.NA)
 duplicates=int(df.duplicated().sum())
 if opts.drop_empty_rows:df=df.dropna(how="all")
 if opts.drop_empty_columns:df=df.dropna(axis=1,how="all")
 if opts.remove_duplicates:df=df.drop_duplicates()
 if opts.missing_strategy=="drop_rows":df=df.dropna()
 elif opts.missing_strategy=="fill_text":
  for col in df.select_dtypes(include=["object","string"]).columns:df[col]=df[col].fillna("Missing")
 elif opts.missing_strategy=="fill_zero":
  for col in df.select_dtypes(include=["number"]).columns:df[col]=df[col].fillna(0)
 return df,{"rows_before":before,"rows_after":len(df),"rows_removed":before-len(df),"duplicate_rows_detected":duplicates,"missing_cells_before":blanks_before,"missing_cells_after":int(df.isna().sum().sum()),"columns_after":len(df.columns)}

@app.post("/datasets/{identifier}/clean/preview")
def clean_preview(identifier:str,options:CleaningOptions,user_id:str=Depends(authenticated_user),authorization:str=Header(...)):
 blob,ext=stored_source(identifier,user_id,authorization.removeprefix("Bearer ").strip())
 if len(blob)>MAX_BYTES:raise HTTPException(413,"File exceeds processing limit")
 try:sheets=read_sheets(blob,ext)
 except Exception as e:raise HTTPException(422,"Could not read source workbook") from e
 if options.sheet not in sheets:raise HTTPException(422,"Unknown worksheet")
 cleaned,report=cleaned_frame(sheets[options.sheet],options)
 return {"report":report,"preview":rows(cleaned.head(30)),"columns":list(map(str,cleaned.columns)),"warning":"Preview only. Original uploaded file is unchanged. Review before downloading."}

@app.post("/datasets/{identifier}/clean/download")
def clean_download(identifier:str,options:CleaningOptions,user_id:str=Depends(authenticated_user),authorization:str=Header(...)):
 blob,ext=stored_source(identifier,user_id,authorization.removeprefix("Bearer ").strip())
 if len(blob)>MAX_BYTES:raise HTTPException(413,"File exceeds processing limit")
 try:sheets=read_sheets(blob,ext)
 except Exception as e:raise HTTPException(422,"Could not read source workbook") from e
 if options.sheet not in sheets:raise HTTPException(422,"Unknown worksheet")
 cleaned,_=cleaned_frame(sheets[options.sheet],options)
 out=io.BytesIO()
 with pd.ExcelWriter(out,engine="openpyxl") as writer:cleaned.to_excel(writer,index=False,sheet_name="Cleaned")
 out.seek(0)
 return StreamingResponse(out,media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",headers={"Content-Disposition":'attachment; filename="analytiq-cleaned.xlsx"'})

from fastapi import FastAPI, HTTPException, Header, UploadFile, File
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from pathlib import Path
from datetime import datetime, timezone
from web3 import Web3
import os, json, secrets, io
import requests
try:
 import psycopg
 from psycopg.rows import dict_row
except Exception: psycopg=None
app=FastAPI(title='1 OF 16000 — Pierre Remixes',version='3.0.0')
ETH_RPC=os.getenv('ETH_RPC_URL','https://ethereum-rpc.publicnode.com'); BASE_RPC=os.getenv('BASE_RPC_URL','https://mainnet.base.org')
MAIN=Web3.to_checksum_address(os.getenv('CONTRACT_ADDRESS','0xcef88f9ff3a204607c1f341435b6f3fb1cd3c382')); GOLD=Web3.to_checksum_address(os.getenv('GOLD_CONTRACT_ADDRESS','0xc253cde2f48b43dc01508afe48fe3806258cfbba'))
OPEPEN=os.getenv('OPEPEN_API_BASE','https://api.opepen.art/v1').rstrip('/'); DATABASE_URL=os.getenv('DATABASE_URL',''); ADMIN_KEY=os.getenv('ADMIN_KEY',''); CRON_SECRET=os.getenv('CRON_SECRET',''); FILEBASE_RPC_URL=os.getenv('FILEBASE_RPC_URL','https://rpc.filebase.io').rstrip('/'); FILEBASE_RPC_TOKEN=os.getenv('FILEBASE_RPC_TOKEN','')
ERC721_ABI=[{'inputs':[],'name':'totalSupply','outputs':[{'type':'uint256'}],'stateMutability':'view','type':'function'},{'inputs':[],'name':'baseURI','outputs':[{'type':'string'}],'stateMutability':'view','type':'function'},{'inputs':[{'type':'uint256','name':'tokenId'}],'name':'tokenURI','outputs':[{'type':'string'}],'stateMutability':'view','type':'function'},{'inputs':[{'type':'uint256','name':'tokenId'}],'name':'ownerOf','outputs':[{'type':'address'}],'stateMutability':'view','type':'function'}]
ERC1155_ABI=[{'inputs':[{'type':'address','name':'account'},{'type':'uint256','name':'id'}],'name':'balanceOf','outputs':[{'type':'uint256'}],'stateMutability':'view','type':'function'},{'inputs':[{'type':'uint256','name':'id'}],'name':'totalSupply','outputs':[{'type':'uint256'}],'stateMutability':'view','type':'function'},{'inputs':[{'type':'bytes4','name':'interfaceId'}],'name':'supportsInterface','outputs':[{'type':'bool'}],'stateMutability':'view','type':'function'}]
SCHEMA='''CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL); CREATE TABLE IF NOT EXISTS events(event_key TEXT PRIMARY KEY,event_type TEXT NOT NULL,source_id TEXT NOT NULL,project_uuid TEXT,project_name TEXT,contributor_address TEXT,image_id TEXT,image_uuid TEXT,source_created_at TEXT,first_seen_at TEXT NOT NULL,status TEXT NOT NULL,burn_value INTEGER NOT NULL DEFAULT 1,raw_json JSONB); CREATE TABLE IF NOT EXISTS scans(id BIGSERIAL PRIMARY KEY,engine TEXT NOT NULL DEFAULT 'main',started_at TEXT NOT NULL,completed_at TEXT,global_set_total BIGINT,recent_submission_window BIGINT NOT NULL DEFAULT 0,open_projects BIGINT NOT NULL DEFAULT 0,contribution_records BIGINT NOT NULL DEFAULT 0,new_submissions BIGINT NOT NULL DEFAULT 0,new_contributions BIGINT NOT NULL DEFAULT 0,failures BIGINT NOT NULL DEFAULT 0,incomplete_projects BIGINT NOT NULL DEFAULT 0,certified BOOLEAN NOT NULL DEFAULT FALSE,notes TEXT); CREATE TABLE IF NOT EXISTS burn_batches(id BIGSERIAL PRIMARY KEY,engine TEXT NOT NULL,created_at TEXT NOT NULL,status TEXT NOT NULL,payload_json JSONB NOT NULL,event_keys_json JSONB NOT NULL,preflight_json JSONB,verified_json JSONB,notes TEXT); CREATE TABLE IF NOT EXISTS drafts(token_id INTEGER PRIMARY KEY,updated_at TEXT NOT NULL,metadata_json JSONB NOT NULL,live_metadata_uri TEXT,image_uri TEXT); CREATE TABLE IF NOT EXISTS version_history(id BIGSERIAL PRIMARY KEY,created_at TEXT NOT NULL,label TEXT,base_uri TEXT,cid TEXT,notes TEXT,payload_json JSONB);'''
def nowiso(): return datetime.now(timezone.utc).isoformat()
def db():
 if not DATABASE_URL or psycopg is None:return None
 c=psycopg.connect(DATABASE_URL,row_factory=dict_row); c.execute(SCHEMA); c.commit(); return c
def require_admin(k):
 if not ADMIN_KEY or not secrets.compare_digest(k or '',ADMIN_KEY):raise HTTPException(401,'Admin key required')
def w3eth():return Web3(Web3.HTTPProvider(ETH_RPC,request_kwargs={'timeout':10}))
def w3base():return Web3(Web3.HTTPProvider(BASE_RPC,request_kwargs={'timeout':10}))
def ipfs_urls(uri):
 if not uri:return []
 if uri.startswith('ipfs://'):
  t=uri[7:].lstrip('/'); return [f'https://ipfs.filebase.io/ipfs/{t}',f'https://dweb.link/ipfs/{t}',f'https://ipfs.io/ipfs/{t}']
 return [uri] if uri.startswith(('http://','https://')) else []
def fetch_json(uri):
 for u in ipfs_urls(uri):
  try:
   r=requests.get(u,timeout=18,headers={'Accept':'application/json,*/*','User-Agent':'VisualGenome/3.0'})
   if r.ok and isinstance(r.json(),dict):return r.json(),u
  except Exception:pass
 raise HTTPException(502,'Could not resolve metadata')
def osession():
 s=requests.Session();s.headers.update({'Accept':'application/json,*/*','Origin':'https://opepen.art','Referer':'https://opepen.art/','User-Agent':'VisualGenomeDeflation/3.0'});return s
def getj(s,u,p=None):r=s.get(u,params=p,timeout=25);r.raise_for_status();return r.json()
def extract(p):
 arr=p if isinstance(p,list) else []
 if isinstance(p,dict):
  for k in ('data','submissions','items','results','setSubmissions'):
   v=p.get(k)
   if isinstance(v,list):arr=v;break
   if isinstance(v,dict):
    for kk in ('data','items','results'):
     if isinstance(v.get(kk),list):arr=v[kk];break
 out=[]
 for x in arr:
  if not isinstance(x,dict):continue
  x=x.get('submission') if isinstance(x.get('submission'),dict) else x
  if isinstance(x.get('uuid'),str):out.append(x)
 return out
def discover(open_only=False):
 s=osession();best={};variants=[{'sort':'latest','per_page':100},{'sort':'latest','limit':100},{'per_page':100}]
 if open_only:variants=[{**v,'open_for_participation':'true'} for v in variants]+[{**v,'participation':'open'} for v in variants]
 for base in variants:
  local={}
  for page in range(1,101):
   try:p=getj(s,f'{OPEPEN}/set-submissions',{**base,'page':page})
   except Exception:break
   items=extract(p)
   if not items:break
   for x in items:
    if open_only and x.get('open_for_participation') is False:continue
    local[str(x['uuid'])]=x
   if len(items)<int(base.get('per_page') or base.get('limit') or 100):break
  if len(local)>len(best):best=local
 return best
def detail(u):
 p=getj(osession(),f'{OPEPEN}/set-submissions/{u}');return p.get('submission') if isinstance(p,dict) and isinstance(p.get('submission'),dict) else p
def global_total():
 try:return int(((getj(osession(),f'{OPEPEN}/stats') or {}).get('submissions') or {}).get('sets'))
 except Exception:return None
def run_scan(engine):
 c=db()
 if not c:raise HTTPException(503,'DATABASE_URL not configured')
 subs=discover(False);opens=discover(True);gt=global_total();bk=f'{engine}_baseline_at';baseline=not bool(c.execute('SELECT value FROM settings WHERE key=%s',(bk,)).fetchone());ns=nc=fail=inc=records=0
 for u,item in subs.items():
  key=f'{engine}:submission:{u}'
  if c.execute('SELECT 1 FROM events WHERE event_key=%s',(key,)).fetchone():continue
  st='baseline' if baseline else 'pending';c.execute('INSERT INTO events(event_key,event_type,source_id,project_uuid,project_name,source_created_at,first_seen_at,status,raw_json) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING',(key,'submission',u,u,item.get('name',''),item.get('created_at'),nowiso(),st,json.dumps(item)));ns+=st=='pending'
 for u in sorted(opens):
  try:
   d=detail(u);imgs=d.get('participationImages') or [];records+=len(imgs) if isinstance(imgs,list) else 0
   if int(d.get('contributions_count') or 0)>len(imgs):inc+=1
   for r in imgs:
    if not isinstance(r,dict) or r.get('id') is None:continue
    key=f'{engine}:contribution:{r["id"]}'
    if c.execute('SELECT 1 FROM events WHERE event_key=%s',(key,)).fetchone():continue
    creator=r.get('creator') if isinstance(r.get('creator'),dict) else {};image=r.get('image') if isinstance(r.get('image'),dict) else {};st='baseline' if baseline else 'pending';c.execute('INSERT INTO events(event_key,event_type,source_id,project_uuid,project_name,contributor_address,image_id,image_uuid,source_created_at,first_seen_at,status,raw_json) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING',(key,'contribution',str(r['id']),u,d.get('name',''),r.get('creator_address') or creator.get('address') or '',str(r.get('image_id') or ''),str(image.get('uuid') or ''),r.get('created_at'),nowiso(),st,json.dumps(r)));nc+=st=='pending'
  except Exception:fail+=1
 cert=bool(subs) and bool(opens) and fail==0 and inc==0;notes=f'Global set total {gt}; recent UUID window {len(subs)}; open projects {len(opens)}; contribution records {records}.'
 if baseline:c.execute('INSERT INTO settings(key,value) VALUES(%s,%s) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value',(bk,nowiso()));notes+=' Initial baseline created; historical activity creates 0 burn debt.'
 c.execute('INSERT INTO scans(engine,started_at,completed_at,global_set_total,recent_submission_window,open_projects,contribution_records,new_submissions,new_contributions,failures,incomplete_projects,certified,notes) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',(engine,nowiso(),nowiso(),gt,len(subs),len(opens),records,ns,nc,fail,inc,cert,notes));c.commit();c.close();return {'engine':engine,'global_set_total':gt,'recent_submission_window':len(subs),'open_projects':len(opens),'contribution_records':records,'new_submissions':ns,'new_contributions':nc,'certified':cert,'failures':fail,'incomplete_projects':inc,'notes':notes}
@app.get('/',response_class=HTMLResponse)
def home():return HTMLResponse((Path(__file__).resolve().parent.parent/'public'/'index.html').read_text(encoding='utf-8'))
@app.get('/api/health')
def health():
 e=w3eth();b=w3base();ok=False
 if DATABASE_URL:
  try:c=db();c.close();ok=True
  except Exception:pass
 return {'version':'3.0.0','ethereum':e.is_connected(),'base':b.is_connected(),'database':{'configured':bool(DATABASE_URL),'ok':ok},'filebase':{'configured':bool(FILEBASE_RPC_TOKEN)}}
@app.get('/api/contract/main')
def main_contract():
 w=w3eth();out={'network':'Ethereum','address':MAIN,'connected':w.is_connected()}
 if w.is_connected():
  c=w.eth.contract(address=MAIN,abi=ERC721_ABI)
  try:out['totalSupply']=int(c.functions.totalSupply().call())
  except Exception:out['totalSupply']=None
  try:out['baseURI']=c.functions.baseURI().call()
  except Exception:out['baseURI']=None
 return out
@app.get('/api/contract/gold')
def gold_contract():
 w=w3base();erc=None
 if w.is_connected():
  try:erc=w.eth.contract(address=GOLD,abi=ERC1155_ABI).functions.supportsInterface(bytes.fromhex('d9b67a26')).call()
  except Exception:pass
 return {'network':'Base','chainId':8453,'address':GOLD,'type':'ERC-1155','connected':w.is_connected(),'erc1155':erc}
@app.get('/api/token/{tid}')
def token(tid:int):
 if tid<1 or tid>16000:raise HTTPException(400,'Token out of range')
 c=w3eth().eth.contract(address=MAIN,abi=ERC721_ABI);uri=c.functions.tokenURI(tid).call();owner=c.functions.ownerOf(tid).call();meta,res=fetch_json(uri);image=str(meta.get('image',''));return {'token_id':tid,'owner':owner,'metadata_uri':uri,'resolved_metadata_url':res,'metadata':meta,'image_uri':image,'image_preview':(ipfs_urls(image) or [''])[0]}
class DraftBody(BaseModel):metadata:dict;live_metadata_uri:str='';image_uri:str=''
@app.put('/api/drafts/{tid}')
def save_draft(tid:int,b:DraftBody,x_admin_key:str|None=Header(default=None)):
 require_admin(x_admin_key);c=db()
 if not c:raise HTTPException(503,'Database missing')
 c.execute('INSERT INTO drafts(token_id,updated_at,metadata_json,live_metadata_uri,image_uri) VALUES(%s,%s,%s,%s,%s) ON CONFLICT(token_id) DO UPDATE SET updated_at=EXCLUDED.updated_at,metadata_json=EXCLUDED.metadata_json,live_metadata_uri=EXCLUDED.live_metadata_uri,image_uri=EXCLUDED.image_uri',(tid,nowiso(),json.dumps(b.metadata),b.live_metadata_uri,b.image_uri));c.commit();c.close();return {'ok':True}
@app.get('/api/drafts')
def drafts():
 c=db()
 if not c:return []
 r=c.execute('SELECT token_id,updated_at,metadata_json,live_metadata_uri,image_uri FROM drafts ORDER BY updated_at DESC').fetchall();c.close();return r
@app.get('/api/cid/inspect')
def cid(cid:str,tokens:str='1,16000'):
 ids=[]
 for x in tokens.split(','):
  try:ids.append(int(x.strip()))
  except:pass
 rows=[]
 for tid in ids[:50]:
  try:m,u=fetch_json(f'ipfs://{cid.strip().strip("/")}/{tid}');im=str(m.get('image',''));ok=False
  except Exception as e:rows.append({'token_id':tid,'metadata_ok':False,'image_ok':False,'error':str(e)});continue
  for z in ipfs_urls(im):
   try:
    if requests.get(z,timeout=10,stream=True).ok:ok=True;break
   except:pass
  rows.append({'token_id':tid,'metadata_ok':True,'metadata_url':u,'image_ok':ok,'name':m.get('name',''),'image':im,'attributes_count':len(m.get('attributes') or [])})
 return {'cid':cid,'tested':len(rows),'metadata_resolved':sum(x.get('metadata_ok',False) for x in rows),'images_resolved':sum(x.get('image_ok',False) for x in rows),'tokens':rows}
@app.get('/api/deflation/{engine}/status')
def dstatus(engine:str):
 if engine not in ('main','gold'):raise HTTPException(400,'Bad engine')
 c=db()
 if not c:return {'database_configured':False,'counts':{},'last_scan':None,'pending':[],'latest_batch':None}
 pre=engine+':';counts={r['status']:int(r['n']) for r in c.execute('SELECT status,COUNT(*) n FROM events WHERE event_key LIKE %s GROUP BY status',(pre+'%',)).fetchall()};types={r['event_type']:int(r['n']) for r in c.execute('SELECT event_type,COUNT(*) n FROM events WHERE event_key LIKE %s GROUP BY event_type',(pre+'%',)).fetchall()};last=c.execute('SELECT * FROM scans WHERE engine=%s ORDER BY id DESC LIMIT 1',(engine,)).fetchone();pending=c.execute("SELECT event_key,event_type,source_id,project_name,contributor_address,image_id,source_created_at,first_seen_at,status FROM events WHERE event_key LIKE %s AND status='pending' ORDER BY COALESCE(source_created_at,first_seen_at) LIMIT 500",(pre+'%',)).fetchall();batch=c.execute('SELECT * FROM burn_batches WHERE engine=%s ORDER BY id DESC LIMIT 1',(engine,)).fetchone();c.close();return {'database_configured':True,'counts':{'pending':counts.get('pending',0),'burned':counts.get('burned',0),'baseline':counts.get('baseline',0),'submissions':types.get('submission',0),'contributions':types.get('contribution',0)},'last_scan':last,'pending':pending,'latest_batch':batch}
@app.post('/api/deflation/{engine}/scan')
def scan(engine:str,x_admin_key:str|None=Header(default=None)):
 require_admin(x_admin_key)
 if engine not in ('main','gold'):raise HTTPException(400,'Bad engine')
 return run_scan(engine)
class MainBatch(BaseModel):token_ids:list[int]
@app.post('/api/deflation/main/prepare')
def prep_main(b:MainBatch,x_admin_key:str|None=Header(default=None)):
 require_admin(x_admin_key);c=db();pending=[r['event_key'] for r in c.execute("SELECT event_key FROM events WHERE event_key LIKE 'main:%' AND status='pending' ORDER BY COALESCE(source_created_at,first_seen_at)").fetchall()];last=c.execute("SELECT certified FROM scans WHERE engine='main' ORDER BY id DESC LIMIT 1").fetchone()
 if not last or not last['certified']:raise HTTPException(409,'Latest scan is not coverage-certified')
 ids=[]
 for x in b.token_ids:
  if 1<=int(x)<=16000 and int(x) not in ids:ids.append(int(x))
 if len(ids)<len(pending):raise HTTPException(400,f'Need {len(pending)} reserve token IDs; supplied {len(ids)}')
 chosen=ids[:len(pending)];ct=w3eth().eth.contract(address=MAIN,abi=ERC721_ABI);pre=[]
 for tid in chosen:
  try:pre.append({'token_id':tid,'owner':ct.functions.ownerOf(tid).call()})
  except Exception:pre.append({'token_id':tid,'owner':None})
 row=c.execute("INSERT INTO burn_batches(engine,created_at,status,payload_json,event_keys_json,preflight_json) VALUES('main',%s,'prepared',%s,%s,%s) RETURNING id",(nowiso(),json.dumps({'token_ids':chosen}),json.dumps(pending),json.dumps(pre))).fetchone();c.commit();c.close();return {'batch_id':row['id'],'token_ids':chosen,'event_keys':pending,'preflight':pre}
class GoldBatch(BaseModel):reserve_wallet:str;candidate_ids:list[int]
@app.post('/api/deflation/gold/inventory')
def ginventory(b:GoldBatch):
 if not Web3.is_address(b.reserve_wallet):raise HTTPException(400,'Invalid reserve wallet')
 ct=w3base().eth.contract(address=GOLD,abi=ERC1155_ABI);rows=[];total=0;wallet=Web3.to_checksum_address(b.reserve_wallet)
 for tid in b.candidate_ids[:500]:
  try:bal=int(ct.functions.balanceOf(wallet,int(tid)).call())
  except Exception:bal=0
  try:sup=int(ct.functions.totalSupply(int(tid)).call())
  except Exception:sup=None
  if bal:rows.append({'id':int(tid),'balance':bal,'totalSupply':sup});total+=bal
 return {'wallet':b.reserve_wallet,'available_units':total,'items':rows}
@app.post('/api/deflation/gold/prepare')
def prep_gold(b:GoldBatch,x_admin_key:str|None=Header(default=None)):
 require_admin(x_admin_key);c=db();pending=[r['event_key'] for r in c.execute("SELECT event_key FROM events WHERE event_key LIKE 'gold:%' AND status='pending' ORDER BY COALESCE(source_created_at,first_seen_at)").fetchall()];last=c.execute("SELECT certified FROM scans WHERE engine='gold' ORDER BY id DESC LIMIT 1").fetchone()
 if not last or not last['certified']:raise HTTPException(409,'Latest Gold scan is not coverage-certified')
 if not Web3.is_address(b.reserve_wallet):raise HTTPException(400,'Invalid reserve wallet')
 ct=w3base().eth.contract(address=GOLD,abi=ERC1155_ABI);wallet=Web3.to_checksum_address(b.reserve_wallet);rem=len(pending);alloc=[];pre={}
 for tid in b.candidate_ids[:500]:
  if rem<=0:break
  try:bal=int(ct.functions.balanceOf(wallet,int(tid)).call())
  except Exception:bal=0
  if bal<=0:continue
  use=min(bal,rem);alloc.append({'id':int(tid),'amount':use});pre[str(tid)]={'balance':bal};rem-=use
 if rem>0:raise HTTPException(400,f'Gold reserve is short by {rem} units')
 row=c.execute("INSERT INTO burn_batches(engine,created_at,status,payload_json,event_keys_json,preflight_json) VALUES('gold',%s,'prepared',%s,%s,%s) RETURNING id",(nowiso(),json.dumps({'reserve_wallet':b.reserve_wallet,'allocations':alloc}),json.dumps(pending),json.dumps(pre))).fetchone();c.commit();c.close();return {'batch_id':row['id'],'allocations':alloc,'event_keys':pending,'preflight':pre}
@app.post('/api/filebase/add')
async def fadd(file:UploadFile=File(...),x_admin_key:str|None=Header(default=None)):
 require_admin(x_admin_key)
 if not FILEBASE_RPC_TOKEN:raise HTTPException(503,'FILEBASE_RPC_TOKEN not configured')
 data=await file.read();r=requests.post(f'{FILEBASE_RPC_URL}/api/v0/add',params=[('cid-version','1'),('pin','true')],headers={'Authorization':f'Bearer {FILEBASE_RPC_TOKEN}'},files={'file':(file.filename,io.BytesIO(data),file.content_type or 'application/octet-stream')},timeout=120);r.raise_for_status();p=r.json();return {'cid':p.get('Hash'),'uri':f"ipfs://{p.get('Hash')}"}
@app.get('/api/history')
def history():
 c=db()
 if not c:return []
 r=c.execute('SELECT * FROM version_history ORDER BY id DESC LIMIT 100').fetchall();c.close();return r
@app.get('/api/cron/scan')
def cron(authorization:str|None=Header(default=None)):
 if not CRON_SECRET or not secrets.compare_digest(authorization or '',f'Bearer {CRON_SECRET}'):raise HTTPException(401,'Invalid cron secret')
 return {'main':run_scan('main'),'gold':run_scan('gold')}

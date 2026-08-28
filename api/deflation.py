import os, json, re, requests
from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel
from web3 import Web3
from .db import conn, nowiso, configured
from .core import w3b, GOLD, ERC1155

router = APIRouter()
OPEPEN_SITE = 'https://opepen.art'
OPEPEN_API = os.getenv('OPEPEN_API_BASE','https://api.opepen.art/v1').rstrip('/')
CRON_SECRET = os.getenv('CRON_SECRET','')


def session():
    s=requests.Session()
    s.headers.update({'Accept':'application/json,*/*','Origin':OPEPEN_SITE,'Referer':OPEPEN_SITE+'/','User-Agent':'1of16000-opepen-monitor/4.0'})
    return s

def get_json(s,url,params=None):
    r=s.get(url,params=params,timeout=25)
    r.raise_for_status()
    return r.json()

def extract_list(payload):
    if isinstance(payload,list): return [x for x in payload if isinstance(x,dict)]
    if not isinstance(payload,dict): return []
    for k in ('data','submissions','items','results','setSubmissions'):
        v=payload.get(k)
        if isinstance(v,list): return [x for x in v if isinstance(x,dict)]
    return []

def normalize_submission(x):
    if isinstance(x.get('submission'),dict): x=x['submission']
    uid=x.get('uuid') or x.get('id')
    if uid is None:return None
    return {**x,'uuid':str(uid)}

def discover_submissions(open_only=False):
    s=session(); found={}; params={'sort':'latest','per_page':100}
    if open_only:params['open_for_participation']='true'
    for page in range(1,101):
        payload=get_json(s,f'{OPEPEN_API}/set-submissions',{**params,'page':page})
        items=[normalize_submission(x) for x in extract_list(payload)]
        items=[x for x in items if x]
        if not items:break
        for x in items:found[x['uuid']]=x
        if len(items)<100:break
    return found

def submission_detail(uid):
    payload=get_json(session(),f'{OPEPEN_API}/set-submissions/{uid}')
    if isinstance(payload,dict) and isinstance(payload.get('submission'),dict):return payload['submission']
    return payload if isinstance(payload,dict) else {}

def contribution_rows(detail):
    for key in ('participationImages','participation_images','contributions','images'):
        v=detail.get(key)
        if isinstance(v,list):return [x for x in v if isinstance(x,dict)]
    return []

def contribution_key(row,project_uid):
    rid=row.get('id') or row.get('uuid') or row.get('image_id')
    if rid is not None:return str(rid)
    creator=row.get('creator_address') or ((row.get('creator') or {}).get('address') if isinstance(row.get('creator'),dict) else '')
    image=((row.get('image') or {}).get('uuid') if isinstance(row.get('image'),dict) else '')
    return f'{project_uid}:{creator}:{image}:{row.get("created_at","")}'

def scan(engine):
    if engine not in ('main','gold'):raise HTTPException(400,'Bad engine')
    c=conn()
    if not c:raise HTTPException(503,'Persistent database is not connected yet. Connect the Neon database to Vercel; the scanner will not run without deduplication storage.')
    started=nowiso(); failures=0; incomplete=0; contribution_total=0; new_subs=0; new_contribs=0
    try:
        submissions=discover_submissions(False)
        open_projects=discover_submissions(True)
    except Exception as e:
        c.close();raise HTTPException(502,f'opepen.art scan failed: {e}')
    baseline_row=c.execute('SELECT value FROM settings WHERE key=%s',(engine+'_baseline_at',)).fetchone()
    baseline=not bool(baseline_row)
    initial_status='baseline' if baseline else 'pending'
    for uid,item in submissions.items():
        event_key=f'{engine}:submission:{uid}'
        if c.execute('SELECT 1 FROM events WHERE event_key=%s',(event_key,)).fetchone():continue
        c.execute('INSERT INTO events(event_key,event_type,source_id,project_uuid,project_name,source_created_at,first_seen_at,status,burn_value,raw_json) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,1,%s) ON CONFLICT DO NOTHING',(event_key,'submission',uid,uid,item.get('name') or item.get('title') or '',item.get('created_at'),nowiso(),initial_status,json.dumps(item)))
        if initial_status=='pending':new_subs+=1
    # Contributions are counted per contributed image, not per wallet/profile.
    for uid,item in open_projects.items():
        try:
            detail=submission_detail(uid); rows=contribution_rows(detail); contribution_total+=len(rows)
            expected=int(detail.get('contributions_count') or detail.get('contribution_count') or len(rows) or 0)
            if expected>len(rows):incomplete+=1
            for row in rows:
                source_id=contribution_key(row,uid); event_key=f'{engine}:contribution:{source_id}'
                if c.execute('SELECT 1 FROM events WHERE event_key=%s',(event_key,)).fetchone():continue
                creator=row.get('creator') if isinstance(row.get('creator'),dict) else {}; image=row.get('image') if isinstance(row.get('image'),dict) else {}
                address=row.get('creator_address') or creator.get('address') or creator.get('wallet') or ''
                c.execute('INSERT INTO events(event_key,event_type,source_id,project_uuid,project_name,contributor_address,image_id,image_uuid,source_created_at,first_seen_at,status,burn_value,raw_json) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1,%s) ON CONFLICT DO NOTHING',(event_key,'contribution',source_id,uid,detail.get('name') or item.get('name') or '',address,str(row.get('image_id') or row.get('id') or ''),str(image.get('uuid') or ''),row.get('created_at'),nowiso(),initial_status,json.dumps(row)))
                if initial_status=='pending':new_contribs+=1
        except Exception:
            failures+=1
    certified=bool(submissions) and failures==0 and incomplete==0
    notes=f'Source: opepen.art. Submissions discovered: {len(submissions)}. Open contribution projects: {len(open_projects)}. Contribution images: {contribution_total}. Each submission/image contributes one burn unit.'
    if baseline:
        c.execute('INSERT INTO settings(key,value) VALUES(%s,%s) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value',(engine+'_baseline_at',nowiso()))
        notes+=' Initial scan stored as baseline; historical activity created no burn debt.'
    c.execute('INSERT INTO scans(engine,started_at,completed_at,recent_submission_window,open_projects,contribution_records,new_submissions,new_contributions,failures,incomplete_projects,certified,notes) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',(engine,started,nowiso(),len(submissions),len(open_projects),contribution_total,new_subs,new_contribs,failures,incomplete,certified,notes))
    c.commit();c.close()
    return {'engine':engine,'source':'opepen.art','new_submissions':new_subs,'new_contributions':new_contribs,'burn_units_added':new_subs+new_contribs,'certified':certified,'notes':notes}

def pending_events(c,engine,limit=5000):
    return c.execute("SELECT event_key,event_type,source_id,project_name,contributor_address,source_created_at,burn_value FROM events WHERE event_key LIKE %s AND status='pending' ORDER BY first_seen_at LIMIT %s",(engine+':%',limit)).fetchall()

def parse_ids(value):
    out=[]
    for part in re.split(r'[,\s]+',value.strip()):
        if not part:continue
        if '-' in part:
            try:
                a,b=map(int,part.split('-',1));out.extend(range(min(a,b),max(a,b)+1))
            except:pass
        else:
            try:out.append(int(part))
            except:pass
    return list(dict.fromkeys(x for x in out if x>=0))

class MainBatch(BaseModel):
    reserve_ids:str
class GoldInventory(BaseModel):
    wallet:str
    item_ids:str='1-113'
class GoldBatch(GoldInventory):
    pass

@router.get('/api/deflation/{engine}/status')
def status(engine:str):
    if engine not in ('main','gold'):raise HTTPException(400,'Bad engine')
    c=conn()
    if not c:return {'database_configured':False,'source':'opepen.art','counts':{'pending':0,'burned':0,'baseline':0,'submissions':0,'contributions':0},'last_scan':None,'pending':[]}
    pre=engine+':%'
    statuses={r['status']:int(r['n']) for r in c.execute('SELECT status,COUNT(*) n FROM events WHERE event_key LIKE %s GROUP BY status',(pre,)).fetchall()}
    types={r['event_type']:int(r['n']) for r in c.execute('SELECT event_type,COUNT(*) n FROM events WHERE event_key LIKE %s GROUP BY event_type',(pre,)).fetchall()}
    last=c.execute('SELECT * FROM scans WHERE engine=%s ORDER BY id DESC LIMIT 1',(engine,)).fetchone();pending=pending_events(c,engine,500);c.close()
    return {'database_configured':True,'source':'opepen.art','counts':{'pending':statuses.get('pending',0),'burned':statuses.get('burned',0),'baseline':statuses.get('baseline',0),'submissions':types.get('submission',0),'contributions':types.get('contribution',0)},'last_scan':last,'pending':pending}

@router.post('/api/deflation/{engine}/scan')
def manual_scan(engine:str):return scan(engine)

@router.post('/api/deflation/main/prepare')
def prepare_main(body:MainBatch):
    c=conn()
    if not c:raise HTTPException(503,'Persistent database is not connected')
    events=pending_events(c,'main'); ids=parse_ids(body.reserve_ids)
    need=sum(int(x.get('burn_value') or 1) for x in events)
    if need==0:c.close();return {'pending_burns':0,'token_ids':[],'transactions':[]}
    if len(ids)<need:c.close();raise HTTPException(400,f'Need at least {need} reserve token IDs; only {len(ids)} supplied')
    chosen=ids[:need]; payload={'contract':'0xcef88f9ff3a204607c1f341435b6f3fb1cd3c382','network':'Ethereum','method':'burn(uint256)','token_ids':chosen,'transactions':[{'method':'burn','args':[tid]} for tid in chosen],'source':'opepen.art'}
    cur=c.execute('INSERT INTO burn_batches(engine,created_at,status,payload_json,event_keys_json,notes) VALUES(%s,%s,%s,%s,%s,%s) RETURNING id',('main',nowiso(),'prepared',json.dumps(payload),json.dumps([e['event_key'] for e in events]),'Prepared only; owner wallet must sign')).fetchone();c.commit();c.close();return {'batch_id':cur['id'],'pending_burns':need,**payload}

@router.post('/api/deflation/gold/inventory')
def gold_inventory(body:GoldInventory):
    if not Web3.is_address(body.wallet):raise HTTPException(400,'Invalid reserve wallet')
    w=w3b()
    if not w.is_connected():raise HTTPException(503,'Base RPC unavailable')
    contract=w.eth.contract(address=GOLD,abi=ERC1155); ids=parse_ids(body.item_ids)[:500]; balances=[];total=0
    for tid in ids:
        try:q=int(contract.functions.balanceOf(Web3.to_checksum_address(body.wallet),tid).call())
        except:q=0
        if q:balances.append({'id':tid,'balance':q});total+=q
    return {'wallet':body.wallet,'contract':GOLD,'network':'Base','total_units':total,'items':balances}

@router.post('/api/deflation/gold/prepare')
def prepare_gold(body:GoldBatch):
    c=conn()
    if not c:raise HTTPException(503,'Persistent database is not connected')
    events=pending_events(c,'gold');need=sum(int(x.get('burn_value') or 1) for x in events)
    inv=gold_inventory(GoldInventory(wallet=body.wallet,item_ids=body.item_ids))
    if inv['total_units']<need:c.close();raise HTTPException(400,f'Gold reserve has {inv["total_units"]} units but {need} burns are pending')
    alloc=[];remaining=need
    for item in inv['items']:
        q=min(item['balance'],remaining)
        if q:alloc.append({'id':item['id'],'amount':q});remaining-=q
        if remaining<=0:break
    payload={'contract':GOLD,'network':'Base','wallet':body.wallet,'allocations':alloc,'burn_units':need,'source':'opepen.art','note':'Use the collection burn method supported by the deployed ERC-1155 contract; wallet must sign.'}
    cur=c.execute('INSERT INTO burn_batches(engine,created_at,status,payload_json,event_keys_json,notes) VALUES(%s,%s,%s,%s,%s,%s) RETURNING id',('gold',nowiso(),'prepared',json.dumps(payload),json.dumps([e['event_key'] for e in events]),'Prepared only; owner wallet must sign')).fetchone();c.commit();c.close();return {'batch_id':cur['id'],**payload}

@router.get('/api/cron/scan')
def cron(authorization:str|None=Header(default=None)):
    if CRON_SECRET and authorization != f'Bearer {CRON_SECRET}':raise HTTPException(401,'Invalid cron secret')
    return {'source':'opepen.art','main':scan('main'),'gold':scan('gold')}

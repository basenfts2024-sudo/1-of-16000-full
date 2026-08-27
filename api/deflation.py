import os,json,requests
from fastapi import APIRouter, HTTPException, Header
from .db import conn,nowiso
router=APIRouter();OPEPEN=os.getenv('OPEPEN_API_BASE','https://api.opepen.art/v1').rstrip('/');CRON_SECRET=os.getenv('CRON_SECRET','')
def sess():
 s=requests.Session();s.headers.update({'Accept':'application/json,*/*','Origin':'https://opepen.art','Referer':'https://opepen.art/','User-Agent':'VisualGenomeDeflation/3.1'});return s
def getj(s,u,p=None):r=s.get(u,params=p,timeout=25);r.raise_for_status();return r.json()
def extract(p):
 arr=p if isinstance(p,list) else []
 if isinstance(p,dict):
  for k in ('data','submissions','items','results','setSubmissions'):
   v=p.get(k)
   if isinstance(v,list):arr=v;break
 out=[]
 for x in arr:
  if not isinstance(x,dict):continue
  x=x.get('submission') if isinstance(x.get('submission'),dict) else x
  if isinstance(x.get('uuid'),str):out.append(x)
 return out
def discover(open_only=False):
 s=sess();best={};base={'sort':'latest','per_page':100}
 if open_only:base['open_for_participation']='true'
 local={}
 for page in range(1,101):
  try:p=getj(s,f'{OPEPEN}/set-submissions',{**base,'page':page})
  except:break
  it=extract(p)
  if not it:break
  for x in it:local[str(x['uuid'])]=x
  if len(it)<100:break
 return local
def detail(u):
 p=getj(sess(),f'{OPEPEN}/set-submissions/{u}');return p.get('submission') if isinstance(p,dict) and isinstance(p.get('submission'),dict) else p
def scan(engine):
 c=conn()
 if not c:raise HTTPException(503,'DATABASE_URL not configured')
 subs,opens=discover(False),discover(True);row=c.execute('SELECT value FROM settings WHERE key=%s',(engine+'_baseline_at',)).fetchone();baseline=not bool(row);ns=nc=fail=inc=rec=0
 for u,item in subs.items():
  key=f'{engine}:submission:{u}'
  if c.execute('SELECT 1 FROM events WHERE event_key=%s',(key,)).fetchone():continue
  st='baseline' if baseline else 'pending';c.execute('INSERT INTO events(event_key,event_type,source_id,project_uuid,project_name,source_created_at,first_seen_at,status,raw_json) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING',(key,'submission',u,u,item.get('name',''),item.get('created_at'),nowiso(),st,json.dumps(item)));ns += st=='pending'
 for u in opens:
  try:
   d=detail(u);imgs=d.get('participationImages') or [];rec+=len(imgs)
   if int(d.get('contributions_count') or 0)>len(imgs):inc+=1
   for r in imgs:
    if not isinstance(r,dict) or r.get('id') is None:continue
    key=f'{engine}:contribution:{r["id"]}'
    if c.execute('SELECT 1 FROM events WHERE event_key=%s',(key,)).fetchone():continue
    creator=r.get('creator') if isinstance(r.get('creator'),dict) else {};image=r.get('image') if isinstance(r.get('image'),dict) else {};st='baseline' if baseline else 'pending';c.execute('INSERT INTO events(event_key,event_type,source_id,project_uuid,project_name,contributor_address,image_id,image_uuid,source_created_at,first_seen_at,status,raw_json) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING',(key,'contribution',str(r['id']),u,d.get('name',''),r.get('creator_address') or creator.get('address') or '',str(r.get('image_id') or ''),str(image.get('uuid') or ''),r.get('created_at'),nowiso(),st,json.dumps(r)));nc += st=='pending'
  except:fail+=1
 cert=bool(subs) and bool(opens) and fail==0 and inc==0;notes=f'Recent submissions {len(subs)}; open projects {len(opens)}; contributions {rec}.'
 if baseline:c.execute('INSERT INTO settings(key,value) VALUES(%s,%s) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value',(engine+'_baseline_at',nowiso()));notes+=' Initial baseline created; historical activity creates 0 burn debt.'
 c.execute('INSERT INTO scans(engine,started_at,completed_at,recent_submission_window,open_projects,contribution_records,new_submissions,new_contributions,failures,incomplete_projects,certified,notes) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',(engine,nowiso(),nowiso(),len(subs),len(opens),rec,ns,nc,fail,inc,cert,notes));c.commit();c.close();return {'engine':engine,'new_submissions':ns,'new_contributions':nc,'certified':cert,'notes':notes}
@router.get('/api/deflation/{engine}/status')
def status(engine:str):
 if engine not in ('main','gold'):raise HTTPException(400,'Bad engine')
 c=conn()
 if not c:return {'database_configured':False,'counts':{},'last_scan':None,'pending':[]}
 pre=engine+':';counts={r['status']:int(r['n']) for r in c.execute('SELECT status,COUNT(*) n FROM events WHERE event_key LIKE %s GROUP BY status',(pre+'%',)).fetchall()};types={r['event_type']:int(r['n']) for r in c.execute('SELECT event_type,COUNT(*) n FROM events WHERE event_key LIKE %s GROUP BY event_type',(pre+'%',)).fetchall()};last=c.execute('SELECT * FROM scans WHERE engine=%s ORDER BY id DESC LIMIT 1',(engine,)).fetchone();pending=c.execute("SELECT event_key,event_type,project_name,contributor_address,source_created_at FROM events WHERE event_key LIKE %s AND status='pending' ORDER BY first_seen_at LIMIT 500",(pre+'%',)).fetchall();c.close();return {'database_configured':True,'counts':{'pending':counts.get('pending',0),'burned':counts.get('burned',0),'baseline':counts.get('baseline',0),'submissions':types.get('submission',0),'contributions':types.get('contribution',0)},'last_scan':last,'pending':pending}
@router.post('/api/deflation/{engine}/scan')
def manual(engine:str):
 if engine not in ('main','gold'):raise HTTPException(400,'Bad engine')
 return scan(engine)
@router.get('/api/cron/scan')
def cron(authorization:str|None=Header(default=None)):
 if CRON_SECRET and authorization != f'Bearer {CRON_SECRET}':raise HTTPException(401,'Invalid cron secret')
 return {'main':scan('main'),'gold':scan('gold')}

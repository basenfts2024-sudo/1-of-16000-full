import csv, io, json, re
from fastapi import APIRouter, UploadFile, File, HTTPException
from pydantic import BaseModel
from .db import conn, nowiso
router=APIRouter()

def remix_key_from_name(name):
    stem=str(name or '').rsplit('/',1)[-1].rsplit('.',1)[0]
    m=re.search(r'(\d+)',stem)
    return str(int(m.group(1))) if m else stem

def normalize_ref(d):
    return {'set_number':str(d.get('set_number') or d.get('set') or ''),'set_name':str(d.get('set_name') or d.get('name') or ''),'artist':str(d.get('artist') or d.get('creator') or d.get('artist_name') or ''),'local_file':str(d.get('local_file') or d.get('reference_file') or d.get('image') or ''),'source_url':str(d.get('source_url') or d.get('url') or d.get('best_reference_url') or ''),'width':d.get('width'),'height':d.get('height'),'animated':bool(d.get('animated',False)),'sha256':str(d.get('sha256') or ''),'embedding_index':d.get('embedding_index')}

def normalize_matches(payload):
    out=[]
    if isinstance(payload,list): items=payload
    elif isinstance(payload,dict): items=payload.get('results') or payload.get('matches') or payload.get('data') or []
    else: items=[]
    for item in items:
        if not isinstance(item,dict):continue
        image=item.get('image') or item.get('filename') or item.get('remix') or ''
        rk=remix_key_from_name(image)
        candidates=item.get('matches') or item.get('candidates') or []
        if candidates:
            for rank,m in enumerate(candidates,1):
                if not isinstance(m,dict):continue
                support=m.get('supporting_matches') or []
                best=support[0] if support and isinstance(support[0],dict) else {}
                out.append({'remix_key':rk,'image':image,'rank':rank,'set_number':m.get('set_number',''),'set_name':m.get('set_name',''),'artist':m.get('artist',''),'score':m.get('score',0),'confidence':m.get('confidence',''),'best_reference_file':best.get('reference_file') or m.get('best_reference_file',''),'best_reference_url':best.get('reference_url') or m.get('best_reference_url',''),'supporting_matches':support,'raw':m})
        elif item.get('rank') is not None:
            out.append({'remix_key':rk,'image':image,'rank':int(item.get('rank') or 1),'set_number':item.get('set_number',''),'set_name':item.get('set_name',''),'artist':item.get('artist',''),'score':item.get('score',0),'confidence':item.get('confidence',''),'best_reference_file':item.get('best_reference_file',''),'best_reference_url':item.get('best_reference_url',''),'supporting_matches':[],'raw':item})
    return out

@router.post('/api/traits/import/reference-metadata')
async def import_reference_metadata(file:UploadFile=File(...)):
    c=conn()
    if not c:raise HTTPException(503,'DATABASE_URL not configured')
    raw=await file.read(); data=json.loads(raw.decode('utf-8')); items=data if isinstance(data,list) else data.get('references') or data.get('data') or []
    n=0
    for i,d in enumerate(items):
        if not isinstance(d,dict):continue
        x=normalize_ref(d);key=x['sha256'] or x['local_file'] or x['source_url'] or f'ref-{i}'
        c.execute('INSERT INTO vg_reference_images(ref_key,set_number,set_name,artist,local_file,source_url,width,height,animated,sha256,embedding_index,raw_json) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(ref_key) DO UPDATE SET set_number=EXCLUDED.set_number,set_name=EXCLUDED.set_name,artist=EXCLUDED.artist,local_file=EXCLUDED.local_file,source_url=EXCLUDED.source_url,raw_json=EXCLUDED.raw_json',(key,x['set_number'],x['set_name'],x['artist'],x['local_file'],x['source_url'],x['width'],x['height'],x['animated'],x['sha256'],x['embedding_index'],json.dumps(d)));n+=1
    c.commit();c.close();return {'imported':n}

@router.post('/api/traits/import/matches')
async def import_matches(file:UploadFile=File(...)):
    c=conn()
    if not c:raise HTTPException(503,'DATABASE_URL not configured')
    raw=await file.read();name=(file.filename or '').lower()
    if name.endswith('.csv'):
        rows=list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig')))); matches=normalize_matches(rows)
    else: matches=normalize_matches(json.loads(raw.decode('utf-8')))
    remixes=set()
    for m in matches:
        rk=m['remix_key'];remixes.add(rk)
        token_id=int(rk) if rk.isdigit() and 1<=int(rk)<=16000 else None
        c.execute('INSERT INTO vg_remixes(remix_key,token_id,image_name,raw_json) VALUES(%s,%s,%s,%s) ON CONFLICT(remix_key) DO UPDATE SET token_id=COALESCE(EXCLUDED.token_id,vg_remixes.token_id),image_name=EXCLUDED.image_name',(rk,token_id,m['image'],json.dumps({'image':m['image']})))
        c.execute('INSERT INTO vg_match_candidates(remix_key,rank,set_number,set_name,artist,score,confidence,best_reference_file,best_reference_url,supporting_matches,raw_json) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(remix_key,rank) DO UPDATE SET set_number=EXCLUDED.set_number,set_name=EXCLUDED.set_name,artist=EXCLUDED.artist,score=EXCLUDED.score,confidence=EXCLUDED.confidence,best_reference_file=EXCLUDED.best_reference_file,best_reference_url=EXCLUDED.best_reference_url,supporting_matches=EXCLUDED.supporting_matches,raw_json=EXCLUDED.raw_json',(rk,m['rank'],m['set_number'],m['set_name'],m['artist'],float(m['score'] or 0),m['confidence'],m['best_reference_file'],m['best_reference_url'],json.dumps(m['supporting_matches']),json.dumps(m['raw'])))
    c.commit();c.close();return {'remixes':len(remixes),'candidates':len(matches)}

@router.get('/api/traits/status')
def status():
    c=conn()
    if not c:return {'database_configured':False,'references':0,'remixes':0,'candidates':0,'reviewed':0}
    vals={}
    for table,key in [('vg_reference_images','references'),('vg_remixes','remixes'),('vg_match_candidates','candidates')]:vals[key]=int(c.execute(f'SELECT COUNT(*) n FROM {table}').fetchone()['n'])
    vals['reviewed']=int(c.execute("SELECT COUNT(*) n FROM vg_reviews WHERE status<>'unreviewed'").fetchone()['n']);c.close();return {'database_configured':True,**vals}

@router.get('/api/traits/remixes')
def remixes(page:int=1,page_size:int=50,review_status:str='all',q:str=''):
    c=conn()
    if not c: return {'items':[],'total':0}
    where=[];args=[]
    if q: where.append('(r.remix_key ILIKE %s OR r.image_name ILIKE %s)');args += [f'%{q}%',f'%{q}%']
    if review_status!='all': where.append("COALESCE(v.status,'unreviewed')=%s");args.append(review_status)
    ws=' WHERE '+' AND '.join(where) if where else ''
    total=int(c.execute('SELECT COUNT(*) n FROM vg_remixes r LEFT JOIN vg_reviews v USING(remix_key)'+ws,args).fetchone()['n'])
    rows=c.execute('SELECT r.remix_key,r.token_id,r.image_name,COALESCE(v.status,\'unreviewed\') status,v.updated_at FROM vg_remixes r LEFT JOIN vg_reviews v USING(remix_key)'+ws+' ORDER BY COALESCE(r.token_id,999999),r.remix_key LIMIT %s OFFSET %s',args+[min(page_size,100),max(0,(page-1)*page_size)]).fetchall();c.close();return {'items':rows,'total':total,'page':page,'page_size':page_size}

@router.get('/api/traits/remix/{rk}')
def remix_detail(rk:str):
    c=conn()
    if not c:raise HTTPException(503,'DATABASE_URL not configured')
    r=c.execute('SELECT * FROM vg_remixes WHERE remix_key=%s',(rk,)).fetchone()
    if not r:raise HTTPException(404,'Remix not found')
    cand=c.execute('SELECT * FROM vg_match_candidates WHERE remix_key=%s ORDER BY rank LIMIT 10',(rk,)).fetchall();rev=c.execute('SELECT * FROM vg_reviews WHERE remix_key=%s',(rk,)).fetchone();c.close();return {'remix':r,'candidates':cand,'review':rev}

class ReviewBody(BaseModel):
    status:str='reviewed';approved_sources:list=[];remixed_elements:dict={};visual_traits:dict={};notes:str=''
@router.put('/api/traits/remix/{rk}/review')
def save_review(rk:str,b:ReviewBody):
    c=conn()
    if not c:raise HTTPException(503,'DATABASE_URL not configured')
    rr=c.execute('SELECT token_id FROM vg_remixes WHERE remix_key=%s',(rk,)).fetchone(); token=rr['token_id'] if rr else None
    c.execute('INSERT INTO vg_reviews(remix_key,token_id,status,approved_sources,remixed_elements,visual_traits,notes,updated_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(remix_key) DO UPDATE SET status=EXCLUDED.status,approved_sources=EXCLUDED.approved_sources,remixed_elements=EXCLUDED.remixed_elements,visual_traits=EXCLUDED.visual_traits,notes=EXCLUDED.notes,updated_at=EXCLUDED.updated_at',(rk,token,b.status,json.dumps(b.approved_sources),json.dumps(b.remixed_elements),json.dumps(b.visual_traits),b.notes,nowiso()));c.execute('INSERT INTO vg_activity(created_at,remix_key,action,payload) VALUES(%s,%s,%s,%s)',(nowiso(),rk,'save_review',json.dumps(b.model_dump())));c.commit();c.close();return {'ok':True}

@router.get('/api/traits/remix/{rk}/metadata')
def trait_metadata(rk:str):
    c=conn()
    if not c:raise HTTPException(503,'DATABASE_URL not configured')
    rev=c.execute('SELECT * FROM vg_reviews WHERE remix_key=%s',(rk,)).fetchone();rm=c.execute('SELECT * FROM vg_remixes WHERE remix_key=%s',(rk,)).fetchone();c.close()
    if not rm:raise HTTPException(404,'Remix not found')
    attrs=[]
    if rev:
        sources=rev['approved_sources'] or []
        for i,s in enumerate(sources):
            prefix='' if len(sources)==1 else ['Primary ','Secondary ','Tertiary '][i] if i<3 else f'Source {i+1} '
            if s.get('set_name'):attrs.append({'trait_type':prefix+'Remix Set','value':s.get('set_name')})
            if s.get('set_number'):attrs.append({'trait_type':prefix+'Source Set Number','value':str(s.get('set_number'))})
            if s.get('artist'):attrs.append({'trait_type':prefix+'Original Set Artist','value':s.get('artist')})
            for el in (rev['remixed_elements'] or {}).get(str(s.get('set_number') or s.get('set_name')),[]):attrs.append({'trait_type':'Remixed Element','value':el})
        for k,v in (rev['visual_traits'] or {}).items():
            if v not in ('',None,[]):attrs.append({'trait_type':k,'value':v})
    tid=rm['token_id'] or rk
    return {'name':f'1 of 16 000 #{tid}','description':'A remix artwork mapped through the Opepen visual genome.','attributes':attrs}

@router.get('/api/traits/references')
def references(set_number:str='',q:str='',page:int=1,page_size:int=60):
    c=conn()
    if not c:return {'items':[],'total':0}
    where=[];args=[]
    if set_number:where.append('set_number=%s');args.append(set_number)
    if q:where.append('(set_name ILIKE %s OR artist ILIKE %s)');args += [f'%{q}%',f'%{q}%']
    ws=' WHERE '+' AND '.join(where) if where else ''
    total=int(c.execute('SELECT COUNT(*) n FROM vg_reference_images'+ws,args).fetchone()['n']);rows=c.execute('SELECT ref_key,set_number,set_name,artist,local_file,source_url,width,height,animated FROM vg_reference_images'+ws+' ORDER BY set_number,id LIMIT %s OFFSET %s',args+[min(page_size,100),max(0,(page-1)*page_size)]).fetchall();c.close();return {'items':rows,'total':total}

@router.get('/api/traits/stats')
def stats():
    c=conn()
    if not c:return {}
    total=int(c.execute('SELECT COUNT(*) n FROM vg_remixes').fetchone()['n']);reviewed=int(c.execute("SELECT COUNT(*) n FROM vg_reviews WHERE status<>'unreviewed'").fetchone()['n']);top=c.execute('SELECT set_name,artist,COUNT(*) n FROM vg_match_candidates WHERE rank=1 GROUP BY set_name,artist ORDER BY n DESC LIMIT 20').fetchall();statuses=c.execute('SELECT status,COUNT(*) n FROM vg_reviews GROUP BY status ORDER BY n DESC').fetchall();c.close();return {'total_remixes':total,'reviewed':reviewed,'unreviewed':max(0,total-reviewed),'top_matched_sets':top,'review_statuses':statuses}

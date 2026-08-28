import os, io, json, requests
from urllib.parse import urljoin, urlparse
from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel
from web3 import Web3
from .db import conn, nowiso, configured

router=APIRouter()
ETH_RPC=os.getenv('ETH_RPC_URL','https://ethereum-rpc.publicnode.com')
BASE_RPC=os.getenv('BASE_RPC_URL','https://mainnet.base.org')
MAIN=Web3.to_checksum_address(os.getenv('CONTRACT_ADDRESS','0xcef88f9ff3a204607c1f341435b6f3fb1cd3c382'))
GOLD=Web3.to_checksum_address(os.getenv('GOLD_CONTRACT_ADDRESS','0xc253cde2f48b43dc01508afe48fe3806258cfbba'))
FILEBASE_RPC_URL=os.getenv('FILEBASE_RPC_URL','https://rpc.filebase.io').rstrip('/')
FILEBASE_RPC_TOKEN=os.getenv('FILEBASE_RPC_TOKEN','')
ABI=[{'inputs':[],'name':'totalSupply','outputs':[{'type':'uint256'}],'stateMutability':'view','type':'function'},{'inputs':[],'name':'baseURI','outputs':[{'type':'string'}],'stateMutability':'view','type':'function'},{'inputs':[{'type':'uint256','name':'tokenId'}],'name':'tokenURI','outputs':[{'type':'string'}],'stateMutability':'view','type':'function'},{'inputs':[{'type':'uint256','name':'tokenId'}],'name':'ownerOf','outputs':[{'type':'address'}],'stateMutability':'view','type':'function'}]
ERC1155=[{'inputs':[{'type':'bytes4','name':'interfaceId'}],'name':'supportsInterface','outputs':[{'type':'bool'}],'stateMutability':'view','type':'function'},{'inputs':[{'type':'address','name':'account'},{'type':'uint256','name':'id'}],'name':'balanceOf','outputs':[{'type':'uint256'}],'stateMutability':'view','type':'function'}]
UA={'User-Agent':'1of16000-cloud/5.1','Accept':'*/*'}

def w3e():return Web3(Web3.HTTPProvider(ETH_RPC,request_kwargs={'timeout':12}))
def w3b():return Web3(Web3.HTTPProvider(BASE_RPC,request_kwargs={'timeout':12}))

def ipfs_urls(uri):
    if not uri:return []
    uri=str(uri).strip()
    if uri.startswith('data:'):return [uri]
    if uri.startswith('ipfs://'):
        t=uri[7:].lstrip('/')
        if t.startswith('ipfs/'):t=t[5:]
        return [
            f'https://dweb.link/ipfs/{t}',
            f'https://ipfs.io/ipfs/{t}',
            f'https://cloudflare-ipfs.com/ipfs/{t}',
            f'https://ipfs.filebase.io/ipfs/{t}',
        ]
    if uri.startswith('/ipfs/'):
        return ipfs_urls('ipfs://'+uri[6:])
    return [uri] if uri.startswith(('http://','https://')) else []

def fetch_json(uri):
    errors=[]
    for u in ipfs_urls(uri):
        if u.startswith('data:application/json'):
            try:
                import base64
                payload=u.split(',',1)[1]
                raw=base64.b64decode(payload) if ';base64,' in u else payload
                p=json.loads(raw)
                if isinstance(p,dict):return p,u
            except Exception as e:errors.append(str(e))
            continue
        try:
            r=requests.get(u,timeout=20,headers={**UA,'Accept':'application/json,*/*'})
            if r.ok:
                p=r.json()
                if isinstance(p,dict):return p,u
            else:errors.append(f'{u}: HTTP {r.status_code}')
        except Exception as e:errors.append(f'{u}: {e}')
    raise HTTPException(502,'Could not resolve metadata from IPFS gateways')

def normalize_image_uri(image, metadata_uri, resolved_metadata_url):
    image=str(image or '').strip()
    if not image:return ''
    if image.startswith(('ipfs://','http://','https://','data:','/ipfs/')):return image
    # Some metadata stores a filename relative to the metadata directory.
    if str(metadata_uri).startswith('ipfs://'):
        base=str(metadata_uri)[7:].lstrip('/')
        if '/' in base:
            parent=base.rsplit('/',1)[0]
            return f'ipfs://{parent}/{image.lstrip("./")}'
    if resolved_metadata_url and resolved_metadata_url.startswith(('http://','https://')):
        return urljoin(resolved_metadata_url,image)
    return image

def resolve_image(image_uri):
    candidates=ipfs_urls(image_uri)
    if not candidates:return '',[]
    if candidates[0].startswith('data:'):return candidates[0],candidates
    # Verify an image gateway server-side so the browser does not get a dead first URL.
    for u in candidates:
        try:
            r=requests.get(u,timeout=12,headers=UA,stream=True,allow_redirects=True)
            ctype=(r.headers.get('content-type') or '').lower()
            if r.ok and ('image/' in ctype or 'svg' in ctype or not ctype):
                r.close();return u,candidates
            r.close()
        except Exception:pass
    return candidates[0],candidates

@router.get('/api/health')
def health():
    e,b=w3e(),w3b();dbok=False
    if configured():
        try:c=conn();dbok=bool(c);c and c.close()
        except Exception:pass
    return {'version':'5.1.0','ethereum':e.is_connected(),'base':b.is_connected(),'database':{'configured':configured(),'ok':dbok},'filebase':{'configured':bool(FILEBASE_RPC_TOKEN)},'opepen_source':'https://opepen.art'}

@router.get('/api/contract/main')
def main_contract():
    w=w3e();out={'network':'Ethereum','address':MAIN,'connected':w.is_connected()}
    if w.is_connected():
        c=w.eth.contract(address=MAIN,abi=ABI)
        for k,fn in [('totalSupply',c.functions.totalSupply),('baseURI',c.functions.baseURI)]:
            try:out[k]=fn().call()
            except Exception:out[k]=None
    return out

@router.get('/api/contract/gold')
def gold_contract():
    w=w3b();erc=None
    if w.is_connected():
        try:erc=w.eth.contract(address=GOLD,abi=ERC1155).functions.supportsInterface(bytes.fromhex('d9b67a26')).call()
        except Exception:pass
    return {'network':'Base','chainId':8453,'address':GOLD,'connected':w.is_connected(),'erc1155':erc}

@router.get('/api/token/{tid}')
def token(tid:int):
    if tid<1 or tid>16000:raise HTTPException(400,'Token out of range')
    w=w3e()
    if not w.is_connected():raise HTTPException(503,'Ethereum RPC unavailable')
    try:
        c=w.eth.contract(address=MAIN,abi=ABI)
        uri=c.functions.tokenURI(tid).call()
        owner=c.functions.ownerOf(tid).call()
    except Exception as e:
        raise HTTPException(502,f'Could not read token {tid} from Ethereum: {e}')
    meta,res=fetch_json(uri)
    raw_image=meta.get('image') or meta.get('image_url') or meta.get('image_data') or ''
    image_uri=normalize_image_uri(raw_image,uri,res)
    preview,candidates=resolve_image(image_uri)
    return {
        'token_id':tid,'owner':owner,'metadata_uri':uri,'resolved_metadata_url':res,
        'metadata':meta,'image_uri':image_uri,'image_preview':preview,'image_candidates':candidates,
        'image_resolved':bool(preview),'contract':MAIN,
    }

class Draft(BaseModel):
    metadata:dict
    live_metadata_uri:str=''
    image_uri:str=''

@router.put('/api/drafts/{tid}')
def save_draft(tid:int,b:Draft):
    c=conn()
    if not c:raise HTTPException(503,'Persistent database is not connected')
    c.execute('INSERT INTO drafts(token_id,updated_at,metadata_json,live_metadata_uri,image_uri) VALUES(%s,%s,%s,%s,%s) ON CONFLICT(token_id) DO UPDATE SET updated_at=EXCLUDED.updated_at,metadata_json=EXCLUDED.metadata_json,live_metadata_uri=EXCLUDED.live_metadata_uri,image_uri=EXCLUDED.image_uri',(tid,nowiso(),json.dumps(b.metadata),b.live_metadata_uri,b.image_uri));c.commit();c.close();return {'ok':True}

@router.get('/api/drafts')
def drafts():
    c=conn()
    if not c:return []
    rows=c.execute('SELECT token_id,updated_at,metadata_json,live_metadata_uri,image_uri FROM drafts ORDER BY updated_at DESC').fetchall();c.close();return rows

@router.get('/api/cid/inspect')
def cid_inspect(cid:str,tokens:str='1,16000'):
    ids=[]
    for x in tokens.split(','):
        try:ids.append(int(x.strip()))
        except:pass
    rows=[]
    for tid in ids[:50]:
        try:m,u=fetch_json(f'ipfs://{cid.strip().strip("/")}/{tid}');raw=m.get('image') or m.get('image_url') or '';im=normalize_image_uri(raw,f'ipfs://{cid.strip().strip("/")}/{tid}',u);preview,_=resolve_image(im);iok=bool(preview)
        except Exception as e:rows.append({'token_id':tid,'metadata_ok':False,'image_ok':False,'error':str(e)});continue
        rows.append({'token_id':tid,'metadata_ok':True,'metadata_url':u,'image_ok':iok,'image_preview':preview,'name':m.get('name',''),'image':im,'attributes_count':len(m.get('attributes') or [])})
    return {'cid':cid,'tested':len(rows),'metadata_resolved':sum(bool(x.get('metadata_ok')) for x in rows),'images_resolved':sum(bool(x.get('image_ok')) for x in rows),'tokens':rows}

@router.post('/api/filebase/add')
async def filebase_add(file:UploadFile=File(...)):
    if not FILEBASE_RPC_TOKEN:raise HTTPException(503,'FILEBASE_RPC_TOKEN not configured in Vercel')
    data=await file.read();r=requests.post(f'{FILEBASE_RPC_URL}/api/v0/add',params=[('cid-version','1'),('pin','true')],headers={'Authorization':f'Bearer {FILEBASE_RPC_TOKEN}'},files={'file':(file.filename,io.BytesIO(data),file.content_type or 'application/octet-stream')},timeout=120);r.raise_for_status();p=r.json();return {'cid':p.get('Hash'),'uri':f"ipfs://{p.get('Hash')}"}

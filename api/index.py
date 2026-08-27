from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pathlib import Path
from web3 import Web3
import os, requests

# Deliberately top-level for Vercel FastAPI discovery.
app = FastAPI(title="1 OF 16000 — Pierre Remixes", version="2.9.1")

ETH_RPC = os.getenv("ETH_RPC_URL", "https://ethereum-rpc.publicnode.com")
BASE_RPC = os.getenv("BASE_RPC_URL", "https://mainnet.base.org")
MAIN = Web3.to_checksum_address("0xcef88f9ff3a204607c1f341435b6f3fb1cd3c382")
GOLD = Web3.to_checksum_address("0xc253cde2f48b43dc01508afe48fe3806258cfbba")
ABI = [
 {"inputs":[],"name":"totalSupply","outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},
 {"inputs":[],"name":"baseURI","outputs":[{"type":"string"}],"stateMutability":"view","type":"function"},
 {"inputs":[{"type":"uint256","name":"tokenId"}],"name":"tokenURI","outputs":[{"type":"string"}],"stateMutability":"view","type":"function"},
 {"inputs":[{"type":"uint256","name":"tokenId"}],"name":"ownerOf","outputs":[{"type":"address"}],"stateMutability":"view","type":"function"}
]

def ipfs_urls(uri):
    if not uri: return []
    if uri.startswith("ipfs://"):
        t=uri[7:].lstrip("/")
        return [f"https://ipfs.filebase.io/ipfs/{t}",f"https://dweb.link/ipfs/{t}",f"https://ipfs.io/ipfs/{t}"]
    return [uri] if uri.startswith(("http://","https://")) else []

def fetch_json(uri):
    for url in ipfs_urls(uri):
        try:
            r=requests.get(url,timeout=15,headers={"User-Agent":"1of16000/2.9.1"})
            if r.ok and isinstance(r.json(),dict): return r.json(),url
        except Exception: pass
    raise HTTPException(502,"Could not resolve metadata")

@app.get("/", response_class=HTMLResponse)
@app.get("/app", response_class=HTMLResponse)
def home():
    return HTMLResponse((Path(__file__).resolve().parent.parent/"public"/"index.html").read_text(encoding="utf-8"))

@app.get("/api/health")
def health():
    eth=Web3(Web3.HTTPProvider(ETH_RPC,request_kwargs={"timeout":7}))
    base=Web3(Web3.HTTPProvider(BASE_RPC,request_kwargs={"timeout":7}))
    return {"version":"2.9.1","ethereum":eth.is_connected(),"base":base.is_connected(),"database":{"configured":bool(os.getenv("DATABASE_URL"))},"filebase":{"configured":bool(os.getenv("FILEBASE_RPC_TOKEN"))}}

@app.get("/api/contract/main")
def main_contract():
    w=Web3(Web3.HTTPProvider(ETH_RPC,request_kwargs={"timeout":10}))
    out={"network":"Ethereum","address":MAIN,"connected":w.is_connected()}
    if w.is_connected():
        c=w.eth.contract(address=MAIN,abi=ABI)
        try: out["totalSupply"]=int(c.functions.totalSupply().call())
        except Exception: out["totalSupply"]=None
        try: out["baseURI"]=c.functions.baseURI().call()
        except Exception: out["baseURI"]=None
    return out

@app.get("/api/contract/gold")
def gold_contract():
    return {"network":"Base","chainId":8453,"address":GOLD,"type":"ERC-1155"}

@app.get("/api/token/{token_id}")
def token(token_id:int):
    if token_id<1 or token_id>16000: raise HTTPException(400,"Token out of range")
    w=Web3(Web3.HTTPProvider(ETH_RPC,request_kwargs={"timeout":10}))
    if not w.is_connected(): raise HTTPException(503,"Ethereum RPC unavailable")
    c=w.eth.contract(address=MAIN,abi=ABI)
    uri=c.functions.tokenURI(token_id).call(); owner=c.functions.ownerOf(token_id).call()
    meta,resolved=fetch_json(uri); image=str(meta.get("image",""))
    return {"token_id":token_id,"owner":owner,"metadata_uri":uri,"resolved_metadata_url":resolved,"metadata":meta,"image_uri":image,"image_preview":(ipfs_urls(image) or [""])[0]}

@app.get("/api/status")
def status():
    return {"pending":0,"baseline":0,"burned":0,"last_scan":None,"events":[],"database_configured":bool(os.getenv("DATABASE_URL"))}

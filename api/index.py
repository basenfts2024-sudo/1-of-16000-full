from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pathlib import Path
app=FastAPI(title='1 OF 16000 — Pierre Remixes',version='3.1.0')
from api.core import router as core_router
from api.deflation import router as deflation_router
from api.traits import router as traits_router
app.include_router(core_router)
app.include_router(deflation_router)
app.include_router(traits_router)
@app.get('/',response_class=HTMLResponse)
@app.get('/app',response_class=HTMLResponse)
def home():
    html=(Path(__file__).resolve().parent.parent/'public'/'index.html').read_text(encoding='utf-8')
    patch='''<script>(function(){function patch(){const a=document.getElementById("akey");if(a){const box=a.parentElement;box.style.display="none";}const t=document.getElementById("traits");if(t){t.innerHTML='<iframe src="/traits.html" style="width:100%;height:calc(100vh - 80px);border:0;border-radius:12px;background:#111"></iframe>';}}if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',patch);else patch();})();</script>'''
    return HTMLResponse(html.replace('</body>',patch+'</body>'))

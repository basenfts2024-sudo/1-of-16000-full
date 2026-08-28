from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pathlib import Path

app = FastAPI(title='1 OF 16000 — Pierre Remixes', version='4.1.0')

from api.core import router as core_router
from api.deflation import router as deflation_router
from api.traits import router as traits_router
from api.opepen_source import router as opepen_source_router

app.include_router(core_router)
app.include_router(deflation_router)
app.include_router(traits_router)
app.include_router(opepen_source_router)

@app.get('/', response_class=HTMLResponse)
@app.get('/app', response_class=HTMLResponse)
def home():
    return HTMLResponse((Path(__file__).resolve().parent.parent/'public'/'index.html').read_text(encoding='utf-8'))

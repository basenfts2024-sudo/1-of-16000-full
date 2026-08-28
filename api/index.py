from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

app = FastAPI(title='1 OF 16000 — Pierre Remixes', version='4.2.0')
BOOT_ERRORS = {}


def mount(name, module_path):
    try:
        module = __import__(module_path, fromlist=['router'])
        app.include_router(module.router)
    except Exception as exc:
        BOOT_ERRORS[name] = f'{type(exc).__name__}: {exc}'


# Keep the application alive even if one optional subsystem fails to import.
mount('opepen_source', 'api.opepen_source')
mount('core', 'api.core')
mount('deflation', 'api.deflation')
mount('traits', 'api.traits')


@app.get('/api/boot')
def boot():
    return {
        'ok': True,
        'version': '4.2.0',
        'boot_errors': BOOT_ERRORS,
        'mounted': {
            'opepen_source': 'opepen_source' not in BOOT_ERRORS,
            'core': 'core' not in BOOT_ERRORS,
            'deflation': 'deflation' not in BOOT_ERRORS,
            'traits': 'traits' not in BOOT_ERRORS,
        },
    }


@app.get('/', response_class=HTMLResponse)
@app.get('/app', response_class=HTMLResponse)
def home():
    path = Path(__file__).resolve().parent.parent / 'public' / 'index.html'
    try:
        return HTMLResponse(path.read_text(encoding='utf-8'))
    except Exception as exc:
        return HTMLResponse(
            '<!doctype html><html><body style="font-family:Arial;padding:40px">'
            '<h1>1 OF 16000</h1><p>The API is running but the dashboard asset could not be loaded.</p>'
            f'<pre>{type(exc).__name__}: {exc}</pre>'
            '<p>Check <a href="/api/boot">/api/boot</a> for backend status.</p>'
            '</body></html>',
            status_code=200,
        )


@app.exception_handler(Exception)
async def unhandled(request, exc):
    return JSONResponse(
        status_code=500,
        content={
            'detail': 'Server error',
            'type': type(exc).__name__,
            'message': str(exc),
            'path': str(request.url.path),
        },
    )

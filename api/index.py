import re
import requests
from fastapi import FastAPI, HTTPException

app = FastAPI(title='1 OF 16000 — Pierre Remixes', version='5.1.0')
BASE = 'https://opepen.art'
HEADERS = {
    'User-Agent': '1of16000-opepen-monitor/5.1',
    'Accept': 'text/html,application/xhtml+xml',
}
BOOT_ERRORS = {}


def mount(name, module_path):
    try:
        module = __import__(module_path, fromlist=['router'])
        app.include_router(module.router)
    except Exception as exc:
        BOOT_ERRORS[name] = f'{type(exc).__name__}: {exc}'


# These are the real working application APIs. Keep each isolated so one
# optional subsystem cannot prevent the others from starting.
mount('core', 'api.core')
mount('deflation', 'api.deflation')
mount('traits', 'api.traits')


def fetch_page(path: str) -> str:
    r = requests.get(BASE + path, headers=HEADERS, timeout=20)
    r.raise_for_status()
    return r.text


def submission_ids(html: str):
    return list(dict.fromkeys(re.findall(r'/submissions/([0-9a-fA-F-]{36})', html)))


@app.get('/api/boot')
def boot():
    return {
        'ok': True,
        'version': '5.1.0',
        'architecture': 'static-first + isolated APIs',
        'mounted': {
            'core': 'core' not in BOOT_ERRORS,
            'deflation': 'deflation' not in BOOT_ERRORS,
            'traits': 'traits' not in BOOT_ERRORS,
        },
        'boot_errors': BOOT_ERRORS,
        'activity_source': BASE,
    }


# If core loaded it owns /api/health. This fallback exists only when core could
# not import, so the site can still report a useful diagnostic.
if 'core' in BOOT_ERRORS:
    @app.get('/api/health')
    def health_fallback():
        return {
            'ok': False,
            'version': '5.1.0',
            'opepen_source': BASE,
            'boot_errors': BOOT_ERRORS,
        }


@app.get('/api/opepen/source')
def opepen_source():
    try:
        submissions_html = fetch_page('/submissions?search=&sort=latest')
        contribute_html = fetch_page('/contribute')
    except Exception as exc:
        raise HTTPException(502, f'opepen.art is not reachable: {type(exc).__name__}: {exc}')
    latest = submission_ids(submissions_html)
    open_sets = submission_ids(contribute_html)
    return {
        'ok': True,
        'source': BASE,
        'submissions_page': BASE + '/submissions?search=&sort=latest',
        'contributions_page': BASE + '/contribute',
        'latest_submission_links_visible': len(latest),
        'open_contribution_sets_visible': len(open_sets),
        'latest_submission_ids': latest[:100],
        'open_contribution_set_ids': open_sets[:100],
        'database_required': False,
    }

import re
import requests
from fastapi import FastAPI, HTTPException

app = FastAPI(title='1 OF 16000 — Pierre Remixes', version='5.0.0')
BASE = 'https://opepen.art'
HEADERS = {
    'User-Agent': '1of16000-opepen-monitor/5.0',
    'Accept': 'text/html,application/xhtml+xml',
}


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
        'version': '5.0.0',
        'architecture': 'static-first',
        'builder': 'static-independent',
        'visual_genome': 'local-first-indexeddb',
        'activity_source': 'https://opepen.art',
        'note': 'Heavy database, Web3 and publishing services are isolated from this health endpoint.'
    }


@app.get('/api/health')
def health():
    return {
        'ok': True,
        'version': '5.0.0',
        'opepen_source': 'https://opepen.art',
        'static_apps': {
            'builder': '/builder.html',
            'traits': '/traits.html',
        }
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
        'latest_submission_ids': latest[:50],
        'open_contribution_set_ids': open_sets[:50],
        'database_required': False,
    }

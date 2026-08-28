import re
import requests
from fastapi import APIRouter, HTTPException

router = APIRouter()
BASE = "https://opepen.art"
HEADERS = {"User-Agent": "1of16000-opepen-monitor/4.1", "Accept": "text/html,application/xhtml+xml"}


def _page(path: str) -> str:
    r = requests.get(BASE + path, headers=HEADERS, timeout=20)
    r.raise_for_status()
    return r.text


def _submission_links(html: str):
    # opepen.art submission detail URLs use UUIDs. Keep unique links in page order.
    ids = re.findall(r'/submissions/([0-9a-fA-F-]{36})', html)
    return list(dict.fromkeys(ids))


@router.get('/api/opepen/source')
def source_probe():
    """Public, database-free health check against the real opepen.art pages.

    This intentionally does not invent an api.opepen.art endpoint. It verifies the
    two public surfaces the deflation monitor cares about: latest submissions and
    sets currently open for contribution.
    """
    try:
        submissions_html = _page('/submissions?search=&sort=latest')
        contribute_html = _page('/contribute')
    except Exception as e:
        raise HTTPException(502, f'opepen.art is not reachable: {e}')

    latest = _submission_links(submissions_html)
    open_sets = _submission_links(contribute_html)
    return {
        'ok': True,
        'source': 'https://opepen.art',
        'submissions_page': 'https://opepen.art/submissions?search=&sort=latest',
        'contributions_page': 'https://opepen.art/contribute',
        'latest_submission_links_visible': len(latest),
        'open_contribution_sets_visible': len(open_sets),
        'latest_submission_ids': latest[:50],
        'open_contribution_set_ids': open_sets[:50],
        'database_required': False,
        'note': 'This is a live source probe. Persistent burn accounting still requires deduplication storage before any burn debt is created.'
    }

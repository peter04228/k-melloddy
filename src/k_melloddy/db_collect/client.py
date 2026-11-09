"""NCBI transport. Network is used only by explicit CLI search/run operations."""
import email.utils
import http.client
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Protocol


class Client(Protocol):
    def search(self, query: str, start: int, size: int, sort: str) -> bytes: ...
    def fetch(self, pmids: list[str]) -> bytes: ...


class NCBIClient:
    def __init__(self, email='', tool='k_melloddy', timeout=30, retries=4, on_retry=None):
        self.email, self.tool = email, tool
        self.timeout, self.retries = timeout, retries
        self.on_retry = on_retry or (lambda *args: None)
        self.last = 0.0
        self.api_key = os.environ.get('NCBI_API_KEY', '')

    def request(self, endpoint, params):
        params = dict(params, db='pubmed', tool=self.tool, email=self.email)
        if self.api_key:
            params['api_key'] = self.api_key
        for attempt in range(self.retries + 1):
            time.sleep(max(0, (0.11 if self.api_key else 0.35) - (time.monotonic() - self.last)))
            self.last = time.monotonic()
            request = urllib.request.Request('https://eutils.ncbi.nlm.nih.gov/entrez/eutils/' + endpoint,
                data=urllib.parse.urlencode(params).encode(), headers={'User-Agent': self.tool})
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    return response.read()
            except (urllib.error.URLError, TimeoutError, OSError, http.client.IncompleteRead,
                    http.client.RemoteDisconnected) as exc:
                status = getattr(exc, 'code', None)
                if status is not None and status not in {429, 500, 502, 503, 504}:
                    raise RuntimeError(f'NCBI HTTP {status}') from None
                if attempt == self.retries:
                    raise RuntimeError('NCBI request failed after retries (credentials omitted)') from None
                delay = 2 ** attempt
                retry_after = getattr(exc, 'headers', {}).get('Retry-After') if getattr(exc, 'headers', None) else None
                if retry_after:
                    try:
                        delay = max(delay, float(retry_after))
                    except ValueError:
                        delay = max(delay, (email.utils.parsedate_to_datetime(retry_after) - datetime.now(timezone.utc)).total_seconds())
                self.on_retry(attempt + 1, status, delay)
                # Sleep in small pieces so Ctrl+C stays responsive.
                end = time.monotonic() + delay
                while time.monotonic() < end:
                    time.sleep(min(1, end - time.monotonic()))
        raise RuntimeError('Unreachable')

    def search(self, query, start=0, size=0, sort='pub_date'):
        return self.request('esearch.fcgi', dict(term=query, retstart=start, retmax=size, sort=sort, retmode='json'))

    def fetch(self, pmids):
        return self.request('efetch.fcgi', dict(id=','.join(pmids), retmode='xml'))


def parse_search(data):
    obj = json.loads(data)
    r = obj.get('esearchresult')
    if not r or 'error' in obj or 'ERROR' in r or r.get('errorlist'):
        raise ValueError('Invalid ESearch response or query error')
    count = int(r['count'])
    if count < 0 or not isinstance(r.get('idlist', []), list):
        raise ValueError('Invalid ESearch count/IDs')
    ids = r.get('idlist', [])
    if any(not isinstance(p, str) or not p.isdecimal() or int(p) <= 0 for p in ids):
        raise ValueError('Invalid PMID in ESearch')
    return dict(count=count, ids=ids, translation=r.get('querytranslation'), warnings=r.get('warninglist', {}))

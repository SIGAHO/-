"""Untrusted external evidence, bounded volatile cache, no State/Memory writes.

Backends are trusted Python plugins; their returned data is always validated.
The built-in transport only contacts fixed Wikipedia HTTPS endpoints, never result URLs.
"""
from abc import ABC, abstractmethod
from collections import OrderedDict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
import math
import os
import re
import time
import unicodedata
from urllib.parse import quote, urlencode, urlsplit, urlunsplit
from urllib.request import Request, HTTPRedirectHandler, ProxyHandler, build_opener

from .knowledge import normalize, subject_in


def safe_text(value, limit):
    if not isinstance(value, str) or '\ufffd' in value:
        raise ValueError('invalid text encoding')
    value.encode('utf-8', errors='strict')
    if any(unicodedata.category(c) in {'Cc', 'Cf', 'Cs'} and c not in '\n\t' for c in value):
        raise ValueError('control characters')
    # Plain text only. Do not turn scripts, role delimiters or HTML into evidence.
    if re.search(r'<[^>]*>|ignore\s+(?:all\s+)?(?:previous|prior)\s+instructions|system\s*:|指示を無視', value, re.I):
        raise ValueError('instruction or markup in evidence')
    return ' '.join(value.split())[:limit]


def public_url(value):
    if not isinstance(value, str) or len(value) > 2048 or re.search(r'[\s\\\x00-\x1f<>"`]', value):
        raise ValueError('invalid URL')
    p = urlsplit(value)
    host = p.hostname
    if p.scheme != 'https' or not host or p.username or p.password or p.port not in (None, 443):
        raise ValueError('HTTPS public URL required')
    host = host.encode('idna').decode('ascii').lower()
    if not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?', host) or '.' not in host or host.endswith(('.local', '.internal', '.localhost')):
        raise ValueError('invalid public host')
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise ValueError('private address')
    return urlunsplit(('https', host, p.path or '/', p.query, ''))


@dataclass(frozen=True)
class ExternalEvidence:
    query: str
    title: str
    url: str
    source: str
    retrieved_at: float
    published_at: str | None
    snippet: str
    score: float
    content_hash: str

    @classmethod
    def create(cls, query, title, url, snippet, *, now=None, published_at=None, score=.5):
        query, title, snippet = safe_text(query, 512), safe_text(title, 160), safe_text(snippet, 1000)
        url = public_url(url)
        if not query or not title or len(snippet) < 20 or not math.isfinite(score) or not 0 <= score <= 1:
            raise ValueError('insufficient evidence')
        now = time.time() if now is None else now
        if not math.isfinite(now):
            raise ValueError('invalid timestamp')
        if published_at is not None:
            datetime.fromisoformat(published_at.replace('Z', '+00:00'))
        digest = hashlib.sha256((title+'\n'+snippet).encode()).hexdigest()
        return cls(query, title, url, urlsplit(url).hostname, now, published_at, snippet, score, digest)

    def metadata(self):
        # Durable provenance holds identity and digest, never downloaded text.
        return {k: v for k, v in asdict(self).items() if k != 'snippet'}


@dataclass(frozen=True)
class RetrievalResult:
    status: str
    evidence: tuple[ExternalEvidence, ...] = ()
    cached: bool = False


class ExternalRetriever(ABC):
    @abstractmethod
    def search(self, query: str) -> RetrievalResult:
        """Return evidence or explicit unavailable; never invent an answer."""


WebRetriever = ExternalRetriever


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('redirect refused')


class WikipediaRetriever(ExternalRetriever):
    """Keyless Japanese + English encyclopedia search, not the whole Web.

    Total wall budget is shared by both languages. Reads are byte bounded.
    Page modification time is deliberately not represented as publication time.
    """
    def __init__(self, timeout=8, opener=None, clock=time.time):
        if not math.isfinite(timeout) or timeout <= 0 or timeout > 30:
            raise ValueError('timeout must be in (0, 30]')
        self.timeout = timeout
        self.opener = opener or build_opener(ProxyHandler({}), NoRedirect())
        self.clock = clock

    def search(self, query):
        deadline = time.monotonic() + self.timeout
        found = []
        try:
            query = safe_text(query, 512)
            if not query:
                return RetrievalResult('zero_results')
            for language in ('ja', 'en'):
                params = urlencode(dict(action='query', generator='search', gsrsearch=query, gsrlimit=4,
                                        prop='extracts', exintro=1, explaintext=1, exchars=1000,
                                        format='json', formatversion=2))
                endpoint = f'https://{language}.wikipedia.org/w/api.php?{params}'
                request = Request(endpoint, headers={'User-Agent': 'Breaktail/2.0 (https://github.com/SIGAHO/-)', 'Accept': 'application/json'})
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError()
                with self.opener.open(request, timeout=remaining) as response:
                    if response.status != 200 or response.headers.get_content_type() != 'application/json':
                        raise ValueError('unexpected HTTP response')
                    chunks, count = [], 0
                    while True:
                        if time.monotonic() >= deadline:
                            raise TimeoutError()
                        chunk = response.read1(16384)
                        if not chunk:
                            break
                        count += len(chunk)
                        if count > 128000:
                            raise ValueError('oversized response')
                        chunks.append(chunk)
                data = json.loads(b''.join(chunks).decode('utf-8', errors='strict'))
                if not isinstance(data, dict) or 'error' in data:
                    raise ValueError('invalid API response')
                pages = data.get('query', {}).get('pages', [])
                if not isinstance(pages, list):
                    raise ValueError('invalid pages')
                for page in pages[:4]:
                    if not isinstance(page, dict):
                        raise ValueError('invalid page')
                    if not page.get('extract'):
                        continue
                    title = page['title']
                    try:
                        found.append(ExternalEvidence.create(query, title,
                            f'https://{language}.wikipedia.org/wiki/'+quote(title.replace(' ', '_'), safe=''),
                            page['extract'], now=self.clock(), score=1/(1+max(1, page.get('index', 1)))))
                    except (ValueError, UnicodeError):
                        continue
            return RetrievalResult('ok', tuple(found)) if found else RetrievalResult('zero_results')
        except TimeoutError:
            return RetrievalResult('timeout')
        except (OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError):
            return RetrievalResult('unavailable')


class RetrievalEngine:
    def __init__(self, backend=None, *, enabled=False, offline=False, ttl=300, clock=time.time):
        if not math.isfinite(ttl) or not 0 < ttl <= 3600:
            raise ValueError('TTL must be in (0, 3600]')
        self.backend = backend if backend is not None else WikipediaRetriever()
        self.enabled, self.offline, self.ttl, self.clock = enabled, offline, ttl, clock
        self.cache = OrderedDict()

    @classmethod
    def from_environment(cls):
        return cls(enabled=os.environ.get('BREAKTAIL_WEB', '0') == '1',
                   offline=os.environ.get('BREAKTAIL_OFFLINE', '0') == '1')

    def retrieve(self, context):
        # Defence in depth: callers cannot bypass CPU route/gate with query text.
        if context.get('intent') != 'external_knowledge' or not context['knowledge']['external_required']:
            return RetrievalResult('bypass')
        if self.offline:
            self.cache.clear()
            return RetrievalResult('offline')
        if not self.enabled:
            self.cache.clear()
            return RetrievalResult('disabled')
        subjects = context['knowledge']['subjects']
        query = context['user_input']
        if subjects:
            query = ' '.join(subjects)  # CPU entities only; never model-generated queries.
        try:
            query = safe_text(query, 512)
            now = self.clock()
            for key, (ts, _) in list(self.cache.items()):
                if not 0 <= now - ts < self.ttl:
                    del self.cache[key]
            key = (normalize(query), tuple(subjects))
            if key in self.cache:
                return RetrievalResult('ok', self.cache[key][1], True)
            result = self.backend.search(query)
            now = self.clock()
            if result.status != 'ok':
                return RetrievalResult(result.status)
            selected, urls, hashes = [], set(), set()
            for item in sorted(result.evidence[:32], key=lambda e: e.score, reverse=True):
                checked = ExternalEvidence.create(query, item.title, item.url, item.snippet,
                    now=item.retrieved_at, published_at=item.published_at, score=item.score)
                if checked.content_hash != item.content_hash or checked.source != item.source or not 0 <= now-item.retrieved_at < self.ttl:
                    continue
                # Relevance for every named subject: fail closed on partial entity coverage.
                if subjects and not any(subject_in(s, item.title+' '+item.snippet) for s in subjects):
                    continue
                if checked.url in urls or item.content_hash in hashes:
                    continue
                selected.append(checked)
                urls.add(checked.url)
                hashes.add(item.content_hash)
                if len(selected) == 4:
                    break
            if not selected or not all(any(subject_in(s, e.title+' '+e.snippet) for e in selected) for s in subjects):
                return RetrievalResult('insufficient_evidence')
            # Unnamed questions require trusted local evidence until relevance can be established.
            if not subjects:
                return RetrievalResult('insufficient_evidence')
            self.cache[key] = (min(e.retrieved_at for e in selected), tuple(selected))
            while len(self.cache) > 32:
                self.cache.popitem(last=False)
            return RetrievalResult('ok', tuple(selected))
        except (OSError, ValueError, TypeError, AttributeError, OverflowError):
            return RetrievalResult('unavailable')

    @staticmethod
    def attach(context, result):
        context['external_retrieval'] = {'status': result.status, 'cached': result.cached}
        context['external_evidence'] = [asdict(e) for e in result.evidence]

    @staticmethod
    def citations(context):
        lines = []
        for e in context.get('external_evidence', []):
            date = datetime.fromtimestamp(e['retrieved_at'], timezone.utc).isoformat(timespec='seconds')
            lines.append(f"{e['title']} — {e['url']}（取得 {date}、公開日 {e['published_at'] or '不明'}）")
        return '\n出典（取得資料・未検証）:\n' + '\n'.join(lines) if lines else ''

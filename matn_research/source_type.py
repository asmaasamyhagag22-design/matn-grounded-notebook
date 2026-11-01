"""Transparent source-type label from domain and saved page metadata.

Labels feed display, the shortlist prior and promotion checks; they never prove
source authority or change claim verification.

Rule (first match wins), recorded as RULE:
1. academic: scholarly page metadata (citation_* / DC DOI meta, JSON-LD ScholarlyArticle),
   an .edu/.ac host, or a listed scholarly publisher host;
2. government: a government host (.gov, .gov.xx, .gob.xx, .gouv.xx, .go.xx, .mil, .gc.ca, .govt.nz)
   or JSON-LD GovernmentOrganization;
3. international organization: an .int host or a listed intergovernmental body host;
4. encyclopedia: a listed reference-work host or a *.wiki host;
5. news: a listed news host;
6. commercial-vendor: a same-publisher JSON-LD Organization declaring a sales contact;
7. news: JSON-LD NewsArticle or a host containing "news";
8. commercial-vendor: a commercial TLD (.com .io .ai .co .net .biz .app .tech .software
   .cloud .solutions .tools .dev .so) not matched above;
9. other. LocalBusiness alone, a blog path or a country TLD does not establish a vendor.
The publisher shown with the label is og:site_name when present, else the host.
"""
import json
import re
from urllib.parse import urlsplit

RULE = ('source-type-v2: academic > government > international organization > encyclopedia > listed news '
        '> same-publisher sales > news > commercial TLD > other')
LABELS = ('government', 'academic', 'international organization', 'news', 'encyclopedia', 'commercial-vendor', 'other')

ACADEMIC_HOSTS = ('arxiv.org', 'doi.org', 'mdpi.com', 'springer.com', 'sciencedirect.com', 'tandfonline.com',
    'wiley.com', 'sagepub.com', 'frontiersin.org', 'plos.org', 'nature.com', 'jstor.org', 'ieee.org', 'acm.org',
    'researchgate.net', 'semanticscholar.org', 'emerald.com', 'ssrn.com', 'scielo.org', 'cambridge.org',
    'oup.com', 'elsevier.com', 'hindawi.com', 'igi-global.com', 'ncbi.nlm.nih.gov', 'europepmc.org',
    'academia.edu', 'scholar.archive.org')
INTERNATIONAL_HOSTS = ('un.org', 'worldbank.org', 'oecd.org', 'imf.org', 'undp.org', 'unesco.org', 'unicef.org',
    'wto.org', 'ilo.org', 'weforum.org', 'europa.eu', 'adb.org', 'afdb.org', 'isdb.org', 'opengovpartnership.org',
    'unescwa.org', 'uneca.org', 'unescap.org', 'oecd-ilibrary.org', 'unctad.org')
ENCYCLOPEDIA_HOSTS = ('wikipedia.org', 'britannica.com', 'encyclopedia.com', 'scholarpedia.org', 'investopedia.com')
NEWS_HOSTS = ('reuters.com', 'apnews.com', 'bbc.com', 'bbc.co.uk', 'nytimes.com', 'theguardian.com',
    'washingtonpost.com', 'cnn.com', 'bloomberg.com', 'ft.com', 'wsj.com', 'economist.com', 'aljazeera.com',
    'ahram.org.eg', 'egypttoday.com', 'dailynewsegypt.com', 'egyptindependent.com', 'thenationalnews.com',
    'arabnews.com', 'zawya.com', 'govtech.com', 'route-fifty.com', 'fedscoop.com', 'nextgov.com',
    'govinsider.asia', 'devex.com', 'forbes.com', 'techcrunch.com', 'theverge.com', 'wired.com', 'zdnet.com',
    'computerweekly.com', 'statescoop.com', 'apolitical.co')
GOVERNMENT = re.compile(r'(?:^|\.)(?:gov|mil)(?:\.[a-z]{2})?$|\.(?:gob|gouv|go|govt|gv)\.[a-z]{2}$|(?:^|\.)gc\.ca$')
ACADEMIC_HOST = re.compile(r'(?:^|\.)edu(?:\.[a-z]{2})?$|\.ac\.[a-z]{2}$')
COMMERCIAL_TLD = re.compile(r'\.(?:com|io|ai|co|net|biz|app|tech|software|cloud|solutions|tools|dev|so)$')


def _host(url):
    host = (urlsplit(url).hostname or '').lower()
    return host[4:] if host.startswith('www.') else host


def _listed(host, hosts):
    return any(host == h or host.endswith('.' + h) for h in hosts)


def page_metadata(raw):
    """Meta names/properties and JSON-LD @types from an HTML snapshot (bytes or str)."""
    if isinstance(raw, bytes):
        raw = raw.decode('utf-8', 'replace')
    meta = {}
    for tag in re.findall(r'<meta\b[^>]*>', raw[:400000], re.I):
        key = re.search(r'\b(?:name|property)\s*=\s*["\']([^"\']+)["\']', tag, re.I)
        value = re.search(r'\bcontent\s*=\s*["\']([^"\']*)["\']', tag, re.I)
        if key and value:
            meta.setdefault(key.group(1).strip().lower(), value.group(1).strip())
    types = set(); sales_publishers = set()
    for block in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', raw[:800000], re.I | re.S):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        stack = [data]
        while stack:
            item = stack.pop()
            if isinstance(item, list):
                stack.extend(item)
            elif isinstance(item, dict):
                kind = item.get('@type')
                types.update(kind if isinstance(kind, list) else [kind] if isinstance(kind, str) else [])
                # A publisher's explicit sales contact is useful on .org and country
                # TLDs too. Do not infer commerce from Organization/LocalBusiness
                # alone: public institutions can inherit those site-template types.
                kinds = kind if isinstance(kind, list) else [kind]
                if 'Organization' in kinds and isinstance(item.get('url'), str):
                    contacts = item.get('contactPoint', [])
                    contacts = contacts if isinstance(contacts, list) else [contacts]
                    if any(isinstance(c, dict) and str(c.get('contactType', '')).strip().lower() == 'sales'
                           for c in contacts):
                        sales_publishers.add(item['url'])
                stack.extend(v for k, v in item.items() if k == '@graph')
    return dict(meta=meta, types=sorted(types), sales_publishers=sorted(sales_publishers))


def classify(url, metadata=None):
    """Return dict(label, publisher, host, evidence) for one source."""
    host = _host(url); metadata = metadata or dict(meta={}, types=[])
    meta = metadata.get('meta', {}); types = set(metadata.get('types', []))
    publisher = meta.get('og:site_name') or host
    scholarly = [k for k in meta if k.startswith('citation_')] or ([k for k in meta if k in ('dc.identifier', 'prism.doi')
                 and '10.' in meta[k]])
    sales_hosts = [_host(u) for u in metadata.get('sales_publishers', [])]
    same_publisher_sales = any(h and (host == h or host.endswith('.' + h)) for h in sales_hosts)
    if scholarly or 'ScholarlyArticle' in types or ACADEMIC_HOST.search(host) or _listed(host, ACADEMIC_HOSTS):
        label, why = 'academic', 'scholarly metadata' if scholarly or 'ScholarlyArticle' in types else 'academic host'
    elif GOVERNMENT.search(host) or 'GovernmentOrganization' in types:
        label, why = 'government', 'government host' if GOVERNMENT.search(host) else 'GovernmentOrganization metadata'
    elif host.endswith('.int') or _listed(host, INTERNATIONAL_HOSTS):
        label, why = 'international organization', 'intergovernmental host'
    elif _listed(host, ENCYCLOPEDIA_HOSTS) or host.endswith('.wiki'):
        label, why = 'encyclopedia', 'reference-work host'
    elif _listed(host, NEWS_HOSTS):
        label, why = 'news', 'news host'
    elif same_publisher_sales:
        label, why = 'commercial-vendor', 'same-publisher sales contact metadata'
    elif 'NewsArticle' in types or 'news' in host:
        label, why = 'news', 'NewsArticle metadata' if 'NewsArticle' in types else 'news host'
    elif COMMERCIAL_TLD.search(host):
        label, why = 'commercial-vendor', 'commercial domain'
    else:
        label, why = 'other', 'no rule matched'
    return dict(label=label, publisher=publisher, host=host, evidence=why, rule=RULE)


def text(info):
    who = info['publisher'] if info['publisher'] == info['host'] else info['publisher'] + ' (' + info['host'] + ')'
    return info['label'] + ' · ' + who


def for_records(records):
    """{doc_id: classification} for completed reads, from saved snapshots only."""
    from pathlib import Path
    result = {}
    for r in records:
        if r.get('status') != 'complete' or r['doc_id'] in result:
            continue
        original = Path(r.get('folder', '')) / 'original.bin'
        kind = r.get('coverage', {}).get('kind')
        metadata = page_metadata(original.read_bytes()) if kind == 'html' and original.exists() else None
        result[r['doc_id']] = classify(r.get('final_url') or r['url'], metadata)
    return result


def identities_for_records(records):
    """Display identity from hash-checked saved source bytes; never evidence.

    Keep source-title metadata outside claim text and cite the source URL. An
    absent title remains explicitly absent; no ingestion hash becomes a title.
    """
    import hashlib
    from html import unescape
    from pathlib import Path
    result = {}
    for record in records:
        if record.get('status') != 'complete' or record['doc_id'] in result:
            continue
        original = Path(record.get('folder', '')) / 'original.bin'
        raw = original.read_bytes() if original.exists() else None
        if raw is not None and (not record.get('source_sha256') or hashlib.sha256(raw).hexdigest() != record['source_sha256']):
            raise ValueError('DISPLAY_SOURCE_HASH_CHANGED')
        kind = record.get('coverage', {}).get('kind')
        metadata = page_metadata(raw) if raw is not None and kind == 'html' else None
        identity = classify(record.get('final_url') or record['url'], metadata)
        title = None; origin = None
        if metadata:
            for key in ('citation_title', 'og:title', 'twitter:title'):
                if metadata['meta'].get(key):
                    title = metadata['meta'][key]; origin = key; break
            if not title:
                match = re.search(r'<title\b[^>]*>(.*?)</title\s*>', raw.decode('utf-8', 'replace')[:400000], re.I | re.S)
                if match:
                    title = re.sub(r'<[^>]+>', '', match.group(1)); origin = 'html:title'
        elif raw is not None and kind == 'pdf':
            import pypdfium2
            from .reader import PDF_LOCK
            try:
                with PDF_LOCK, pypdfium2.PdfDocument(original) as document:
                    title = document.get_metadata_dict().get('Title') or None
                    origin = 'pdf:Title' if title else None
            except pypdfium2.PdfiumError:  # an unreadable title stays explicitly absent; the page still renders
                title = None; origin = 'pdf:unreadable'
        identity.update(source_title=' '.join(unescape(title).split()) if title else None,
                        title_origin=origin, source_sha256=record.get('source_sha256'),
                        url=record.get('final_url') or record['url'])
        result[record['doc_id']] = identity
    return result

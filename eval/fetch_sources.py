"""Rebuild eval/incoming/ from eval/incoming/SOURCES.md: download missing PDFs from an allowlist of hosts, verified.

Why: the evaluation PDFs are never committed (size, licensing), so any machine rebuilds the set with this tool and
checks the bytes against the sha256 pinned in eval/registry.json.

Rules, all enforced in code:
- network only when MATN_ALLOW_NETWORK=1 is set for this process (CLAUDE.md rule 2); otherwise nothing is requested;
- HTTPS GET only, to ALLOWED_HOSTS; every redirect hop is checked against the same list; no cookies are kept;
- each URL is printed before it is requested;
- a download lands in a scratch folder OUTSIDE the repository first and enters eval/incoming/ only after it passes:
  HTTP 200, %PDF- magic bytes, sha256 equal to the registry (once registered), the SOURCES.md title on the first
  pages, and English text (an Arabic edition exists for one document);
- an existing file is never overwritten; one whose sha256 differs from the registry is reported;
- the first failure stops the run; the failing temp file is deleted;
- an empty pdf_url is resolved from the row's citation page (one unambiguous PDF link on an allowed host);
- --save-page URL / --save-citation-page FILE keeps a landing page (e.g. the arXiv abstract page, for its license)
  in scratch;
- --compare-copy downloads a second copy of an existing file into scratch only and reports whether the bytes match.
The JSON log holds URLs, HTTP status, content type, sizes, hashes, page counts and check ratios: no document text.

Usage:
  python eval/fetch_sources.py --scratch DIR [--save-page URL ...] [--save-citation-page FILE ...]
                               [--compare-copy FILE ...] [--log PATH] [--dry-run]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import ssl
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from register import parse_sources

REPO = Path(__file__).resolve().parents[1]
ALLOWED_HOSTS = frozenset({
    "arxiv.org",
    "openknowledge.worldbank.org",
    "documents1.worldbank.org",
    "www.gao.gov",
    "gao.gov",
    "nvlpubs.nist.gov",
    "asu.edu.eg",
})
USER_AGENT = "matn-eval-fetch/1 (one-time download of a public evaluation document)"
MAX_BYTES = 200 * 1024 * 1024
TITLE_COVERAGE_MIN = 0.8
LATIN_RATIO_MIN = 0.9
FIRST_PAGES = 3
OK_RESULTS = {"DOWNLOADED", "PRESENT_VERIFIED", "PRESENT_UNREGISTERED", "PAGE_SAVED", "COMPARED"}
STOPWORDS = {"the", "of", "and", "for", "on", "in", "a", "an", "to", "other"}


class FetchRefused(RuntimeError):
    def __init__(self, code: str, **details):
        super().__init__(code)
        self.code = code
        self.details = details


@dataclass
class Response:
    url: str
    final_url: str
    status: int
    content_type: str
    body: bytes
    redirects: list = field(default_factory=list)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def check_url(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise FetchRefused("NOT_HTTPS", url=url)
    if (parts.hostname or "").lower() not in ALLOWED_HOSTS:
        raise FetchRefused("HOST_NOT_ALLOWED", host=parts.hostname)


class AllowlistRedirects(urllib.request.HTTPRedirectHandler):
    """Follows a redirect only to an allowed HTTPS host, and records the chain."""

    def __init__(self):
        super().__init__()
        self.chain: list[str] = []

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl)
        print(f"  REDIRECT {code} -> {newurl}", flush=True)
        self.chain.append(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def tls_context() -> tuple[ssl.SSLContext, dict]:
    """Strict TLS (certificate and hostname checked) against the certifi CA bundle when installed.

    On Windows, Python only sees the roots already present in the Windows store, which fills lazily (39 roots on the
    Step 0 laptop: arxiv.org failed with CERTIFICATE_VERIFY_FAILED). certifi ships Mozilla's CA list. Without
    certifi the system store is used. Verification is never disabled.
    """
    info = tls_info()
    return ssl.create_default_context(cafile=info["cafile"]), info


def tls_info() -> dict:
    """Which CA bundle tls_context() uses (cheap: no context is built)."""
    try:
        import certifi
    except ImportError:
        return {"ca_source": "system", "cafile": None, "certifi_version": None}
    return {"ca_source": "certifi", "cafile": certifi.where(), "certifi_version": certifi.__version__}


def http_get(url: str) -> Response:
    if os.environ.get("MATN_ALLOW_NETWORK") != "1":
        raise FetchRefused("NETWORK_NOT_ALLOWED")
    check_url(url)
    print(f"GET {url}", flush=True)
    redirects = AllowlistRedirects()
    context, _ = tls_context()
    # No HTTPCookieProcessor: cookies are never stored or sent.
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=context), redirects)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"}, method="GET")
    try:
        with opener.open(request, timeout=120) as response:
            body = response.read(MAX_BYTES + 1)
            if len(body) > MAX_BYTES:
                raise FetchRefused("TOO_LARGE", limit=MAX_BYTES)
            return Response(url, response.geturl(), response.status, response.headers.get("Content-Type", ""), body,
                            redirects.chain)
    except urllib.error.HTTPError as err:
        return Response(url, err.geturl() or url, err.code, err.headers.get("Content-Type", "") if err.headers else "",
                        b"", redirects.chain)
    except urllib.error.URLError as err:
        raise FetchRefused("NETWORK_ERROR", reason=str(err.reason)) from err


def first_pages_text(path: Path) -> str:
    import pymupdf  # eval tooling only (ADR-0001)

    with pymupdf.open(path) as doc:
        return "\n".join(doc[i].get_text("text") for i in range(min(FIRST_PAGES, doc.page_count)))


def page_count(path: Path) -> int:
    import pymupdf

    with pymupdf.open(path) as doc:
        return doc.page_count


def latin_ratio(text: str) -> float:
    latin = len(re.findall(r"[A-Za-z]", text))
    arabic = len(re.findall(r"[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]", text))
    return round(latin / (latin + arabic), 4) if latin + arabic else 0.0


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.casefold()) if len(w) > 1 and w not in STOPWORDS}


def title_coverage(title: str, text: str) -> float:
    wanted = _words(title)
    return round(len(wanted & _words(text)) / len(wanted), 4) if wanted else 0.0


def _record(entry: dict, response: Response) -> None:
    entry.update(final_url=response.final_url, redirects=response.redirects, http_status=response.status,
                 content_type=response.content_type, fetched_at_utc=_now())


def _safe_name(url: str) -> str:
    parts = urlsplit(url)
    return re.sub(r"[^a-z0-9]+", "-", f"{parts.hostname}{parts.path}".lower()).strip("-")[:80]


def save_page(url: str, scratch: Path, entry: dict) -> Response:
    entry.update(kind="page", url=url)
    response = http_get(url)
    _record(entry, response)
    if response.status != 200:
        raise FetchRefused("HTTP_STATUS")
    out = scratch / "pages" / f"{_safe_name(url)}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(response.body)
    entry.update(bytes=len(response.body), sha256=_sha(response.body), saved_to=str(out), result="PAGE_SAVED")
    return response


def pdf_links(html: str, base_url: str) -> list[str]:
    """Allowed-host links to a PDF or a DSpace bitstream download; Arabic-edition links are dropped."""
    found = []
    for href in re.findall(r"""href\s*=\s*["']([^"']+)["']""", html, re.IGNORECASE):
        url = urljoin(base_url, href.replace("&amp;", "&"))
        try:
            check_url(url)
        except FetchRefused:
            continue
        path = urlsplit(url).path.lower()
        if not (path.endswith(".pdf") or re.search(r"/bitstreams/[^/]+/download$", path)):
            continue
        if re.search(r"arabic|[/_-]ar([/_.-]|$)", url.lower()):
            continue
        if url not in found:
            found.append(url)
    english = [u for u in found if "/en/" in u.lower() or "english" in u.lower()]
    return english if len(found) > 1 and len(english) == 1 else found


def resolve_pdf_url(page_url: str, scratch: Path, entry: dict) -> str:
    page_entry: dict = {}
    response = save_page(page_url, scratch, page_entry)
    entry.update(resolved_from=page_url, landing_page=page_entry)
    candidates = pdf_links(response.body.decode("utf-8", errors="replace"), response.final_url)
    entry["candidates"] = candidates
    if len(candidates) != 1:
        raise FetchRefused("PDF_LINK_NOT_RESOLVED")
    return candidates[0]


def download_row(row: dict, root: Path, scratch: Path, registry: dict, entry: dict) -> None:
    name = row["file"]
    entry.update(kind="pdf", file=name, registry_sha256=registry.get(name))
    target = root / "incoming" / name
    if target.exists():
        local = _sha(target.read_bytes())
        entry["local_sha256"] = local
        if registry.get(name) and local != registry[name]:
            raise FetchRefused("EXISTING_HASH_MISMATCH")
        entry["result"] = "PRESENT_VERIFIED" if registry.get(name) else "PRESENT_UNREGISTERED"
        return
    url = (row.get("pdf_url") or "").strip()
    if not url:
        if not (row.get("url") or "").strip():
            raise FetchRefused("PDF_URL_MISSING")
        url = resolve_pdf_url(row["url"].strip(), scratch, entry)
    entry["url"] = url
    response = http_get(url)
    _record(entry, response)
    if response.status != 200:
        raise FetchRefused("HTTP_STATUS")
    if not response.body.startswith(b"%PDF-"):
        raise FetchRefused("NOT_PDF")
    entry.update(bytes=len(response.body), sha256=_sha(response.body))
    if registry.get(name) and entry["sha256"] != registry[name]:
        raise FetchRefused("HASH_MISMATCH")
    temp = scratch / f"{name}.partial"
    temp.write_bytes(response.body)
    try:
        text = first_pages_text(temp)
        entry.update(page_count=page_count(temp), title_coverage=title_coverage(row.get("title", ""), text),
                     latin_ratio=latin_ratio(text))
        if entry["title_coverage"] < TITLE_COVERAGE_MIN:
            raise FetchRefused("TITLE_NOT_FOUND")
        if entry["latin_ratio"] < LATIN_RATIO_MIN:
            raise FetchRefused("NOT_ENGLISH")
        shutil.move(str(temp), str(target))
        entry["result"] = "DOWNLOADED"
    finally:
        temp.unlink(missing_ok=True)


def compare_copy(name: str, root: Path, scratch: Path, rows: dict, entry: dict) -> None:
    entry.update(kind="compare", file=name)
    local = root / "incoming" / name
    url = (rows.get(name, {}).get("pdf_url") or "").strip()
    if not local.is_file() or not url:
        raise FetchRefused("COMPARE_NEEDS_LOCAL_FILE_AND_PDF_URL")
    entry["url"] = url
    response = http_get(url)
    _record(entry, response)
    if response.status != 200:
        raise FetchRefused("HTTP_STATUS")
    if not response.body.startswith(b"%PDF-"):
        raise FetchRefused("NOT_PDF")
    out = scratch / "compare" / name
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(response.body)
    local_sha = _sha(local.read_bytes())
    entry.update(bytes=len(response.body), sha256=_sha(response.body), local_sha256=local_sha,
                 local_bytes=local.stat().st_size, equal_to_local=_sha(response.body) == local_sha,
                 page_count=page_count(out), saved_to=str(out), result="COMPARED")


def _registry(root: Path) -> dict[str, str]:
    path = root / "registry.json"
    if not path.is_file():
        return {}
    docs = json.loads(path.read_text(encoding="utf-8")).get("documents", [])
    return {Path(d["file"]).name: d["sha256"] for d in docs if d.get("sha256")}


def _needs_resolution(root: Path, row: dict) -> bool:
    return not (root / "incoming" / row["file"]).exists() and not (row.get("pdf_url") or "").strip()


def run(root: Path, scratch: Path, *, save_pages=(), citation_pages=(), compare_copies=()) -> dict:
    scratch = Path(scratch)
    if scratch.resolve().is_relative_to(REPO.resolve()):
        raise FetchRefused("SCRATCH_INSIDE_REPO")
    scratch.mkdir(parents=True, exist_ok=True)
    rows = parse_sources(root / "incoming" / "SOURCES.md")
    registry = _registry(root)
    log = {"started_utc": _now(), "tool": "eval/fetch_sources.py", "user_agent": USER_AGENT,
           "allowed_hosts": sorted(ALLOWED_HOSTS), "tls": tls_info(), "entries": [], "ok": True}
    save_pages = list(save_pages) + [rows.get(n, {}).get("url", "").strip() for n in citation_pages]
    # Rows whose PDF link must first be resolved from a landing page are the likeliest to stop the run: last.
    direct = [r for r in rows.values() if not _needs_resolution(root, r)]
    resolve = [r for r in rows.values() if _needs_resolution(root, r)]
    jobs = ([lambda e, u=u: save_page(u, scratch, e) for u in save_pages]
            + [lambda e, r=r: download_row(r, root, scratch, registry, e) for r in direct]
            + [lambda e, n=n: compare_copy(n, root, scratch, rows, e) for n in compare_copies]
            + [lambda e, r=r: download_row(r, root, scratch, registry, e) for r in resolve])
    for job in jobs:
        entry: dict = {}
        log["entries"].append(entry)
        try:
            job(entry)
        except FetchRefused as refused:
            entry.update(result=refused.code, **refused.details)
        if entry.get("result") not in OK_RESULTS:
            log["ok"] = False
            break
    log["finished_utc"] = _now()
    return log


def plan(root: Path, save_pages=(), compare_copies=(), citation_pages=()) -> list[str]:
    """The URLs a run would request, without any network access."""
    rows = parse_sources(root / "incoming" / "SOURCES.md")
    save_pages = list(save_pages) + [rows.get(n, {}).get("url", "").strip() for n in citation_pages]
    lines = [f"save page   {u}" for u in save_pages]
    ordered = sorted(rows.values(), key=lambda r: _needs_resolution(root, r))  # same order as run()
    resolve_lines = []
    for row in ordered:
        if _needs_resolution(root, row):
            resolve_lines.append(f"resolve    {row['file']} <- landing page {row.get('url', '').strip()}, "
                                 "then its one PDF link")
            continue
        if (root / "incoming" / row["file"]).exists():
            lines.append(f"present    {row['file']} (hash check only, no request)")
        else:
            lines.append(f"download   {row['file']} <- {row['pdf_url'].strip()}")
    lines += [f"compare    {n} <- {rows.get(n, {}).get('pdf_url', '?')} (scratch only)" for n in compare_copies]
    return lines + resolve_lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Download the evaluation PDFs listed in SOURCES.md (allowlisted hosts).")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--scratch", type=Path, required=True, help="working folder outside the repository")
    parser.add_argument("--save-page", action="append", default=[], metavar="URL")
    parser.add_argument("--save-citation-page", action="append", default=[], metavar="FILE",
                        help="save the citation page (url column) of this SOURCES.md row")
    parser.add_argument("--compare-copy", action="append", default=[], metavar="FILE")
    parser.add_argument("--log", type=Path, default=REPO / "reports" / "step0-evidence" / "fetch-log.json")
    parser.add_argument("--dry-run", action="store_true", help="print the planned requests; no network")
    args = parser.parse_args(argv)
    if args.dry_run:
        print("\n".join(plan(args.root, args.save_page, args.compare_copy, args.save_citation_page)))
        return 0
    try:
        log = run(args.root, args.scratch, save_pages=args.save_page, citation_pages=args.save_citation_page,
                  compare_copies=args.compare_copy)
    except FetchRefused as refused:
        print(f"REFUSED {refused.code} {json.dumps(refused.details)}")
        return 1
    history = json.loads(args.log.read_text(encoding="utf-8")) if args.log.is_file() else {"runs": []}
    history["runs"].append(log)
    args.log.parent.mkdir(parents=True, exist_ok=True)
    args.log.write_text(json.dumps(history, indent=2) + "\n", encoding="utf-8")
    for e in log["entries"]:
        print(f"{e.get('result', '?'):24} {e.get('file') or e.get('url')} sha256={e.get('sha256', '-')} "
              f"status={e.get('http_status', '-')} pages={e.get('page_count', '-')}")
    print(f"ok={log['ok']} log={args.log}")
    return 0 if log["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())

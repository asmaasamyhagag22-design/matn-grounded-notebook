"""Offline tests for eval/fetch_sources.py: every network response is mocked; nothing leaves the machine."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pymupdf
import pytest

import fetch_sources as fs

TITLE = "Harbor Pilot Report on Evidence-First Review"
HEADER = "| file | title | publisher | url | pdf_url | license | license_url | doc_type | notes |\n" + "|---" * 9 + "|\n"


def pdf_bytes(first_page: str, pages: int = 3) -> bytes:
    doc = pymupdf.open()
    for i in range(pages):
        doc.new_page().insert_text((72, 72), first_page if i == 0 else f"Body text of page {i + 1} in English.", fontsize=11)
    return doc.tobytes()


GOOD_PDF = pdf_bytes(f"{TITLE}\nPublished by the Example Office.\nThis report describes an evidence-first pilot.")


def row(file="doc.pdf", pdf_url="https://www.gao.gov/assets/doc.pdf", url="https://www.gao.gov/products/doc"):
    return f"| {file} | {TITLE} | Example Office | {url} | {pdf_url} | public domain | | audit_framework | |\n"


@pytest.fixture()
def root(tmp_path):
    (tmp_path / "eval" / "incoming").mkdir(parents=True)
    (tmp_path / "eval" / "incoming" / "SOURCES.md").write_text(HEADER + row(), encoding="utf-8")
    return tmp_path / "eval"


@pytest.fixture()
def scratch(tmp_path):
    path = tmp_path / "scratch"
    path.mkdir()
    return path


class FakeWeb:
    """Stands in for fs.http_get: url -> (status, content type, body, final url)."""

    def __init__(self, responses):
        self.responses = responses
        self.requested = []

    def __call__(self, url):
        self.requested.append(url)
        fs.check_url(url)  # the real gate runs before any request
        status, ctype, body, final = self.responses[url]
        return fs.Response(url=url, final_url=final or url, status=status, content_type=ctype, body=body, redirects=[])


def run(root, scratch, web, monkeypatch, **kwargs):
    monkeypatch.setattr(fs, "http_get", web)
    log = fs.run(root, scratch, **kwargs)
    return log, {e.get("file") or e.get("url"): e for e in log["entries"]}


# ---------- host allowlist and network gate ----------
@pytest.mark.parametrize("url", ["https://arxiv.org/abs/2601.14525", "https://www.gao.gov/assets/gao-21-519sp.pdf",
                                 "https://gao.gov/x.pdf", "https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.600-1.pdf",
                                 "https://asu.edu.eg/141090/_mediacenter/2025/pdf/x.pdf",
                                 "https://openknowledge.worldbank.org/entities/publication/x",
                                 "https://documents1.worldbank.org/curated/en/x.pdf"])
def test_allowed_hosts_pass_the_gate(url):
    fs.check_url(url)


@pytest.mark.parametrize("url,code", [
    ("https://example.com/x.pdf", "HOST_NOT_ALLOWED"),
    ("https://doi.org/10.6028/NIST.AI.600-1", "HOST_NOT_ALLOWED"),
    ("https://gao.gov.evil.example/x.pdf", "HOST_NOT_ALLOWED"),
    ("https://evil.example/?u=https://gao.gov/x.pdf", "HOST_NOT_ALLOWED"),
    ("http://www.gao.gov/x.pdf", "NOT_HTTPS"),
])
def test_refused_hosts_and_plain_http(url, code):
    with pytest.raises(fs.FetchRefused) as err:
        fs.check_url(url)
    assert err.value.code == code


def test_no_network_without_explicit_env(monkeypatch):
    monkeypatch.delenv("MATN_ALLOW_NETWORK", raising=False)
    with pytest.raises(fs.FetchRefused) as err:
        fs.http_get("https://www.gao.gov/assets/doc.pdf")
    assert err.value.code == "NETWORK_NOT_ALLOWED"


def test_tls_uses_the_certifi_bundle_and_keeps_verification_strict():
    import ssl

    import certifi

    context, info = fs.tls_context()
    assert info == {"ca_source": "certifi", "cafile": certifi.where(), "certifi_version": certifi.__version__}
    assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname is True
    assert len(context.get_ca_certs()) > 100


def test_tls_falls_back_to_the_system_store_without_certifi(monkeypatch):
    import ssl
    import sys

    monkeypatch.setitem(sys.modules, "certifi", None)  # import certifi -> ImportError
    context, info = fs.tls_context()
    assert info == {"ca_source": "system", "cafile": None, "certifi_version": None}
    assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname is True


def test_https_requests_use_that_context(monkeypatch):
    seen = {}

    class Stop(Exception):
        pass

    def fake_build_opener(*handlers):
        seen["handlers"] = handlers
        raise Stop

    monkeypatch.setenv("MATN_ALLOW_NETWORK", "1")
    monkeypatch.setattr(fs.urllib.request, "build_opener", fake_build_opener)
    with pytest.raises(Stop):
        fs.http_get("https://www.gao.gov/assets/doc.pdf")
    https = [h for h in seen["handlers"] if isinstance(h, fs.urllib.request.HTTPSHandler)]
    assert len(https) == 1 and https[0]._context.verify_mode == __import__("ssl").CERT_REQUIRED
    assert len(https[0]._context.get_ca_certs()) > 100


def test_log_records_the_trust_store(root, scratch, monkeypatch):
    web = FakeWeb({"https://www.gao.gov/assets/doc.pdf": (200, "application/pdf", GOOD_PDF, None)})
    log, _ = run(root, scratch, web, monkeypatch)
    assert log["tls"]["ca_source"] in {"certifi", "system"}


def test_redirect_to_a_host_outside_the_list_is_refused():
    handler = fs.AllowlistRedirects()
    with pytest.raises(fs.FetchRefused) as err:
        handler.redirect_request(None, None, 302, "Found", {}, "https://login.example.com/sso")
    assert err.value.code == "HOST_NOT_ALLOWED"


# ---------- downloads ----------
def test_download_from_an_allowed_host_is_verified_logged_and_moved_in(root, scratch, monkeypatch):
    web = FakeWeb({"https://www.gao.gov/assets/doc.pdf": (200, "application/pdf", GOOD_PDF, None)})
    log, entries = run(root, scratch, web, monkeypatch)
    entry = entries["doc.pdf"]
    assert entry["result"] == "DOWNLOADED" and log["ok"] is True
    assert entry["sha256"] == hashlib.sha256(GOOD_PDF).hexdigest() and entry["bytes"] == len(GOOD_PDF)
    assert entry["http_status"] == 200 and entry["content_type"] == "application/pdf" and entry["fetched_at_utc"]
    assert entry["page_count"] == 3 and entry["title_coverage"] == 1.0 and entry["latin_ratio"] == 1.0
    assert (root / "incoming" / "doc.pdf").read_bytes() == GOOD_PDF
    assert list(scratch.rglob("*.partial")) == []


def test_html_instead_of_pdf_is_refused_and_nothing_enters_incoming(root, scratch, monkeypatch):
    web = FakeWeb({"https://www.gao.gov/assets/doc.pdf": (200, "text/html", b"<html>Please sign in</html>", None)})
    log, entries = run(root, scratch, web, monkeypatch)
    assert entries["doc.pdf"]["result"] == "NOT_PDF" and log["ok"] is False
    assert not (root / "incoming" / "doc.pdf").exists() and list(scratch.rglob("*")) == []


def test_hash_mismatch_with_the_registry_is_refused(root, scratch, monkeypatch):
    (root / "registry.json").write_text(json.dumps({"documents": [{"file": "incoming/doc.pdf", "sha256": "0" * 64}]}))
    web = FakeWeb({"https://www.gao.gov/assets/doc.pdf": (200, "application/pdf", GOOD_PDF, None)})
    log, entries = run(root, scratch, web, monkeypatch)
    assert entries["doc.pdf"]["result"] == "HASH_MISMATCH" and log["ok"] is False
    assert not (root / "incoming" / "doc.pdf").exists() and list(scratch.rglob("*")) == []


def test_existing_file_with_a_different_hash_is_never_overwritten(root, scratch, monkeypatch):
    (root / "incoming" / "doc.pdf").write_bytes(b"%PDF-1.7 local copy")
    (root / "registry.json").write_text(json.dumps({"documents": [{"file": "incoming/doc.pdf", "sha256": "0" * 64}]}))
    web = FakeWeb({})
    log, entries = run(root, scratch, web, monkeypatch)
    assert entries["doc.pdf"]["result"] == "EXISTING_HASH_MISMATCH" and log["ok"] is False
    assert (root / "incoming" / "doc.pdf").read_bytes() == b"%PDF-1.7 local copy" and web.requested == []


def test_present_file_matching_the_registry_is_not_downloaded_again(root, scratch, monkeypatch):
    (root / "incoming" / "doc.pdf").write_bytes(GOOD_PDF)
    sha = hashlib.sha256(GOOD_PDF).hexdigest()
    (root / "registry.json").write_text(json.dumps({"documents": [{"file": "incoming/doc.pdf", "sha256": sha}]}))
    web = FakeWeb({})
    log, entries = run(root, scratch, web, monkeypatch)
    assert entries["doc.pdf"]["result"] == "PRESENT_VERIFIED" and log["ok"] is True and web.requested == []


def test_wrong_document_is_refused(root, scratch, monkeypatch):
    body = pdf_bytes("Quarterly Bulletin of Something Else\nUnrelated text in English.")
    web = FakeWeb({"https://www.gao.gov/assets/doc.pdf": (200, "application/pdf", body, None)})
    log, entries = run(root, scratch, web, monkeypatch)
    assert entries["doc.pdf"]["result"] == "TITLE_NOT_FOUND" and not (root / "incoming" / "doc.pdf").exists()


def test_non_english_edition_is_refused(root, scratch, monkeypatch):
    # The Arabic edition carries the English title on its cover but Arabic body text.
    monkeypatch.setattr(fs, "first_pages_text", lambda path: TITLE + " " + "تقرير تجريبي عن المراجعة القائمة على الأدلة " * 20)
    web = FakeWeb({"https://www.gao.gov/assets/doc.pdf": (200, "application/pdf", GOOD_PDF, None)})
    log, entries = run(root, scratch, web, monkeypatch)
    assert entries["doc.pdf"]["result"] == "NOT_ENGLISH" and entries["doc.pdf"]["latin_ratio"] < 0.9
    assert not (root / "incoming" / "doc.pdf").exists()


@pytest.mark.parametrize("text,ratio", [("abc def", 1.0), ("مرحبا", 0.0), ("ab مر", 0.5)])
def test_latin_ratio(text, ratio):
    assert fs.latin_ratio(text) == ratio


def test_http_error_status_is_refused(root, scratch, monkeypatch):
    web = FakeWeb({"https://www.gao.gov/assets/doc.pdf": (403, "text/html", b"", None)})
    log, entries = run(root, scratch, web, monkeypatch)
    assert entries["doc.pdf"]["result"] == "HTTP_STATUS" and entries["doc.pdf"]["http_status"] == 403


def test_first_failure_stops_the_run(root, scratch, monkeypatch):
    sources = root / "incoming" / "SOURCES.md"
    sources.write_text(HEADER + row("a.pdf", "https://www.gao.gov/a.pdf") + row("b.pdf", "https://www.gao.gov/b.pdf"))
    web = FakeWeb({"https://www.gao.gov/a.pdf": (200, "text/html", b"<html></html>", None),
                   "https://www.gao.gov/b.pdf": (200, "application/pdf", GOOD_PDF, None)})
    log, entries = run(root, scratch, web, monkeypatch)
    assert web.requested == ["https://www.gao.gov/a.pdf"] and "b.pdf" not in entries


def test_log_has_hashes_and_urls_but_no_document_text(root, scratch, monkeypatch):
    web = FakeWeb({"https://www.gao.gov/assets/doc.pdf": (200, "application/pdf", GOOD_PDF, None)})
    log, _ = run(root, scratch, web, monkeypatch)
    assert "evidence-first pilot" not in json.dumps(log) and "Example Office" not in json.dumps(log)


# ---------- landing pages and link resolution ----------
WB_URL = "https://openknowledge.worldbank.org/entities/publication/300aaa4c"


def wb_row(pdf_url=""):
    return row("wb.pdf", pdf_url, WB_URL)


def test_empty_pdf_url_is_resolved_from_the_landing_page(root, scratch, monkeypatch):
    (root / "incoming" / "SOURCES.md").write_text(HEADER + wb_row(), encoding="utf-8")
    html = (b'<a href="/bitstreams/1111-aaaa/download">English PDF</a>'
            b'<a href="https://documents1.worldbank.org/curated/en/123/pdf/Egypt-Arabic.pdf">AR</a>'
            b'<a href="https://example.com/other.pdf">elsewhere</a>')
    resolved = "https://openknowledge.worldbank.org/bitstreams/1111-aaaa/download"
    web = FakeWeb({WB_URL: (200, "text/html; charset=utf-8", html, None),
                   resolved: (200, "application/pdf", GOOD_PDF, None)})
    log, entries = run(root, scratch, web, monkeypatch)
    assert entries["wb.pdf"]["result"] == "DOWNLOADED" and entries["wb.pdf"]["url"] == resolved
    assert entries["wb.pdf"]["resolved_from"] == WB_URL
    assert list(scratch.glob("pages/*.html"))  # the landing page is kept in scratch, outside the repository


def test_rows_that_need_link_resolution_run_last(root, scratch, monkeypatch):
    (root / "incoming" / "SOURCES.md").write_text(HEADER + wb_row() + row(), encoding="utf-8")
    (root / "incoming" / "local.pdf").write_bytes(GOOD_PDF)
    web = FakeWeb({WB_URL: (200, "text/html", b"<p>no links</p>", None),
                   "https://www.gao.gov/assets/doc.pdf": (200, "application/pdf", GOOD_PDF, None)})
    log, entries = run(root, scratch, web, monkeypatch)
    assert web.requested == ["https://www.gao.gov/assets/doc.pdf", WB_URL]
    assert entries["doc.pdf"]["result"] == "DOWNLOADED" and entries["wb.pdf"]["result"] == "PDF_LINK_NOT_RESOLVED"


def test_ambiguous_landing_page_links_stop_the_run(root, scratch, monkeypatch):
    (root / "incoming" / "SOURCES.md").write_text(HEADER + wb_row(), encoding="utf-8")
    html = b'<a href="/bitstreams/1111/download">a</a><a href="/bitstreams/2222/download">b</a>'
    web = FakeWeb({WB_URL: (200, "text/html", html, None)})
    log, entries = run(root, scratch, web, monkeypatch)
    assert entries["wb.pdf"]["result"] == "PDF_LINK_NOT_RESOLVED" and len(entries["wb.pdf"]["candidates"]) == 2
    assert web.requested == [WB_URL]


def test_saved_page_goes_to_scratch_only(root, scratch, monkeypatch):
    url = "https://arxiv.org/abs/2601.14525"
    (root / "incoming" / "SOURCES.md").write_text(HEADER, encoding="utf-8")
    web = FakeWeb({url: (200, "text/html", b"<html>abs</html>", None)})
    log, entries = run(root, scratch, web, monkeypatch, save_pages=[url])
    assert entries[url]["result"] == "PAGE_SAVED" and Path(entries[url]["saved_to"]).read_bytes() == b"<html>abs</html>"
    assert Path(entries[url]["saved_to"]).is_relative_to(scratch)


def test_citation_page_of_a_row_is_saved_by_file_name(root, scratch, monkeypatch):
    (root / "incoming" / "doc.pdf").write_bytes(GOOD_PDF)  # present: only the page is requested
    web = FakeWeb({"https://www.gao.gov/products/doc": (200, "text/html", b"<html>landing</html>", None)})
    log, entries = run(root, scratch, web, monkeypatch, citation_pages=["doc.pdf"])
    assert entries["https://www.gao.gov/products/doc"]["result"] == "PAGE_SAVED"
    assert web.requested == ["https://www.gao.gov/products/doc"]
    assert fs.plan(root, citation_pages=["doc.pdf"])[0] == "save page   https://www.gao.gov/products/doc"


def test_scratch_inside_the_repository_is_refused(root, monkeypatch):
    monkeypatch.setattr(fs, "REPO", root.parent)
    with pytest.raises(fs.FetchRefused) as err:
        fs.run(root, root / "tmp-scratch")
    assert err.value.code == "SCRATCH_INSIDE_REPO"


# ---------- comparison copy (never replaces the local file) ----------
def test_compare_copy_reports_equality_and_never_touches_incoming(root, scratch, monkeypatch):
    local = pdf_bytes(f"{TITLE}\nlocal copy text in English for the comparison.")
    (root / "incoming" / "doc.pdf").write_bytes(local)
    web = FakeWeb({"https://www.gao.gov/assets/doc.pdf": (200, "application/pdf", GOOD_PDF, None)})
    log, entries = run(root, scratch, web, monkeypatch, compare_copies=["doc.pdf"])
    entry = [e for e in log["entries"] if e["kind"] == "compare"][0]
    assert entry["equal_to_local"] is False and entry["local_sha256"] == hashlib.sha256(local).hexdigest()
    assert (root / "incoming" / "doc.pdf").read_bytes() == local
    assert Path(entry["saved_to"]).is_relative_to(scratch)

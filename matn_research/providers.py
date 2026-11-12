"""Small search interface. No cloud extraction and no account creation.

Search is discovery only (ADR-0035). A provider declares a `retention_policy`;
`retain` applies it before a result leaves the provider, so no caller, checkpoint
or ledger can persist provider content the policy does not allow. Evidence always
comes from pages Matn fetches itself (`reader.read_source`).
"""
import json
import os
import shlex
from pathlib import Path
import time
from typing import Protocol
from .network import request
from .retention import RETENTION_POLICIES, envelope, policy_of, retain  # noqa: F401  (re-exported)


class SearchProvider(Protocol):
    name: str
    retention_policy: str

    def search(self, query: str) -> dict: ...


def load_settings(path=None):
    """Read the owner's local key file as data, never execute shell commands."""
    path = Path(path) if path else Path.home() / '.config/matn/tavily.env'
    if not os.environ.get('TAVILY_API_KEY') and path.is_file():
        for line in path.read_text().splitlines():
            fields = shlex.split(line, comments=True)
            if fields and fields[0] == 'export':
                fields = fields[1:]
            if len(fields) == 1 and fields[0].startswith('TAVILY_API_KEY='):
                os.environ['TAVILY_API_KEY'] = fields[0].split('=', 1)[1]
    return dict(settings_file_present=path.is_file(), key_present=bool(os.environ.get('TAVILY_API_KEY')))


def qualify(proof=None, *, usage=None, free_credit_budget=None):
    """Only presence is reported. Account proof must be provided by the owner.

    Public pricing documentation does not establish this account's billing.
    Never infer a free account from the shape of a key or run a billable probe.
    """
    result = dict(provider='tavily-search', key_present=bool(os.environ.get('TAVILY_API_KEY')),
                  status='BLOCKED', reasons=[])
    if not result['key_present']:
        result['reasons'].append('TAVILY_API_KEY_MISSING')
    value = json.loads(Path(proof).read_bytes()) if proof else {}
    valid = (value.get('provider') == 'tavily-search' and value.get('plan') == 'free'
             and value.get('pay_as_you_go') is False and value.get('spending_enabled') is False
             and value.get('remaining_credits', 0) >= 12
             and 0 <= time.time() - value.get('verified_at', 0) < 86400
             and value.get('owner_attested') is True and bool(value.get('evidence_reference')))
    if usage is not None:
        account = usage.get('account', {})
        key = usage.get('key', {})
        # A zero usage counter says nothing about paid spending; only an
        # explicit zero PAYG limit is used. Unknown fields remain unknown.
        remaining = account.get('plan_limit', 0) - account.get('plan_usage', 0)
        key_limit = key.get('limit')
        key_used = key.get('usage', 0)
        # No per-key cap (null) cannot create paid spend when account PAYG
        # limit is explicitly zero. A configured numeric cap must have room.
        key_has_room = key_limit is None or (isinstance(key_limit, (int, float)) and isinstance(key_used, (int, float)) and key_limit - key_used >= 12)
        valid_usage = (str(account.get('current_plan', '')).lower() in ('free', 'researcher')
                       and remaining >= 12 and key_has_room
                       and account.get('paygo_limit') == 0)
        bounded_free = (type(free_credit_budget) is int and 1 <= free_credit_budget <= 12
                        and str(account.get('current_plan', '')).lower() in ('free', 'researcher')
                        and remaining >= free_credit_budget
                        and (key_limit is None or (isinstance(key_limit, (int, float)) and key_limit - key_used >= free_credit_budget)))
        valid = bounded_free if free_credit_budget is not None else (valid or valid_usage)
        result['account_usage'] = usage
        result['payg_status'] = 'unknown' if account.get('paygo_limit') is None else 'limit_reported; usage_is_not_enablement'
        if bounded_free:
            result['free_credit_budget'] = free_credit_budget
        result['qualification_basis'] = 'proven free credits cover bounded basic-request budget; PAYG not inferred' if bounded_free else 'usage: free plan, remaining credits, explicit zero PAYG limit' if valid_usage else 'saved owner settings or insufficient usage evidence'
    if not valid:
        result['reasons'].append('FREE_QUOTA_AND_SPENDING_DISABLED_PROOF_MISSING')
    if not result['reasons']:
        result['status'] = 'READY'
    return result


def discover(provider, query):
    """The only way the pipeline searches: applies the provider's declared policy again.

    The policy is validated before the (billable) request. A provider that declares
    no policy gets the strictest one, and only allowlisted top-level keys survive,
    so a new or misconfigured provider cannot put its content into a checkpoint.
    """
    policy = policy_of(provider)
    return envelope(provider.search(query), policy)


class TavilySearch:
    name = 'tavily-search'
    # Tavily Search API Agreement (2023-11-30; re-checked 2026-11-04, see
    # docs/compliance/search-providers.md): no storing or caching of output.
    retention_policy = 'discovery-urls'

    def __init__(self, proof, *, usage=None, free_credit_budget=None, max_results=4):
        policy_of(self)  # an unknown policy fails here, before any credit is spent
        import threading
        self.proof = proof
        self.usage = usage
        self.free_credit_budget = free_credit_budget
        self.requests_sent = 0
        self.max_results = max_results
        self._lock = threading.Lock()  # concurrent searches share one budget check and counter
        self._batch = 0
        self._usage_at = time.time() if usage is not None else 0.0; self._sent_at_usage = 0

    def admit_batch(self, n):
        """One usage read for the next n searches (the usage endpoint is rate limited)."""
        if self.free_credit_budget is None or n <= 0:
            return
        with self._lock:
            n = min(n, self.free_credit_budget - self.requests_sent)
            if n <= 0:
                raise ValueError('PROVIDER_LOCAL_REQUEST_CAP')
            # Reuse a usage read younger than 120 s: the remaining credits must still cover
            # everything sent since then plus this batch. Otherwise read usage once.
            fresh = self.usage is not None and time.time() - self._usage_at < 120
            if not fresh:
                self.usage = account_usage(); self._usage_at = time.time(); self._sent_at_usage = self.requests_sent
            budget = n + self.requests_sent - self._sent_at_usage
            if budget > 12 or qualify(self.proof, usage=self.usage, free_credit_budget=budget)['status'] != 'READY':
                self.usage = account_usage(); self._usage_at = time.time(); self._sent_at_usage = self.requests_sent
                if qualify(self.proof, usage=self.usage, free_credit_budget=n)['status'] != 'READY':
                    raise ValueError('LIVE_DISCOVERY_BLOCKED')
            self._batch = n

    def search(self, query):
        with self._lock:
            payload = self._admit(query)
        raw = request('https://api.tavily.com/search', method='POST',
                      body=json.dumps(payload).encode(), redirects=0, max_bytes=512000,
                      headers={'Authorization': 'Bearer ' + os.environ['TAVILY_API_KEY'],
                               'Content-Type': 'application/json'})
        # The full body lives only in this frame. Callers (and every checkpoint)
        # get URLs in provider rank order plus credit usage, never content.
        response, dropped = retain(json.loads(raw['body']), self.retention_policy)
        return dict(provider=self.name, query=query, at=raw['fetched_at'], request=payload,
                    retention_policy=self.retention_policy, dropped_fields=dropped,
                    response=response, usage_before=self.usage)

    def _admit(self, query):
        if self.free_credit_budget is not None:
            if self.requests_sent >= self.free_credit_budget:
                raise ValueError('PROVIDER_LOCAL_REQUEST_CAP')
            # Read account usage before EACH billable-credit request (or once per declared
            # batch: the whole batch must fit the proven free credits). Null PAYG remains
            # unknown; never consume beyond proven free credits.
            if self._batch > 0:
                self._batch -= 1; eligibility = dict(status='READY')
            else:
                self.usage = account_usage()
                eligibility = qualify(self.proof, usage=self.usage, free_credit_budget=1)
        else:
            eligibility = qualify(self.proof, usage=self.usage) if self.usage is not None else qualify(self.proof)
        if eligibility['status'] != 'READY':
            raise ValueError('LIVE_DISCOVERY_BLOCKED')
        payload = dict(query=query, search_depth='basic', auto_parameters=False,
                       include_answer=False, include_raw_content=False,
                       include_images=False, max_results=self.max_results, topic='general', include_usage=True)
        self.requests_sent += 1
        return payload


def account_usage():
    """Read only documented usage data; never persist auth headers or the key."""
    if not os.environ.get('TAVILY_API_KEY'):
        raise ValueError('TAVILY_API_KEY_MISSING')
    raw = request('https://api.tavily.com/usage', redirects=0, max_bytes=64000,
                  headers={'Authorization': 'Bearer ' + os.environ['TAVILY_API_KEY']})
    value = json.loads(raw['body'])
    # Whitelist documented non-secret fields, rather than saving an arbitrary
    # authenticated response with possible future credential additions.
    return {group: {k: v for k, v in value.get(group, {}).items() if k in fields}
            for group, fields in {
                'key': ('usage', 'limit', 'search_usage', 'extract_usage', 'crawl_usage', 'map_usage', 'research_usage'),
                'account': ('current_plan', 'plan_usage', 'plan_limit', 'paygo_usage', 'paygo_limit',
                            'search_usage', 'extract_usage', 'crawl_usage', 'map_usage', 'research_usage')}.items()}

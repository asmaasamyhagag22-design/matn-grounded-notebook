"""Search-provider retention policies (ADR-0035). Standard library only.

This module has no package imports on purpose: the app's frozen-research launcher
loads it by file path to enforce the same policy on immutable delivery code.

`discovery-urls` keeps only each result's URL, in the provider's rank order (a
result without a URL stays as an empty placeholder so ranks do not shift), plus
credit `usage`. Titles, snippets, raw content, answers, scores and request IDs
are dropped. `storage-rights` keeps everything and is only for a provider whose
written terms allow storage.
"""

RETENTION_POLICIES = {
    'discovery-urls': dict(result_fields=('url',), body_fields=('usage',)),
    'storage-rights': dict(result_fields=None, body_fields=None),
}
DEFAULT_POLICY = 'discovery-urls'
# The only top-level keys a search result may carry to a checkpoint; anything
# else a provider returns is dropped and named in `dropped_fields`.
ENVELOPE = ('provider', 'query', 'at', 'request', 'usage_before', 'response', 'retention_policy', 'dropped_fields')


def policy_of(provider):
    """The provider's declared policy, the strictest one if none; unknown names fail before any request."""
    policy = getattr(provider, 'retention_policy', None) or DEFAULT_POLICY
    if policy not in RETENTION_POLICIES:
        raise ValueError('UNKNOWN_RETENTION_POLICY:' + str(policy))
    return policy


def retain(body, policy):
    """Reduce a provider response body to what `policy` allows on disk; report dropped field names only."""
    if policy not in RETENTION_POLICIES:
        raise ValueError('UNKNOWN_RETENTION_POLICY:' + str(policy))
    rule = RETENTION_POLICIES[policy]
    body = body if isinstance(body, dict) else {}
    if rule['result_fields'] is None:
        return body, []
    dropped = set()
    results = []
    for hit in body.get('results') or []:
        if not isinstance(hit, dict) or not isinstance(hit.get('url'), str):
            results.append({})  # keeps the provider rank of every later result
            continue
        dropped |= set(hit) - set(rule['result_fields'])
        results.append({k: hit[k] for k in rule['result_fields']})
    dropped |= {'body.' + k for k in body if k not in rule['body_fields'] and k != 'results'}
    kept = {k: body[k] for k in rule['body_fields'] if k in body}
    return dict(kept, results=results), sorted(dropped)


def envelope(result, policy):
    """Apply `policy` to a whole search result: allowlisted top-level keys, reduced response."""
    result = result if isinstance(result, dict) else {}
    response, dropped = retain(result.get('response') or {}, policy)
    out = {k: result[k] for k in ENVELOPE if k in result}
    extra = {'envelope.' + k for k in result if k not in ENVELOPE}
    out.update(response=response, retention_policy=policy,
               dropped_fields=sorted(set(result.get('dropped_fields') or []) | set(dropped) | extra))
    return out


def scrub_reading_records(records):
    """Copies of reading-status rows for a new run, without provider-derived fields.

    Before ADR-0035 `suitability.metadata_matches` was computed from search titles
    and snippets. Nothing reads it, so copies drop it rather than carry it forward.
    """
    out = []
    for row in records:
        row = dict(row)
        if isinstance(row.get('suitability'), dict) and 'metadata_matches' in row['suitability']:
            row['suitability'] = {k: v for k, v in row['suitability'].items() if k != 'metadata_matches'}
            row['suitability']['metadata_matches_removed'] = 'ADR-0035: provider-derived on the parent run'
        out.append(row)
    return out

"""Explicit owner checkpoints add allowances without reopening prior journals."""
import json
from pathlib import Path
import time
from matn_chat.readiness import write
from matn_storyboard.core import digest

KINDS = ('generation', 'native')


def _read(path):
    return json.loads(Path(path).read_bytes())


def _historical(parent):
    if 'cumulative' in parent:
        return {k: parent['cumulative'][k] for k in KINDS}
    lineage = parent['lineage']
    return dict(generation=lineage['total_generation'], native=lineage['native_total'])


def _counts(value):
    return set(value) == set(KINDS) and all(type(value[k]) is int and value[k] >= 0 for k in KINDS)


def authorize_continuation(folder, parent_final, *, additional, cumulative, reason):
    """Call only with an explicit owner grant. No automatic renewal or migration."""
    folder = Path(folder); path = folder/'continuation-authorization.json'
    ledger = _read(folder/'ledger.json')
    if path.exists() or ledger.get('continuation_authorization'):
        raise ValueError('CONTINUATION_ALREADY_AUTHORIZED')
    if any(ledger['calls'][k] for k in KINDS):
        raise ValueError('CONTINUATION_MUST_PRECEDE_CALLS')
    parent_final = Path(parent_final).resolve(); parent = _read(parent_final)
    prior = _historical(parent)
    if (not all(_counts(v) for v in (prior, additional, cumulative)) or not reason.strip()
            or any(prior[k]+additional[k] != cumulative[k] for k in KINDS)):
        raise ValueError('CONTINUATION_CUMULATIVE_MISMATCH')
    value = dict(parent_final=str(parent_final), parent_sha256=digest(parent), historical=prior,
        additional=additional, cumulative_cap=cumulative, reason=reason, authorized_at=time.time())
    write(path, value)
    ledger['continuation_authorization'] = digest(value); write(folder/'ledger.json', ledger)
    return value


def accounting(folder):
    folder = Path(folder); ledger = _read(folder/'ledger.json')
    path = folder/'continuation-authorization.json'
    if not path.exists() or not ledger.get('continuation_authorization'):
        raise ValueError('CONTINUATION_AUTHORIZATION_MISSING')
    value = _read(path)
    if digest(value) != ledger['continuation_authorization']:
        raise ValueError('CONTINUATION_AUTHORIZATION_DRIFT')
    parent = _read(value['parent_final'])
    if digest(parent) != value['parent_sha256'] or _historical(parent) != value['historical']:
        raise ValueError('CONTINUATION_PARENT_DRIFT')
    prior, additional, caps = (value[k] for k in ('historical','additional','cumulative_cap'))
    if not all(_counts(v) for v in (prior, additional, caps)) or any(prior[k]+additional[k] != caps[k] for k in KINDS):
        raise ValueError('CONTINUATION_CUMULATIVE_MISMATCH')
    current = {k: ledger['calls'][k] for k in KINDS}
    if not _counts(current) or any(current[k]>additional[k] for k in KINDS):
        raise ValueError('CONTINUATION_CAP_EXCEEDED')
    return dict(historical=prior, additional_cap=additional, new=current,
        cumulative={k: prior[k]+current[k] for k in KINDS}, cumulative_cap=caps)

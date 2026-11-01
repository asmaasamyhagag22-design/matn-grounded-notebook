"""One-command public research; saved state resumes under its original deadline."""
import argparse
import json
from pathlib import Path
import sys

from matn_chat.readiness import write
from matn_storyboard.budget import open_ledger, supervise
from matn_storyboard.core import save_version
from .models import Brief
from .providers import qualify, TavilySearch, account_usage, load_settings
from .preview import publish


def display_policy(*, legacy=False):
    """New CLI runs show local context; library callers retain saved defaults."""
    from .workflow import FEATURES
    FEATURES['context_display'] = not legacy
    FEATURES['subject_binding'] = bool(legacy)


def worker(folder, brief, ledger, proof, requirements=None, reading_context=False):
    from eval.chat.token_budget import TokenCounter
    from matn_storyboard.units import identity
    from .runtime import ResearchCalls, ResearchGenerator, ResearchNative, initialized_session
    from .workflow import run
    calls = ResearchCalls(ledger); native = ResearchNative(calls, identity()); counter = TokenCounter()
    try:
        generator = ResearchGenerator(calls)
        with initialized_session(calls, generator):
            usage = account_usage()
            eligibility = qualify(proof, usage=usage, free_credit_budget=12)
            write(Path(folder) / 'usage-before.json', usage)
            write(Path(folder) / 'provider-qualification.json', eligibility)
            if eligibility['status'] != 'READY':
                raise ValueError('FREE_ACCOUNT_USAGE_NOT_QUALIFIED')
            result = run(folder, brief, requirements=requirements, local_slots='requirements' if reading_context else False, provider=TavilySearch(proof, usage=usage, free_credit_budget=12), generator=generator, native=native, counter=counter)
            write(Path(folder) / 'outcome.json', result)
            path = Path(folder) / 'v1.json'
            publish(folder, json.loads(path.read_bytes()) if path.exists() else None)
            print(json.dumps(result))
    except Exception as exc:
        state_path = Path(folder) / 'state.json'
        state = json.loads(state_path.read_bytes()) if state_path.exists() else {}
        failed = [name for name, row in state.get('jobs', {}).items() if row['status'] != 'complete']
        write(Path(folder) / 'outcome.json', dict(status='INCOMPLETE', first_loss=failed[-1] if failed else 'pipeline_admission',
              error=type(exc).__name__, detail=str(exc)[:200], full_journey_accepted=False))
        publish(folder)
        raise
    finally:
        counter.close(); native.close()


def live_worker(folder, brief, ledger, *, preset, plan=None, plan_only=False):
    """Matn v2 path under the same supervisor, ledger, drain and verification contracts."""
    from eval.chat.token_budget import TokenCounter
    from matn_storyboard.units import identity
    from .fast import run_v2
    from .runtime import ResearchCalls, ResearchGenerator, ResearchNative, initialized_session
    calls = ResearchCalls(ledger); native = ResearchNative(calls, identity()); counter = TokenCounter()
    config = preset.get('v2', {}); budget = preset.get('search_budget', 12)
    try:
        generator = ResearchGenerator(calls); generator.resident = bool(preset.get('resident', False))
        with initialized_session(calls, generator):
            provider = None
            if not plan_only:
                usage = account_usage()
                eligibility = qualify(None, usage=usage, free_credit_budget=budget)
                write(Path(folder) / 'usage-before.json', usage)
                write(Path(folder) / 'provider-qualification.json', eligibility)
                if eligibility['status'] != 'READY':
                    raise ValueError('FREE_ACCOUNT_USAGE_NOT_QUALIFIED')
                provider = TavilySearch(None, usage=usage, free_credit_budget=budget, max_results=config.get('max_results', 4))
            try:
                result = run_v2(folder, brief, provider=provider, generator=generator, native=native, counter=counter,
                                config=config, plan_override=plan, plan_only=plan_only)
            finally:
                native.close(); generator.release()
            write(Path(folder) / 'outcome.json', result)
            print(json.dumps({k: v for k, v in result.items() if k != 'plan'}))
    except Exception as exc:
        state_path = Path(folder) / 'state.json'
        state = json.loads(state_path.read_bytes()) if state_path.exists() else {}
        failed = [name for name, row in state.get('jobs', {}).items() if row['status'] != 'complete']
        write(Path(folder) / 'outcome.json', dict(status='INCOMPLETE', first_loss=failed[-1] if failed else 'pipeline_admission',
              error=type(exc).__name__, detail=str(exc)[:200], full_journey_accepted=False))
        version = Path(folder) / 'v1.json'
        publish(folder, json.loads(version.read_bytes()) if version.exists() else None)
        raise
    finally:
        counter.close(); native.close()


def saved_worker(folder, pack_path, reading_status, ledger, *, reading_context=False, follow_gaps=False, proof=None):
    """Existing source snapshots, fresh analysis and shared product finalization."""
    from eval.chat.token_budget import TokenCounter
    from matn_contracts.structure import DocumentStructure
    from matn_storyboard.units import identity
    from .runtime import ResearchCalls, ResearchGenerator, ResearchNative, initialized_session
    from .workflow import continue_saved
    records = json.loads(Path(reading_status).read_bytes())
    documents = [DocumentStructure.model_validate_json((Path(r['folder'])/'document.json').read_bytes())
        for r in records if r.get('independent') and r.get('status') == 'complete']
    for d in documents:
        write(Path(folder)/'sources'/d.doc_id/'document.json',d.model_dump(mode='json'))
    saved = json.loads(Path(pack_path).read_bytes())
    calls = ResearchCalls(ledger); native = ResearchNative(calls, identity()); counter = TokenCounter()
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
    write(folder/'reading-status.json', records)
    try:
        generator = ResearchGenerator(calls)
        with initialized_session(calls, generator):
            provider = None
            if follow_gaps:
                load_settings(); usage = account_usage()
                eligibility = qualify(proof,usage=usage,free_credit_budget=12)
                write(folder/'provider-qualification.json',eligibility)
                if eligibility['status'] != 'READY': raise ValueError('FREE_ACCOUNT_USAGE_NOT_QUALIFIED')
                provider = TavilySearch(proof,usage=usage,free_credit_budget=12)
            result = continue_saved(folder, saved, documents, generator=generator, native=native,
                                    counter=counter, local_slots='requirements' if reading_context else False, provider=provider, reading_records=records)
            write(folder/'outcome.json', result)
            version = folder/'v1.json'
            publish(folder, json.loads(version.read_bytes()) if version.exists() else None)
            print(json.dumps(result))
    except Exception as exc:
        write(folder/'outcome.json', dict(status='INCOMPLETE', error=type(exc).__name__,
            detail=str(exc)[:240], full_journey_accepted=False))
        publish(folder)
        raise
    finally:
        counter.close(); native.close()


def refinement_worker(folder, parent, facet, producer_snapshot, ledger):
    from eval.chat.token_budget import TokenCounter
    from .runtime import ResearchCalls, ResearchGenerator, ResearchNative, initialized_session
    from .workflow import refine_saved_result
    from matn_storyboard.units import identity
    calls=ResearchCalls(ledger);generator=ResearchGenerator(calls)
    native=ResearchNative(calls,identity());counter=TokenCounter()
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    try:
        with initialized_session(calls,generator):
            result=refine_saved_result(folder,parent,facet,producer_snapshot,generator=generator,native=native,counter=counter)
            write(folder/'outcome.json',result)
            publish(folder,json.loads((folder/'v1.json').read_bytes()))
            print(json.dumps(result))
    except Exception as exc:
        write(folder/'outcome.json',dict(status='INCOMPLETE',error=type(exc).__name__,detail=str(exc)[:240],full_journey_accepted=False))
        publish(folder);raise
    finally:counter.close();native.close()


def edit(folder, parent, operations, ledger=None, phase='experiments'):
    from matn_storyboard.units import style_version, identity
    from matn_storyboard.unit_composition import ComposedWorkflow
    from matn_contracts.structure import DocumentStructure
    if all(op['op'] == 'style' for op in operations):
        return style_version(parent, operations)
    if ledger is None:
        raise ValueError('FACTUAL_EDIT_REQUIRES_GUARDED_LEDGER')
    from .runtime import ResearchCalls, ResearchNative
    native = ResearchNative(ResearchCalls(ledger, phase=phase), identity())
    try:
        documents = [DocumentStructure.model_validate_json(p.read_bytes()) for p in (Path(folder) / 'sources').glob('*/document.json')]
        pack = json.loads((Path(folder) / 'evidence-pack.json').read_bytes())
        # Duplicate-content snapshots are retained as originals, not independent evidence.
        documents = list({d.doc_id: d for d in documents if d.doc_id in pack['sources']}.values())
        flow = ComposedWorkflow(documents, pack, native)
        native.identity = flow.identity
        return flow.edit(parent, operations)
    finally:
        native.close()


def live_main(a):
    folder = Path(a.out); folder.mkdir(parents=True, exist_ok=True)
    request_path = folder / 'request.json'
    if a.topic:
        goal = a.goal or ('Prepare a bounded evidence-backed introductory briefing on ' + a.topic + ' for ' + a.audience)
        brief = Brief(topic=a.topic, audience=a.audience, goal=goal, scope=a.scope, public_topic=True).model_dump()
        if request_path.exists() and json.loads(request_path.read_bytes()) != brief:
            raise ValueError('NEW_BRIEF_REQUIRES_NEW_OUTPUT_FOLDER')
        write(request_path, brief)
    else:
        brief = json.loads(request_path.read_bytes())
    preset = json.loads(Path(a.preset).read_bytes())
    plan = json.loads(Path(a.plan).read_bytes()) if a.plan else None
    if a.worker:
        load_settings(); display_policy()
        live_worker(folder, brief, Path(a.ledger), preset=preset, plan=plan, plan_only=a.plan_only); return
    ledger = Path(a.ledger)
    if not (ledger / 'ledger.json').exists():
        open_ledger(ledger, experiment=6 * 3600, validation=1800, closure=900)
    command = [sys.executable, '-m', 'matn_research', 'live', '--out', str(folder), '--ledger', str(ledger),
               '--preset', a.preset, '--worker'] + (['--plan', a.plan] if a.plan else []) + (['--plan-only'] if a.plan_only else [])
    row = supervise(ledger, 'experiments', command, timeout=a.timeout)
    if row['returncode'] or row['stop_reason']:
        raise SystemExit(1)


def main():
    p = argparse.ArgumentParser(description=__doc__); s = p.add_subparsers(dest='command', required=True)
    run = s.add_parser('run'); run.add_argument('--out', required=True)
    run.add_argument('--topic'); run.add_argument('--audience'); run.add_argument('--goal')
    run.add_argument('--scope', default='Public sources only; a bounded English introductory briefing')
    run.add_argument('--requirements', help='Frozen audience requirements JSON, prepared before discovery'); run.add_argument('--quota-proof'); run.add_argument('--ledger'); run.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    run.add_argument('--reading-context',action='store_true',help='Preserve source context in code and draft fixed section groups')
    demo = s.add_parser('demo'); demo.add_argument('--out', required=True)
    e = s.add_parser('edit'); e.add_argument('--folder', required=True); e.add_argument('--parent', required=True)
    e.add_argument('--operations', required=True); e.add_argument('--out', required=True); e.add_argument('--ledger')
    e.add_argument('--phase', choices=['experiments', 'validation'], default='experiments')
    saved = s.add_parser('continue-sources', help='Fresh analysis/draft/verification from completed public source snapshots')
    saved.add_argument('--out', required=True); saved.add_argument('--pack', required=True)
    saved.add_argument('--reading-status', required=True); saved.add_argument('--ledger', required=True)
    saved.add_argument('--reading-context', action='store_true', help='Use scoped selection with code-preserved reading context')
    saved.add_argument('--follow-gaps', action='store_true', help='Automatically search original unresolved requirements before drafting')
    saved.add_argument('--quota-proof')
    refine=s.add_parser('refine-result',help='Refine an unresolved original axis using a novel saved-source view')
    refine.add_argument('--out',required=True);refine.add_argument('--parent',required=True)
    refine.add_argument('--facet',required=True);refine.add_argument('--producer-snapshot',required=True)
    refine.add_argument('--ledger',required=True)
    live = s.add_parser('live', help='Matn v2 path (live preset): code shortlist, one selection call, code writer')
    live.add_argument('--out', required=True); live.add_argument('--topic'); live.add_argument('--audience')
    live.add_argument('--goal'); live.add_argument('--scope', default='Public sources only; a bounded English introductory briefing')
    live.add_argument('--preset', default=str(Path(__file__).with_name('live_preset.json')))
    live.add_argument('--plan', help='Owner-edited plan JSON from --plan-only'); live.add_argument('--plan-only', action='store_true')
    live.add_argument('--ledger', required=True); live.add_argument('--timeout', type=int, default=1200)
    live.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    deck = s.add_parser('deck', help='Verifiable deck from a saved result (deck v2, docs/deck-v2.md; zero model calls)')
    deck.add_argument('folder'); deck.add_argument('--template'); deck.add_argument('--out')
    deck.add_argument('--fonts', default='office', choices=('template', 'office')); deck.add_argument('--pdf', action='store_true')
    for command in (run, saved, refine):
        command.add_argument('--legacy-context', action='store_true',
            help='Compatibility fallback: legacy subject binding instead of the local context display contract')
    a = p.parse_args()
    if a.command in ('run', 'continue-sources', 'refine-result'):
        display_policy(legacy=a.legacy_context)
    if a.command == 'live':
        live_main(a); return
    if a.command == 'deck':
        from matn_deck.__main__ import main as deck_main
        argv = ['from-result', a.folder, '--fonts', a.fonts] + (['--template', a.template] if a.template else [])
        argv += ([] if a.pdf else ['--no-pdf']) + (['--out', a.out] if a.out else [])
        raise SystemExit(deck_main(argv))
    if a.command == 'refine-result':
        refinement_worker(a.out,a.parent,a.facet,a.producer_snapshot,a.ledger);return
    if a.command == 'continue-sources':
        saved_worker(a.out, a.pack, a.reading_status, a.ledger, reading_context=a.reading_context, follow_gaps=a.follow_gaps, proof=a.quota_proof)
        return
    if a.command == 'demo':
        from eval.research.fixtures import demo as run_demo
        run_demo(a.out); return
    if a.command == 'edit':
        parent = json.loads(Path(a.parent).read_bytes()); operations = json.loads(Path(a.operations).read_bytes())
        result = edit(a.folder, parent, operations, a.ledger, a.phase)
        save_version(Path(a.folder) / 'versions', result); write(a.out, result)
        publish(a.folder, result, name=Path(a.out).stem + '.html'); return
    folder = Path(a.out); folder.mkdir(parents=True, exist_ok=True)
    request_path = folder / 'request.json'
    if a.topic:
        brief = Brief(topic=a.topic, audience=a.audience, goal=a.goal, scope=a.scope, public_topic=True).model_dump()
        if request_path.exists() and json.loads(request_path.read_bytes()) != brief:
            raise ValueError('NEW_BRIEF_REQUIRES_NEW_OUTPUT_FOLDER')
        write(request_path, brief)
    else:
        brief = json.loads(request_path.read_bytes())
    load_settings()
    eligibility = qualify(a.quota_proof); write(folder / 'provider-qualification.json', eligibility)
    if not eligibility['key_present']:
        result = dict(status='BLOCKED', stage='live_discovery', reasons=eligibility['reasons'],
                      generation=0, native=0, live_search=0, sources_read=0,
                      first_loss='provider_qualification', full_journey_accepted=False)
        write(folder / 'outcome.json', result); publish(folder)
        print(json.dumps(dict(result, preview=str((folder / 'index.html').resolve())))); return
    ledger = Path(a.ledger) if a.ledger else folder / 'measurement'
    if a.worker:
        requirements = json.loads(Path(a.requirements).read_bytes()) if a.requirements else None
        worker(folder, brief, ledger, a.quota_proof, requirements, a.reading_context); return
    if not (ledger / 'ledger.json').exists():
        open_ledger(ledger, experiment=3000, validation=1500, closure=900)
    command = [sys.executable, '-m', 'matn_research', 'run', '--out', str(folder), '--ledger', str(ledger), '--worker']
    if a.legacy_context:command += ['--legacy-context']
    if a.reading_context:command += ['--reading-context']
    if a.requirements:
        command += ['--requirements', a.requirements]
    if a.quota_proof:
        command += ['--quota-proof', a.quota_proof]
    row = supervise(ledger, 'experiments', command)
    if row['returncode'] or row['stop_reason']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()

"""Offline-sized stage ceilings; reject rather than truncate or silently pack."""
import json

# See reports/topic-analysis-repair.md and offline measurements. Input includes
# schema plus 256 framing reserve (estimate, not server prompt_eval_count).
STAGES = dict(plan=dict(input=1536, output=512, context=2048),
              facet=dict(input=2560, output=768, context=3328),
              draft=dict(input=5888, output=1152, context=7040))
FRAMING = 256
# Requirement-first view sizes tried (min, max, step) in characters. The token
# ceiling above stays authoritative; the old fixed view was 2600 characters.
VIEW_CHARACTERS = (2600, 9000, 400)


def budget(prompt, schema, counter, stage, representative=None):
    limits = STAGES[stage]
    measured = dict(prompt=counter(prompt), schema=counter(json.dumps(schema)))
    measured['input_with_framing'] = measured['prompt'] + measured['schema'] + FRAMING
    if measured['input_with_framing'] > limits['input']:
        raise ValueError('RESEARCH_INPUT_BUDGET:' + stage)
    fixture = None if representative is None else counter(json.dumps(representative))
    # 25% shape headroom. This is a planning estimate, never a quality prediction.
    if fixture is not None and (fixture * 5 + 3) // 4 > limits['output']:
        raise ValueError('RESEARCH_OUTPUT_BUDGET:' + stage)
    return dict(stage=stage, measured=measured, limits=limits, framing_estimate=FRAMING,
                representative_tokens=fixture, output_headroom_ratio=1.25)


def journey_schedule(task, reg, wire, counter, *, generation_cap, completed_calls=1,
                     facet_ids=None, reserve_gap=False, exploration_offset=0, whole_segments=False, local_slots=False, draft_calls=1, cached_analysis_calls=0, cached_draft_calls=0, rankings=None):
    if local_slots == 'requirements':
        from .requirement_selection import schedule
        return schedule(task, reg, wire, counter, generation_cap=generation_cap,completed_calls=completed_calls,
            facet_ids=facet_ids,reserve_gap=reserve_gap,exploration_offset=exploration_offset,draft_calls=draft_calls,
            cached_analysis_calls=cached_analysis_calls,cached_draft_calls=cached_draft_calls,rankings=rankings)
    # Low-level calculator retains its no-followup default for existing callers.
    # The public initial journey always passes reserve_gap=True.
    from .facets import IDAnalysis, facet_specs, prompt_for, representative, bundle_representative, evidence_view, requirement_view, selection_schema
    specs = [f for f in facet_specs(task) if facet_ids is None or f['id'] in facet_ids]
    batches = []; pending = []; views = {}; audits = {}
    multi = task.get('research_selection_mode') == 'bounded-multiple-v1'
    for i, spec in enumerate(specs):
        if local_slots == 'bundle':
            # Requirement-first: the largest view whose single-facet call still
            # fits the unchanged facet input ceiling (STAGES['facet']['input']).
            for size in range(VIEW_CHARACTERS[1], VIEW_CHARACTERS[0] - 1, -VIEW_CHARACTERS[2]):
                view, audit = requirement_view([spec], wire, max_characters=size, exploration_offset=exploration_offset)
                probe = dict(view, bounded_view=True, projection='whole-context-v1',
                             facet_supports={spec['id']: [s['handle'] for s in view['sources']]})
                try:
                    budget(prompt_for(task, [spec], probe, local_slots=local_slots),
                           selection_schema([spec], probe, local_slots=local_slots), counter, 'facet',
                           bundle_representative([spec], probe))
                except ValueError:
                    continue
                audit[spec['id']]['max_characters'] = size; break
        else:
            view, audit = evidence_view([spec], wire, exploration_offset=exploration_offset+i)
        views[spec['id']] = view; audits.update(audit)
    def union(fs):
        keys = {s['handle'] for f in fs for s in views[f['id']]['sources']}
        sources = [s for s in wire['sources'] if s['handle'] in keys]
        ids = {k for s in sources for k in [s['support_segment'], *s['context']]}
        return dict(sources=sources, segments=[s for s in wire['segments'] if s['id'] in ids], bounded_view=True,
                    **(dict(projection='whole-context-v1') if local_slots == 'bundle' else {}),
                    facet_supports={f['id']: [s['handle'] for s in views[f['id']]['sources']] for f in fs})
    def cost(fs):
        shape = bundle_representative(fs, union(fs)) if local_slots == 'bundle' else representative(fs, reg, multi=multi)
        return budget(prompt_for(task, fs, union(fs), whole_segments=whole_segments, local_slots=local_slots), selection_schema(fs, union(fs), whole_segments=whole_segments, local_slots=local_slots), counter,
                      'facet', shape)
    def batch(fs): return dict(facets=fs, wire=union(fs), budget=cost(fs))
    for spec in specs:
        try: cost([*pending, spec])
        except ValueError:
            if not pending: raise
            batches.append(batch(pending)); pending = [spec]; cost(pending)
        else: pending.append(spec)
    if pending: batches.append(batch(pending))
    # Reserve a REAL future analysis request and draft before spending anything.
    if not 0 <= cached_analysis_calls <= len(batches) or not 0 <= cached_draft_calls <= draft_calls:
        raise ValueError('INVALID_COMPLETED_JOURNEY_COUNTS')
    new_analysis = len(batches)-cached_analysis_calls
    new_draft = draft_calls-cached_draft_calls
    minimum = completed_calls + new_analysis + new_draft
    required = minimum + int(reserve_gap)
    if required > generation_cap:
        raise ValueError(f'FULL_JOURNEY_GENERATION_BUDGET:required={required},cap={generation_cap},analysis={len(batches)},gap={int(reserve_gap)},draft={draft_calls}')
    total_caps = {key: new_draft*STAGES['draft'][key] + (new_analysis+int(reserve_gap))*STAGES['facet'][key]
                  for key in ('input', 'output')}
    return dict(batches=batches, facet_views=audits, generation_minimum=minimum,
                generation_required_with_gap=required, generation_cap=generation_cap,
                generation_token_ceiling=total_caps,
                generation_attempt_wall_upper_seconds=required*420,
                native_edit_inclusive_call_cap=64, native_attempt_wall_upper_seconds=64*180,
                stages=dict(planning=dict(method='explicit requirements: deterministic queries; otherwise one model call', completed_calls=completed_calls),
                    analysis=dict(calls=len(batches),cached_calls=cached_analysis_calls,new_reserved_calls=new_analysis), gap_followup=dict(reserved_calls=int(reserve_gap)),
                    draft=dict(reserved_calls=draft_calls,cached_calls=cached_draft_calls,new_reserved_calls=new_draft), native=dict(base_roles_upper=28, operator_assay_call_allowance=28, total_before_edit_cap=56),
                    edit=dict(native_reserved=8, generation=0), cleanup=dict(included_per_generation_attempt=45),
                    validation=dict(reserved_phase_seconds=1500), closure=dict(reserved_phase_seconds=900)),
                estimates=dict(latency_seconds=None, native_latency_seconds=None,
                    assumptions='No measured analysis/native throughput, KV cache or residency assumption. Token counts measure size only. Native roles checked again on concrete draft; exact scored pairs may reduce actual cost.',
                    experiment_phase_seconds=3000, fit='unknown; admission against active supervisor deadline required for every attempt'),
                wall_interpretation='Sum of ceilings is not a latency estimate or proof of phase fit. Search/fetch and CPU overhead remain unknown.',
                followup_batch_allowance=generation_cap-minimum,
                note='No automatic retry. Reserve one gap call initially; expanded followup must fit remaining calls or refuse before generation.')

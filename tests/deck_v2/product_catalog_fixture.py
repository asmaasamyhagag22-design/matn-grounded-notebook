"""Synthetic structural QA only; none of these numbers are real findings."""
from dataclasses import replace
from .catalog_fixture import make_catalog,unit
from matn_deck.catalog import Axis,Gap
from matn_deck.numeric import facts_for_unit


def make_product_catalog(folder=None):
    base=make_catalog(folder,with_figure=folder is not None)
    units=(*base.units,unit('U10','a6','Managers should review deployment risks before launch.'),
           unit('U11','a1','Agencies should document the service processes before redesign.'),
           unit('U12','a1','Teams should publish service eligibility criteria before launch.'))
    units=tuple(replace(u,source_type='commercial-vendor') for u in units)
    sources=tuple(replace(s,type='commercial-vendor',url='https://example.com/'+s.id) for s in base.sources)
    plan=replace(base.plan,topic='Synthetic layout QA — source-linked briefing',axes=(*base.plan.axes,Axis('a6','Deployment readiness')))
    return replace(base,plan=plan,units=units,sources=sources,numbers=tuple(f for u in units for f in facts_for_unit(u)),
        gaps=(*base.gaps,Gap('a1','a1','Queue practices',('Accessibility coverage is missing.',))),
        origin=dict(adapter='synthetic-layout-QA',fake=True,
            axis_coverage=dict(a1='part',a2='full',a3='full',a4='none',a5='full',a6='full'),
            searches_by_axis=dict(a1=['public service queue practices accessibility'],a4=['public service funding sources']))).validate()

"""New product compositions preserve verified text, source scope and old galleries."""
from dataclasses import replace
import hashlib,json
from pathlib import Path
from matn_deck.storyboard_v2 import build_storyboard,Controls
from matn_deck.deck_qa import storyboard_fidelity
from matn_deck.product_storyboard import balanced_groups,gap_rows
from .product_catalog_fixture import make_product_catalog


def test_product_titles_are_axes_and_groups_do_not_make_a_four_plus_one_split():
    c=make_product_catalog();story=build_storyboard(c,lambda _:True,Controls(),template='midnight|fonts=template')
    assert [len(g) for g in balanced_groups(list(range(5)))]==[3,2]
    assert all(s.title.kind=='axis' and not s.title.marker for s in story.slides if s.kind=='assertion')
    assert {b.unit_id for s in story.slides for b in s.bullets}=={u.id for u in c.units}
    assert storyboard_fidelity(story,c)==[]
    compositions={s.composition for s in story.slides}
    assert {'quote','grouped','comparison','timeline','key_number','section','closing','visual_agenda'}<=compositions


def test_gap_slide_never_lists_complete_axes_or_raw_internal_success_criteria():
    c=make_product_catalog();rows=gap_rows(c)
    assert set(rows)=={'a1','a4'} and 'Searched' not in rows['a1']['reason']
    story=build_storyboard(c,lambda _:True,template='ministry_light')
    gap=next(s for s in story.slides if s.kind=='gaps')
    assert {t.ref for t in gap.lines if t.kind=='axis'}=={'a1','a4'}
    assert not any(t.kind=='requirement' for t in gap.lines)
    assert any(t.text=='Searched: public service funding sources' for t in gap.lines)


def test_timeline_uses_unit_dates_never_access_dates():
    c=make_product_catalog();story=build_storyboard(c,lambda _:True,template='editorial')
    line=next(s for s in story.slides if s.composition=='timeline')
    assert [t.text for t in line.item_titles]==['2022','2024']
    assert '2026-10-28' not in [t.text for t in line.item_titles]
    assert all(b.text.text==c.unit(b.unit_id).text for b in line.bullets)


def test_icons_are_pinned_upstream_assets_with_actual_mit_license():
    root=Path(__file__).resolve().parents[2]/'design/icons/heroicons'
    manifest=json.loads((root/'provenance.json').read_bytes())
    assert manifest['license']=='MIT' and 'Permission is hereby granted' in (root/'LICENSE').read_text()
    for row in manifest['files']:assert hashlib.sha256((root/row['file']).read_bytes()).hexdigest()==row['sha256']
    rasters=json.loads((root/'raster-provenance.json').read_bytes())
    assert len(rasters['icons'])==12
    for row in rasters['icons']:assert hashlib.sha256((root/(row['name']+'.png')).read_bytes()).hexdigest()==row['png_sha256']


def test_qualified_number_statement_fits_without_dropping_its_conditions(tmp_path):
    from .catalog_fixture import unit
    from matn_deck.numeric import facts_for_unit
    from matn_deck.deck_v2 import build_deck
    from matn_deck.product_templates import product_template
    c=make_product_catalog()
    statement=("In this fictional layout test, 30% of offices offered online appointments during the review period, "
               "while the remaining offices retained scheduled visits, subject to local staffing arrangements, "
               "published opening hours, accessibility requirements and the availability of trained support teams.")
    units=tuple(unit('U4','a2',statement) if u.id=='U4' else u for u in c.units)
    c=replace(c,units=units,numbers=tuple(n for u in units for n in facts_for_unit(u)))
    built=build_deck(c,product_template(),tmp_path,fonts='template')
    assert not built.report.overflows
    from pptx import Presentation
    text='\n'.join(s.text for slide in Presentation(built.pptx).slides for s in slide.shapes if s.has_text_frame)
    assert statement in text

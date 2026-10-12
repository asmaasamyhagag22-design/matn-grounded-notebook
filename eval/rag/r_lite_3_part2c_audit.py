"""Precommitted blind owner-audit draw; no owner-label reading or scoring."""
import csv
import hashlib
import json
from pathlib import Path
import random

ROOT = Path('out/r-lite-3/part2c')
WEF = 'wef-future-of-jobs-2025'


def load(path):
    return json.loads(Path(path).read_text())


def draw(mapping, agreement, safety, config):
    rows = mapping['sources'][WEF]
    retyped = {r['block_id'] for r in rows if r['retyped']}
    seeded = {b for r in agreement['checks']['eval/rag/wef-table-visual-annotations.json']['rows']
              for b in r['retyped_block_ids']}
    cells = set(safety['available_original_table_block_ids'])
    preserved = {r['block_id'] for r in rows if not r['retyped']}
    pool = retyped - seeded - cells
    first = set(random.Random(config['sample_seed']).sample(sorted(pool), config['sample_size']))
    groups = [first, preserved, cells]
    entries = [{'block_id': b, 'group': i + 1} for i, group in enumerate(groups) for b in sorted(group)]
    random.Random(config['shuffle_seed']).shuffle(entries)
    for i, entry in enumerate(entries, 1):
        entry['item'] = i
    overlap = sorted(seeded & cells)
    assert len(entries) == len({e['block_id'] for e in entries}), 'AUDIT_GROUP_OVERLAP'
    return entries, {'retyped': len(retyped), 'retyped_seeded': len(seeded), 'index45_cells': len(cells),
                     'seeded_cells_overlap_ids': overlap, 'seeded_outside_retyped': sorted(seeded-retyped),
                     'cells_outside_retyped': sorted(cells-retyped), 'pool_size': len(pool),
                     'pool_ids': sorted(pool), 'group_counts': [len(g) for g in groups],
                     'unique_total': len(entries), 'sample_seed': config['sample_seed'],
                     'shuffle_seed': config['shuffle_seed'], 'drawn_group1_ids': sorted(first)}


def main():
    cfg = load('eval/rag/r_lite_3_part2c_sampling.json')
    entries, stats = draw(load('out/r-lite-3/part2b/mapping.json'),
                          load('out/r-lite-3/part2b/agreement.json'),
                          load('out/r-lite-3/part2b/table-number-safety.json'), cfg)
    assert stats['pool_size'] == 194 and stats['group_counts'] == [30, 11, 9]
    pdf_path = Path(cfg['pdf'])
    assert hashlib.sha256(pdf_path.read_bytes()).hexdigest() == cfg['sha256'], 'PDF_SHA_MISMATCH'
    # The PDF is opened directly, read-only, only after the SHA check.
    import pypdfium2 as pdfium
    doc = load('out/rag-core/section-rebuild/' + WEF + '/05_document.json')
    blocks = {e['block']['block_id']: e['block'] for e in doc['elements']}
    folder = ROOT / 'audit'
    folder.mkdir(parents=True, exist_ok=True)
    manifest = []
    with pdfium.PdfDocument(str(pdf_path)) as pdf:
        for entry in entries:
            block = blocks[entry['block_id']]
            page = pdf[block['page_index']]
            bitmap = page.render(scale=cfg['render_scale_px_per_pt'])
            im = bitmap.to_pil().convert('RGB')
            scale = cfg['render_scale_px_per_pt']
            x0, y0, x1, y1 = block['bbox']
            pixel = (max(0, int(x0*scale)), max(0, int(y0*scale)),
                     min(im.width, int(x1*scale+1)), min(im.height, int(y1*scale+1)))
            path = folder / f"item-{entry['item']:02d}.png"
            im.crop(pixel).save(path)
            im.close(); bitmap.close(); page.close()
            entry['pdf_page_index'] = block['page_index']
            manifest.append({'item': entry['item'], 'block_id': entry['block_id'],
                             'pdf_page_index': block['page_index'], 'bbox': block['bbox'],
                             'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                             'source_sha256': cfg['sha256'], 'scale_px_per_pt': scale})
    # Item names, page indices and pixels alone: no decision/group/cell status/IDs in HTML or asset names.
    html = '<!doctype html><html lang="en"><meta charset="utf-8"><title>Owner audit</title>'
    html += '<style>body{max-width:1100px;margin:24px auto;font:16px sans-serif}article{margin:32px 0;break-inside:avoid}img{max-width:100%;border:1px solid #aaa}</style>'
    for entry in entries:
        html += f'<article><p>Item {entry["item"]} · PDF page index {entry["pdf_page_index"]}</p><img alt="Item {entry["item"]}" src="item-{entry["item"]:02d}.png"></article>'
    html += '</html>\n'
    (folder / 'index.html').write_text(html)
    csv_path = Path('eval/rag/owner-audit-20261013.csv')
    if csv_path.exists():
        existing = list(csv.DictReader(csv_path.open()))
        assert len(existing) == len(entries) and all(not r['label'] and not r['note'] for r in existing), 'OWNER_LABELS_EXIST_STOP'
    with csv_path.open('w', newline='') as stream:
        writer = csv.writer(stream, lineterminator='\n'); writer.writerow(['item', 'label', 'note'])
        writer.writerows((e['item'], '', '') for e in entries)
    for name, data in [('audit-private-mapping.json', entries), ('audit-draw.json', stats), ('audit-crops-manifest.json', manifest)]:
        (ROOT / name).write_text(json.dumps(data, sort_keys=True, indent=2)+'\n')
    print(json.dumps(stats | {'pool_ids': 'see audit-draw.json', 'drawn_group1_ids': 'see audit-draw.json'}))


if __name__ == '__main__':
    main()

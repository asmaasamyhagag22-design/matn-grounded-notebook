"""Generate only the committed sample, with original scan crops and no visible strata."""
import json
import base64
import subprocess
from PIL import Image, ImageDraw
from .review import HERE, make_proposals
from .sample import INITIAL, GAO, blind_payload, manifests, validate_records
from .verify import require_verified


def render_sample_html(payloads):
    data = json.dumps(payloads, ensure_ascii=False).replace('<', '\\u003c')
    return (HERE / 'sample_ui.html').read_text(encoding='utf8').replace('__SAMPLE_DATA__', data)


def embedded_assets(assets, folder=HERE):
    """Keep the local review portable; PNG bytes remain identical to verified crop assets."""
    return {item_id: {key: 'data:image/png;base64,' + base64.b64encode((folder / path).read_bytes()).decode('ascii')
                      for key, path in files.items()} for item_id, files in assets.items()}


def require_committed(path):
    repo = HERE.parents[2]
    relative = path.relative_to(repo).as_posix()
    committed = subprocess.run(['git', 'show', 'HEAD:' + relative], cwd=repo, capture_output=True)
    if committed.returncode or json.loads(committed.stdout.decode('utf8')) != json.loads(path.read_text(encoding='utf8')):
        raise ValueError('Commit this frozen sample before generating the review page: ' + relative)


def generate():
    from eval.reading.closeout import OUT
    payloads = []
    for manifest in manifests():
        require_committed(GAO if manifest['batch'] == 'gao' else INITIAL)
        validate_records(manifest, OUT / 'final/real')
        for doc in manifest['sources']:
            require_verified(doc)
        assets = {}
        for page in sorted({i['page'] for i in manifest['items']}):
            record = json.loads((OUT / 'final/real' / (page + '.json')).read_text(encoding='utf8'))
            with Image.open(HERE / 'review_assets' / (page + '.png')) as image:
                lines = {line['index']: line for line in record['lines']}
                def original_line(token):
                    line = lines[token['line']]
                    return make_proposals([{'token': '', 'bbox': line['bbox'], 'flagged': False}], [],
                                          record['preprocess']['rotation_deg'], image.size, record['cropbox'])[0]['bbox']
                def crop(box, margin, name, outline=False):
                    scale = 300 / 72; ox, oy = record['cropbox'][:2]
                    x0, y0, x1, y1 = box
                    b = (max(0, int((x0 - ox) * scale) - margin), max(0, int((y0 - oy) * scale) - margin),
                         min(image.width, int((x1 - ox) * scale) + margin), min(image.height, int((y1 - oy) * scale) + margin))
                    if b[0] >= b[2] or b[1] >= b[3]:
                        raise ValueError('Invalid original scan crop: ' + name)
                    cropped = image.crop(b)
                    if outline:
                        cropped = cropped.convert('RGB')
                        target = ((x0 - ox) * scale - b[0] - 3, (y0 - oy) * scale - b[1] - 3,
                                  (x1 - ox) * scale - b[0] + 3, (y1 - oy) * scale - b[1] + 3)
                        ImageDraw.Draw(cropped).rectangle(target, outline='#007aaf', width=2)
                    cropped.save(HERE / 'review_assets' / name)
                    return 'review_assets/' + name
                for item in [i for i in manifest['items'] if i['page'] == page]:
                    name = f"sample_{page}_t{item['token_index']:04d}"
                    assets[item['id']] = {'crop': crop(item['bbox'], 25, name + '.png', outline=True),
                                          'context_crop': crop(original_line(record['tokens'][item['token_index']]), 35, name + '_line.png')}
        payloads.append(blind_payload(manifest, embedded_assets(assets)))
    (HERE / 'review.html').write_text(render_sample_html(payloads), encoding='utf8')
    print(f"Sample review: {HERE / 'review.html'}; {sum(len(b['items']) for b in payloads)} items; GT untouched")


if __name__ == '__main__':
    generate()

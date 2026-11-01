"""Explicit copy migration: original checkpoint bindings and bytes stay unchanged."""
import json
from pathlib import Path
import shutil
from .readiness import binding, load_ready, load_page, lock, write, sha


def migrate(pdf, source, output):
    source=Path(source).resolve();output=Path(output).resolve()
    if output.exists():raise ValueError('MIGRATION_OUTPUT_MUST_BE_NEW')
    with lock(source/'prepare.lock'):
        raw=(source/'progress.json').read_bytes();state=json.loads(raw);old=state['binding']
        current=binding(pdf)
        legacy=json.loads(Path(__file__).with_name('legacy-preparation-v1.json').read_bytes())
        if old.get('version')=='pdf-chat-readiness-v1':
            if {k:v for k,v in old.items() if k!='doc_id'}!=legacy:raise ValueError('MIGRATION_UNKNOWN_PRODUCER')
        elif old.get('version')=='pdf-chat-readiness-v2':
            stages=('reader','ocr_glm_digest','checkpoint_schema','orchestration')
            if any(old.get(k)!=current.get(k) for k in stages):raise ValueError('MIGRATION_UNKNOWN_READING_PRODUCER')
        else:raise ValueError('MIGRATION_UNKNOWN_PRODUCER')
        if old['doc_id']!=current['doc_id'] or old['reader']!=current['reader'] or old['ocr_glm_digest']!=current['ocr_glm_digest']:
            raise ValueError('MIGRATION_READING_IDENTITY')
        hashes={}
        for folder in ('pages','ocr'):
            for path in sorted((source/folder).glob('*.json.gz')):
                value=load_page(path)
                if value['page_index']!=int(path.name.split('.')[0]):raise ValueError('MIGRATION_PAGE_ID')
                hashes[str(path.relative_to(source))]=sha(path.read_bytes())
        receipt=load_ready(source/'ready.json') if (source/'ready.json').exists() else None
        output.mkdir(parents=True)
        for folder in ('pages','ocr','glm-cache'):
            if (source/folder).exists():shutil.copytree(source/folder,output/folder)
        for name in ('digital.json.gz','embedding-cache.db'):
            if (source/name).exists():shutil.copy2(source/name,output/name)
        # The new orchestration adopts unchanged extraction/OCR outputs, whose
        # actual producing identity is retained explicitly, never relabelled.
        state['binding']=current
        state['status']='adopted_reading_checkpoints'
        state['derived_from']=dict(path=str(source),progress_sha256=sha(raw),producer_binding=old,
            unchanged_checkpoints=hashes,policy='explicit-v1-to-v2-adoption')
        write(output/'progress.json',state)
        write(output/'migration.json',state['derived_from'])
        if receipt:
            # Index/structure output is never relabelled under a new pipeline.
            # Re-publish from adopted reading outputs using the current producer.
            write(output/'previous-publication.json',receipt)
    return output

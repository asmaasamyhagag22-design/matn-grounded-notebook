"""Separate v1 snapshots: existing public schemas remain frozen."""
import json
import re
from pathlib import Path
from . import structure

NAMES=('BBoxRef','BlockSpan','PrimarySpan','RepeatedContextSpan','OffsetSpan','SentenceSpan','NumberTokenRef','StructureIssue','Element','PageGeometry','Section','TableCell','Table','Chunk','DocumentStructure','OfflineRunManifest')

def render_schema_files():
    result={}
    for name in NAMES:
        stem='bbox-ref' if name=='BBoxRef' else re.sub(r'(?<!^)(?=[A-Z])','-',name).lower()
        result[stem+'.schema.json']=json.dumps(getattr(structure,name).model_json_schema(),ensure_ascii=False,sort_keys=True,indent=2)+'\n'
    return result

if __name__=='__main__':
    folder=Path(__file__).resolve().parents[1]/'schemas/contracts/structure'
    folder.mkdir(parents=True,exist_ok=True)
    for name,text in render_schema_files().items(): (folder/name).write_text(text)

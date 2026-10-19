"""Offline GGUF vocabulary tokenizer in the existing isolated tokenizers runtime.

Reads metadata only, never loads model tensors. JSON lines in/out, no downloads.
"""
import json
import struct
import sys
from tokenizers import Tokenizer, Regex, pre_tokenizers, normalizers
from tokenizers.models import BPE

MODEL='/usr/share/ollama/.ollama/models/blobs/sha256-02d45dc1cf451ba2475ac33b301c2dd8f985abe4c182ce04a1f2f5bf0260278d'


def metadata(path):
    with open(path,'rb') as f:
        def unpack(fmt):return struct.unpack('<'+fmt,f.read(struct.calcsize('<'+fmt)))[0]
        def string():return f.read(unpack('Q')).decode('utf-8')
        def value(kind):
            if kind==8:return string()
            if kind==9:
                element=unpack('I');return [value(element) for _ in range(unpack('Q'))]
            return unpack({0:'B',1:'b',2:'H',3:'h',4:'I',5:'i',6:'f',7:'?',10:'Q',11:'q',12:'d'}[kind])
        assert f.read(4)==b'GGUF';assert unpack('I') in (2,3)
        unpack('Q');count=unpack('Q');rows={}
        for _ in range(count):
            key=string();v=value(unpack('I'))
            if key.startswith('tokenizer.'):rows[key]=v
        return rows


def tokenizer():
    meta=metadata(MODEL)
    assert meta['tokenizer.ggml.model']=='gpt2'
    # Qwen pretokenizer from the locally installed official transformers Qwen3.5 tokenizer.
    # Same expression as the installed official module; avoid importing its ML runtime.
    PRETOKENIZE_REGEX = r"""(?i:'s|'t|'re|'ve|'m|'ll|'d)|[^\r\n\p{L}\p{N}]?[\p{L}\p{M}]+|\p{N}| ?[^\s\p{L}\p{M}\p{N}]+[\r\n]*|\s*[\r\n]+|\s+(?!\S)|\s+"""
    t=Tokenizer(BPE(vocab={s:i for i,s in enumerate(meta['tokenizer.ggml.tokens'])},
                    merges=[tuple(m.split(' ',1)) for m in meta['tokenizer.ggml.merges']]))
    t.normalizer=normalizers.NFC()
    t.pre_tokenizer=pre_tokenizers.Sequence([pre_tokenizers.Split(Regex(PRETOKENIZE_REGEX),behavior='isolated'),
                                           pre_tokenizers.ByteLevel(add_prefix_space=False,use_regex=False)])
    return t,meta


if __name__=='__main__':
    t,meta=tokenizer()
    print(json.dumps({'ready':True,'pre':meta.get('tokenizer.ggml.pre'),'vocab':t.get_vocab_size()}),flush=True)
    for line in sys.stdin:
        prompt=json.loads(line)
        print(json.dumps({'tokens':len(t.encode(prompt).ids)}),flush=True)

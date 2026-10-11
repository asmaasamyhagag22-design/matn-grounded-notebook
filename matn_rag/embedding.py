"""Pinned local embeddings; deterministic batches, float32 normalized vectors."""
import math
import struct
from .transport import LoopbackTransport

MODEL = 'qwen3-embedding:0.6b'
DIGEST = 'ac6da0dfba84a81fdbfbaf330198c33cd77c4cdfc53e8bc50eb581914a15621d'
DIMENSION = 1024
NUM_CTX = 32768
BATCH_SIZE = 8
DOC_INPUT_VERSION = 'doc-input-v1'
QUERY_INPUT_VERSION = 'q-instr-v1'


def query_input(question):
    return 'Instruct: Given a question, retrieve passages from the uploaded documents that answer the question\nQuery: ' + question


def normalized(vector):
    if len(vector) != DIMENSION or any(not math.isfinite(v) for v in vector):
        raise ValueError('INVALID_VECTOR')
    norm = math.sqrt(math.fsum(v*v for v in vector))
    if not norm:
        raise ValueError('ZERO_VECTOR')
    return list(struct.unpack('<'+'f'*DIMENSION, struct.pack('<'+'f'*DIMENSION, *(v/norm for v in vector))))


class Embedder:
    def __init__(self, transport=None):
        self.transport = transport or LoopbackTransport()

    def check_digest(self):
        models = self.transport.request('/api/tags')['models']
        if not any(m['name'] == MODEL and m['digest'] == DIGEST for m in models):
            raise ValueError('EMBEDDING_DIGEST_MISMATCH')

    def embed(self, texts, num_ctx=NUM_CTX):
        self.check_digest()
        result = []
        for start in range(0, len(texts), BATCH_SIZE):
            batch = texts[start:start+BATCH_SIZE]
            response = self.transport.request('/api/embed', {'model': MODEL, 'input': batch,
                'truncate': False, 'options': {'num_ctx': num_ctx}})
            vectors = response.get('embeddings', [])
            if len(vectors) != len(batch):
                raise ValueError('VECTOR_COUNT_MISMATCH')
            result.extend(normalized(v) for v in vectors)
        return result

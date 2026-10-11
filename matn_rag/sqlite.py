"""Transactional laptop repository with cache references and canonical logical export."""
import hashlib
import json
import sqlite3
from collections import Counter
from .contracts import INDEX_VERSION, canonical
from .tokenizer import VERSION, tokenize

TABLES = ('notebooks', 'sources', 'chunks', 'inputs', 'postings', 'stats', 'embeddings', 'refs')


def identity(*parts):
    return hashlib.sha256(canonical(parts)).hexdigest()


class SQLiteRepository:
    def __init__(self, path=':memory:'):
        self.db = sqlite3.connect(str(path))
        self.db.row_factory = sqlite3.Row
        self.revision = 0
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS notebooks (id TEXT PRIMARY KEY);
        CREATE TABLE IF NOT EXISTS sources (id TEXT PRIMARY KEY, notebook TEXT REFERENCES notebooks(id) ON DELETE CASCADE,
          doc_id TEXT NOT NULL, metadata TEXT NOT NULL, UNIQUE(notebook,doc_id));
        CREATE TABLE IF NOT EXISTS chunks (source TEXT REFERENCES sources(id) ON DELETE CASCADE, id TEXT, payload TEXT,
          PRIMARY KEY(source,id));
        CREATE TABLE IF NOT EXISTS inputs (source TEXT, chunk TEXT, variant TEXT, text TEXT, dl INTEGER,
          PRIMARY KEY(source,chunk,variant), FOREIGN KEY(source,chunk) REFERENCES chunks(source,id) ON DELETE CASCADE);
        CREATE TABLE IF NOT EXISTS postings (source TEXT, chunk TEXT, variant TEXT, term TEXT, position INTEGER,
          PRIMARY KEY(source,chunk,variant,term,position), FOREIGN KEY(source,chunk,variant) REFERENCES inputs(source,chunk,variant) ON DELETE CASCADE);
        CREATE TABLE IF NOT EXISTS stats (source TEXT REFERENCES sources(id) ON DELETE CASCADE, variant TEXT, term TEXT, df INTEGER,
          PRIMARY KEY(source,variant,term));
        CREATE TABLE IF NOT EXISTS embeddings (key TEXT PRIMARY KEY, digest TEXT, version TEXT, text_sha256 TEXT, vector TEXT,
          UNIQUE(digest,version,text_sha256));
        CREATE TABLE IF NOT EXISTS refs (source TEXT, chunk TEXT, variant TEXT, key TEXT REFERENCES embeddings(key),
          PRIMARY KEY(source,chunk,variant), FOREIGN KEY(source,chunk) REFERENCES chunks(source,id) ON DELETE CASCADE);
        ''')

    def create_notebook(self, notebook):
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO notebooks VALUES (?)', (notebook,))

    def source_ids(self, notebook):
        return [r[0] for r in self.db.execute('SELECT id FROM sources WHERE notebook=? ORDER BY doc_id', (notebook,))]

    def source_rows(self, notebook):
        return [dict(r) for r in self.db.execute('SELECT * FROM sources WHERE notebook=? ORDER BY doc_id', (notebook,))]

    def add_source(self, notebook, doc_id, metadata, chunks):
        if metadata['versions']['tokenizer'] != VERSION or metadata['versions']['index'] != INDEX_VERSION:
            raise ValueError('INDEX_VERSION_MISMATCH')
        found = self.db.execute('SELECT id,metadata FROM sources WHERE notebook=? AND doc_id=?', (notebook,doc_id)).fetchone()
        if found:
            if json.loads(found['metadata']) != metadata:
                raise ValueError('SOURCE_VERSION_OR_FINGERPRINT_MISMATCH')
            return found['id']
        sid = identity(notebook, doc_id)
        with self.db:
            self.db.execute('INSERT INTO sources VALUES (?,?,?,?)', (sid,notebook,doc_id,canonical(metadata).decode()))
            dfs = {v: Counter() for v in ('doc-input-v1','doc-input-no-prefix-v1')}
            for chunk in sorted(chunks, key=lambda c:c['chunk_id']):
                self.db.execute('INSERT INTO chunks VALUES (?,?,?)', (sid,chunk['chunk_id'],canonical(chunk).decode()))
                for variant, text in [('doc-input-v1', chunk['context_prefix']+'\n\n'+chunk['text']), ('doc-input-no-prefix-v1', chunk['text'])]:
                    tokens = tokenize(text)
                    self.db.execute('INSERT INTO inputs VALUES (?,?,?,?,?)', (sid,chunk['chunk_id'],variant,text,len(tokens)))
                    terms = set()
                    for token in tokens:
                        for term in token.terms:
                            self.db.execute('INSERT INTO postings VALUES (?,?,?,?,?)', (sid,chunk['chunk_id'],variant,term,token.position))
                            terms.add(term)
                    dfs[variant].update(terms)
            for variant, df in dfs.items():
                self.db.executemany('INSERT INTO stats VALUES (?,?,?,?)', ((sid,variant,t,n) for t,n in sorted(df.items())))
        self.revision += 1
        return sid

    def validate_selection(self, notebook, selected):
        if not selected or len(set(selected)) != len(selected) or not set(selected) <= set(self.source_ids(notebook)):
            raise ValueError('EMPTY_UNKNOWN_OR_DUPLICATE_SELECTION')
        from .embedding import DIGEST
        for sid in selected:
            metadata=json.loads(self.db.execute('SELECT metadata FROM sources WHERE id=?',(sid,)).fetchone()[0])
            versions=metadata['versions']
            if versions.get('tokenizer')!=VERSION or versions.get('index')!=INDEX_VERSION or ('chunker' in versions and versions['chunker']!='r-lite-2'):
                raise ValueError('STORED_INDEX_VERSION_MISMATCH')
            if 'digest' in metadata and metadata['digest']!=DIGEST:raise ValueError('STORED_DIGEST_MISMATCH')

    def selected_chunks(self, notebook, selected):
        self.validate_selection(notebook,selected)
        result=[]
        for sid in sorted(selected):
            for row in self.db.execute('SELECT payload FROM chunks WHERE source=? ORDER BY id', (sid,)):
                result.append({**json.loads(row['payload']), 'source_id':sid})
        return result

    def source_stats(self, selected, variant):
        result={}
        for sid in sorted(selected):
            r=self.db.execute('SELECT COUNT(*),COALESCE(SUM(dl),0) FROM inputs WHERE source=? AND variant=?',(sid,variant)).fetchone()
            result[sid]={'N':r[0], 'sumdl':r[1], 'df':dict(self.db.execute('SELECT term,df FROM stats WHERE source=? AND variant=? ORDER BY term',(sid,variant)))}
        return result

    def raw_postings(self, selected, variant):
        return [dict(r) for sid in sorted(selected) for r in self.db.execute('SELECT * FROM postings WHERE source=? AND variant=? ORDER BY chunk,term,position',(sid,variant))]

    def get_embedding(self, digest, version, text):
        row=self.db.execute('SELECT vector FROM embeddings WHERE key=?',(identity(digest,version,hashlib.sha256(text.encode()).hexdigest()),)).fetchone()
        return json.loads(row[0]) if row else None

    def put_embedding(self, digest, version, text, vector):
        sha=hashlib.sha256(text.encode()).hexdigest();key=identity(digest,version,sha)
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO embeddings VALUES (?,?,?,?,?)',(key,digest,version,sha,canonical(vector).decode()))
        return key

    def link_embedding(self, source, chunk, variant, digest, version, text):
        key=identity(digest,version,hashlib.sha256(text.encode()).hexdigest())
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO refs VALUES (?,?,?,?)',(source,chunk,variant,key))
        self.revision += 1

    def vectors(self, selected, variant):
        return {(r['source'],r['chunk']):json.loads(r['vector']) for sid in sorted(selected) for r in self.db.execute(
            'SELECT refs.source,refs.chunk,embeddings.vector FROM refs JOIN embeddings ON refs.key=embeddings.key WHERE source=? AND variant=? ORDER BY chunk',(sid,variant))}

    def delete_source(self, source):
        with self.db:
            self.db.execute('DELETE FROM sources WHERE id=?',(source,))
            self.db.execute('DELETE FROM embeddings WHERE key NOT IN (SELECT key FROM refs)')
        self.revision += 1

    def canonical_export(self):
        # Every declared table, no rowid/internal SQLite objects. Semantic keys are table PKs.
        result={}
        for table in TABLES:
            rows=[dict(r) for r in self.db.execute('SELECT * FROM '+table)]
            keys={'notebooks':('id',),'sources':('notebook','doc_id'),'chunks':('source','id'),'inputs':('source','chunk','variant'),'postings':('source','chunk','variant','term','position'),'stats':('source','variant','term'),'embeddings':('digest','version','text_sha256'),'refs':('source','chunk','variant')}[table]
            result[table]=sorted(rows,key=lambda row:tuple(row[k] for k in keys))
        return canonical(result)

    def integrity(self):
        return {'foreign_key_errors':[list(r) for r in self.db.execute('PRAGMA foreign_key_check')],
                'chunks':self.db.execute('SELECT COUNT(*) FROM chunks').fetchone()[0],
                'embedding_refs':self.db.execute('SELECT COUNT(*) FROM refs').fetchone()[0],
                'embedding_count':self.db.execute('SELECT COUNT(*) FROM embeddings').fetchone()[0],
                'orphan_embeddings':self.db.execute('SELECT COUNT(*) FROM embeddings WHERE key NOT IN (SELECT key FROM refs)').fetchone()[0]}

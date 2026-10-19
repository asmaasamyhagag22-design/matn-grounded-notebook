"""Persistent offline tokenizer; kept separate from generation and L4 weights."""
import json
from pathlib import Path
import subprocess


class TokenCounter:
    def __init__(self):
        self.process=subprocess.Popen([str(Path.home()/'.venvs/matn-rerank/bin/python'),'-m','eval.chat.tokenizer_worker'],
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True,bufsize=1)
        self.metadata=json.loads(self.process.stdout.readline())
        if not self.metadata.get('ready'):raise ValueError('TOKENIZER_UNAVAILABLE')
    def __call__(self,prompt):
        self.process.stdin.write(json.dumps(prompt)+'\n');self.process.stdin.flush()
        return json.loads(self.process.stdout.readline())['tokens']
    def close(self):
        self.process.stdin.close();self.process.wait(timeout=20);self.process.stdout.close()

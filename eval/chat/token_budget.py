"""Persistent offline tokenizer in an isolated Python environment."""
import json
import os
from pathlib import Path
import subprocess


class TokenCounter:
    def __init__(self):
        default = Path.home() / '.venvs' / 'matn-rerank' / 'bin' / 'python'
        python = os.environ.get('MATN_TOKENIZER_PYTHON') or os.environ.get('MATN_NLI_PYTHON') or default
        self.process = subprocess.Popen(
            [str(python), '-B', '-m', 'eval.chat.tokenizer_worker'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1,
        )
        try:
            handshake = self.process.stdout.readline()
            if not handshake:
                raise ValueError('TOKENIZER_UNAVAILABLE: check the Python environment and the pinned Ollama model')
            self.metadata = json.loads(handshake)
            if not self.metadata.get('ready'):
                raise ValueError('TOKENIZER_UNAVAILABLE')
        except Exception:
            self.close()
            raise

    def __call__(self, prompt):
        self.process.stdin.write(json.dumps(prompt) + '\n')
        self.process.stdin.flush()
        return json.loads(self.process.stdout.readline())['tokens']

    def close(self):
        self.process.stdin.close()
        self.process.wait(timeout=20)
        self.process.stdout.close()

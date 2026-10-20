"""Foreground, project-scoped Linux Ollama with bounded host prompt cache.

Stop with Ctrl-C; no service files or generation options are changed.
The default port deliberately matches Matn's existing loopback transport.
"""
from __future__ import annotations

import argparse
import fcntl
import os
from pathlib import Path
import signal
import socket
import subprocess
import tempfile


def runtime_env(port: int, cache_mib: int, models: Path) -> dict[str, str]:
    if not 1024 <= port <= 65535 or not 0 <= cache_mib <= 512:
        raise ValueError('port must be 1024..65535; cache must be 0..512 MiB')
    env = os.environ.copy()
    env.update(OLLAMA_HOST=f'127.0.0.1:{port}', OLLAMA_MODELS=str(models),
               OLLAMA_MAX_LOADED_MODELS='1', OLLAMA_NUM_PARALLEL='1',
               OLLAMA_KEEP_ALIVE='60m', OLLAMA_NO_CLOUD='1', OLLAMA_NOPRUNE='1',
               LLAMA_ARG_CACHE_RAM=str(cache_mib))
    return env


def resident_runners(proc: Path = Path('/proc')) -> list[int]:
    runners = []
    for path in proc.glob('[0-9]*/cmdline'):
        try:
            args = path.read_bytes().split(b'\0')
            if (Path(os.fsdecode(args[0])).name == 'llama-server' or
                    (Path(os.fsdecode(args[0])).name == 'ollama' and args[1:2] == [b'runner'])):
                runners.append(int(path.parent.name))
        except (OSError, ValueError):
            continue
    return runners


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=11434)
    parser.add_argument('--cache-mib', type=int, default=512)
    parser.add_argument('--models', type=Path, default=Path('/usr/share/ollama/.ollama/models'))
    args = parser.parse_args()
    env = runtime_env(args.port, args.cache_mib, args.models.resolve(strict=True))
    if not args.models.is_dir():
        parser.error('model store must be an existing directory')
    help_text = subprocess.run(['/usr/local/lib/ollama/llama-server', '--help'],
                               capture_output=True, text=True, check=True).stdout
    if 'LLAMA_ARG_CACHE_RAM' not in help_text:
        parser.error('installed backend does not advertise LLAMA_ARG_CACHE_RAM')
    lock_path = Path(tempfile.gettempdir()) / f'matn-cpu-runtime-{os.getuid()}.lock'
    with lock_path.open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.error('another project CPU runtime owns the lock')
        if resident_runners():
            parser.error('an existing model runner is resident; leave existing jobs alone')
        with socket.socket() as probe:
            # Match Ollama's listener: a recently closed connection in TIME_WAIT
            # must not look like an active service after a clean shutdown.
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind(('127.0.0.1', args.port))
            except OSError:
                parser.error('port is busy; stop the idle Ollama service before using its port')
        child = subprocess.Popen(['/usr/local/bin/ollama', 'serve'], env=env, start_new_session=True)

        def stop(signum, frame):
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGTERM)

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        try:
            return child.wait()
        finally:
            stop(None, None)
            try:
                child.wait(timeout=15)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()


if __name__ == '__main__':
    raise SystemExit(main())

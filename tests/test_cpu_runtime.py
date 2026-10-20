"""Runtime-only safeguards; no model calls or evaluation inputs."""
import importlib.util
from pathlib import Path
import signal
import socket
from types import SimpleNamespace

import pytest

pytest.importorskip('fcntl')  # The opt-in launcher uses Linux /proc and process groups.

SPEC = importlib.util.spec_from_file_location(
    'cpu_runtime', Path(__file__).resolve().parents[1] / 'scripts/cpu_runtime.py')
runtime = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runtime)


def test_scoped_settings_override_inherited_unbounded_cache(monkeypatch):
    monkeypatch.delenv('OLLAMA_CONTEXT_LENGTH', raising=False)
    monkeypatch.setenv('LLAMA_ARG_CACHE_RAM', '-1')
    monkeypatch.setenv('OLLAMA_HOST', '0.0.0.0:11434')
    monkeypatch.setenv('OLLAMA_NUM_PARALLEL', '8')
    env = runtime.runtime_env(11434, 512, Path('/models'))
    assert env['LLAMA_ARG_CACHE_RAM'] == '512'
    assert env['OLLAMA_HOST'] == '127.0.0.1:11434'
    assert env['OLLAMA_NUM_PARALLEL'] == env['OLLAMA_MAX_LOADED_MODELS'] == '1'
    assert env['OLLAMA_NO_CLOUD'] == '1'
    assert env['OLLAMA_NOPRUNE'] == '1'
    assert env['OLLAMA_MODELS'] == '/models'
    # No payload/context/decoder option is set by the launcher.
    assert 'OLLAMA_CONTEXT_LENGTH' not in env


@pytest.mark.parametrize('port,cache', [(80,512),(65536,512),(11434,-1),(11434,513)])
def test_runtime_rejects_unbounded_or_invalid_config(port, cache):
    with pytest.raises(ValueError):
        runtime.runtime_env(port, cache, Path('/models'))


def test_resident_detection_includes_backend_and_legacy_runner(tmp_path):
    for pid, command in [(1,b'/usr/local/lib/ollama/llama-server\0--port\0000\0'),
                         (2,b'/usr/local/bin/ollama\0runner\0--model\0x\0'),
                         (3,b'/usr/local/bin/ollama\0serve\0'),
                         (4,b'/usr/bin/python\0some-script.py\0')]:
        folder = tmp_path / str(pid)
        folder.mkdir()
        (folder / 'cmdline').write_bytes(command)
    assert sorted(runtime.resident_runners(tmp_path)) == [1,2]


def test_launcher_can_rebind_after_clean_tcp_shutdown(tmp_path, monkeypatch):
    # Close the server end first, leaving a real TIME_WAIT connection. An
    # ordinary bind probe incorrectly reports this as an active server.
    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(('127.0.0.1', 0)); listener.listen()
        port = listener.getsockname()[1]
        with socket.create_connection(('127.0.0.1', port)) as client:
            connection, _ = listener.accept()
            connection.close()
            assert client.recv(1) == b''
    monkeypatch.setattr(runtime, 'resident_runners', lambda: [])
    monkeypatch.setattr(runtime.tempfile, 'gettempdir', lambda: str(tmp_path))
    monkeypatch.setattr(runtime.subprocess, 'run', lambda *a, **k: SimpleNamespace(stdout='LLAMA_ARG_CACHE_RAM'))
    monkeypatch.setattr(runtime.subprocess, 'Popen', lambda *a, **k: SimpleNamespace(
        wait=lambda **kw: 0, poll=lambda: 0))
    monkeypatch.setattr(signal, 'signal', lambda *a: None)
    monkeypatch.setattr('sys.argv', ['cpu_runtime.py', '--port', str(port), '--models', str(tmp_path)])
    assert runtime.main() == 0

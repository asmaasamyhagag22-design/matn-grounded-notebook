# Optional bounded CPU runtime (Linux)

On a 15.3 GiB CPU laptop, saved host prompt states accumulated to about 4.69 GiB before an OOM during prompt-cache saving. A project-scoped Ollama launch profile now bounds this cache while keeping the model loaded. This is an opt-in operational change; generation prompts, schema, decoding settings, retrieval and verification defaults are unchanged.

The installed runtime was Ollama 0.40.2 with llama-server 0.5.0-dev, build 1, commit `631109b34`. Its help advertises `LLAMA_ARG_CACHE_RAM`; the runner inherited `512`, its logs reported a 512 MiB limit and cache eviction, and no `--cache-ram` command-line override was present. No runtime upgrade was needed. Upstream context: [Ollama #17351](https://github.com/ollama/ollama/issues/17351), [#18264](https://github.com/ollama/ollama/issues/18264), and the [llama-server documentation](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md). Recheck effective settings if the installed runtime changes.

Ensure the regular service is idle and no other model job is running, then start the foreground profile from the repository root:

```bash
sudo systemctl stop ollama
python scripts/cpu_runtime.py
```

Run the existing Chat API/CLI in another terminal. The default port remains `127.0.0.1:11434`; the launcher sets parallelism and maximum loaded models to one, disables cloud features and pruning, and caps saved prompt cache at 512 MiB. It refuses a busy port, a resident runner or another instance of this launcher. The defaults use `/usr/local/bin/ollama`, `/usr/local/lib/ollama/llama-server`, and `/usr/share/ollama/.ollama/models`; `--models` can select an existing store. This launcher targets the tested Linux installation layout.

To undo the operational change, stop the launcher with Ctrl-C and restore the ordinary service:

```bash
sudo systemctl start ollama
```

No service configuration files are edited. The original service's cache policy returns when restarted. `--port 11435` supports isolated diagnostics; the existing Chat transport still uses 11434. Do not run concurrent resident generators. The launcher does not enforce a total-RAM limit.

## Diagnostic result — improved with limits

Each arm used eight requests in the sequence A B C D A C B D, prepared from public RFC 8259, 4180, 7946 and 3339. Paragraph catalogs came from character slice `[5000:19000]`, with 69/46/68/58 handles and 2380–4199 prompt tokens. This was generation-only, not an end-to-end retrieval or verification benchmark. Model: `qwen3.5:9b`, digest `56671c2ab9385f9cfcb404638e32cd62d88e3501d44822208363c010179a3c90`; context 16384, output limit 768, seed 20261018, temperature 0, four threads, thinking disabled, truncation disabled, keep-alive 60 minutes. Matching requests used identical prompts and JSON schemas.

| Measurement | Default 8192 MiB | Bounded 512 MiB |
|---|---:|---:|
| Completed requests / OOM / runner recycles | 8 / 0 / 0 | 8 / 0 / 0 |
| Maximum logged saved cache, MiB | 824.778 | 509.562 |
| Sampled peak runner RSS, GiB | 7.914 | 7.679 |
| Sampled peak process group RSS, GiB | 7.946 | 7.711 |
| Minimum system MemAvailable, MiB | 1907.75 | 2442.90 |
| Maximum memory full PSI avg10, % | 3.24 | 2.37 |
| Maximum owned process group swap, MiB | 309.14 | 0 |
| Separate load-only wall time, seconds | 20.34 | 20.87 |
| Request wall p50 / p95, seconds | 110.62 / 331.80 | 312.64 / 354.76 |
| Total request wall, seconds | 1242.23 | 2296.61 |
| First four new requests, seconds | 1141.76 | 1141.12 |
| Four revisits, seconds | 100.47 | 1155.49 |

The observed total latency cost was **84.9%**, concentrated in prompt evaluation after eviction. Generation evaluation totals were similar (178.53 versus 175.98 seconds). All eight paired responses were byte-identical and all 16 matched their JSON schemas. This establishes neither semantic accuracy nor long-run reliability.

The arms ran sequentially, default first, on fresh runners at a temporary loopback endpoint while the ordinary service was empty. Both disabled cloud features and pruning. Memory sampling targeted one-second intervals, with scan overhead (1141/2095 samples); peaks between samples may be missed and summed RSS can double-count shared pages. The experiment stopped automatically above 8 GiB runner RSS or below 768 MiB MemAvailable; neither stop condition occurred. There was one runner PID throughout each arm and no L4 residency.

Ambient application memory, swap and OS cache were not controlled or counterbalanced: global swap started at 0/1653.74 MiB and ended at 1989.30/2090.99 MiB. The four-catalog workload and 7–75 generated tokens per request are limited evidence. The cache cap does not bound KV memory, recurrent checkpoints, repacked weights, workspaces or allocator overhead. A longer varied public-input soak and full Chat residency measurement remain necessary before claiming general runtime stability. Internal evaluation artifacts and diagnostic raw outputs are not published.

# Local setup

Matn was tested on Ubuntu 24.04 with Python 3.12, four CPU cores and 15 GiB of RAM. Use the fixture walkthrough to try the UI with no model weights.

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-app.txt
sudo apt-get install libreoffice-impress fonts-crosextra-carlito fonts-noto-core fonts-liberation
.venv/bin/python -B -m matn_app --fake --search-budget 0
```

Open `http://127.0.0.1:8787`, attach a small JSON file such as `{"policy":"Inspect equipment before use."}`, then ask what the policy says. The source overview includes a citation and the answer shows the fixture notice. The default data directory is `.matn-data/app`. Use `--data` for a different directory, or set `MATN_WORK_ROOT` to move the workspace. The server listens on loopback. Font hashes and notices are in [design/fonts](../design/fonts).

## Real local inference

- Run Ollama on `127.0.0.1:11434` and provision the pinned `qwen3.5:9b` generator and `qwen3-embedding:0.6b` embedder. The adapters check the model digests recorded in [generation.py](../matn_chat/generation.py) and [embedding.py](../matn_rag/embedding.py). Document Q&A uses hybrid retrieval, including embeddings for a bounded pool of passages when an index lacks vectors.
- Set `MATN_NLI_PYTHON` to the Python executable of a separate CPU environment with PyTorch and Transformers. Set `MATN_MINICHECK_DIR` to the local `MiniCheck-RoBERTa-Large` directory. Use revision `74c8919647e61ed0f71bc177d94f10930f090068` of [MiniCheck-RoBERTa-Large](https://huggingface.co/lytang/MiniCheck-RoBERTa-Large) and copy [the acquisition receipt](../config/minicheck-acquisition.json) into the model directory as `acquisition.json`. The verifier checks the local files against the receipt.
- The prompt budget uses `tokenizers` to read vocabulary metadata from the installed Qwen GGUF. Install `tokenizers` in the verifier environment or set `MATN_TOKENIZER_PYTHON` to a separate Python that has it. Set `OLLAMA_MODELS` if the Ollama model store is outside its standard location. The pinned blob is listed in [the tokenizer profile](../eval/chat/tokenizer_profile.json).
- For scanned pages, install [the RapidOCR worker requirements](../requirements-ocr-rapid-linux.lock.txt) in `.venv-ocr-rapid` and provision the reader and layout models pinned in [rapidocr_settings.json](../matn_reading/ocr/rapidocr_settings.json) and [regions.py](../matn_reading/ocr/regions.py). GLM-OCR provides an independent numeric check over loopback. Its local model and limits are in [glm.py](../matn_reading/ocr/glm.py).

Run `./app.sh --search-budget 0` on Ubuntu. This starts the same loopback server under a sleep inhibitor. Model weights are installed separately under their upstream licences. [Qwen generator](https://huggingface.co/Qwen/Qwen3.5-9B) · [Qwen embedder](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B) · [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR) · [GLM-OCR](https://huggingface.co/zai-org/GLM-OCR)

### Answer profiles

The [shipped profile](../matn_app/answer_profile.json) selects the quote-first path. Pass `--answer-profile path/to/profile.json` to change it. A profile can select the earlier path with `{"answer_path":"v2"}`, or override individual booleans in [the quote-first policy](../matn_app/answer_v3_policy.json) under `v3_components`. The generator remains pinned.

## Public-source research preview

Document Q&A runs locally with a zero search budget. The research preview fetches public sources only after an explicit search allowance and uses a separately configured Tavily account. Supply `TAVILY_API_KEY` as an environment variable and keep credentials out of Git. Use `--dev-research-v2` to enable the included experimental research implementation. CI uses synthetic fixtures for research checks.

## Development checks

In a clean Python 3.12 environment, install `requirements-ci.txt`, the rendering packages above and Node.js, then run `bash scripts/ci-fast.sh`. Enable the public hooks with `git config core.hooksPath .githooks`. The hooks check staged files and commit messages and run the full test suite on push.

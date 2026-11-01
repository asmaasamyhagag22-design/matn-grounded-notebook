# Local setup

The tested desktop environment is Ubuntu 24.04, Python 3.12, four CPU cores and 15 GiB RAM, without a GPU. The public CI exercises deterministic offline contracts; it does not download inference weights or reproduce the private evaluations.

## UI and rendering

Create `.venv`, install `requirements-app.txt`, and install LibreOffice Impress, `fonts-crosextra-carlito`, `fonts-noto-core` and `fonts-liberation`. `design/fonts/fonts.json` lists exact package versions and file hashes; `matn_deck.measure.verify_fonts()` reports any mismatch. Font notices are under `design/fonts/licenses/`. Templates and icons have separate provenance files.

Run `.venv/bin/python -B -m matn_app --fake --search-budget 0` for the labelled UI walkthrough. The default data directory is `.matn-data/app`, ignored by Git. Set `MATN_WORK_ROOT` to an absolute writable directory to move it. The app binds to loopback. Do not expose it as a multiuser service.

## Real local inference

`pip install` alone does not provision these environments. The application fails closed when required models, identities or dependencies are absent. Provision and validate these components before using `./app.sh --search-budget 0`:

1. Ollama on `127.0.0.1:11434`, with `qwen3.5:9b` digest `56671c2ab9385f9cfcb404638e32cd62d88e3501d44822208363c010179a3c90`. The generation adapter checks the digest and structured output. Research additionally uses `qwen3-embedding:0.6b` digest `ac6da0dfba84a81fdbfbaf330198c33cd77c4cdfc53e8bc50eb581914a15621d`. Document retrieval uses BM25 and does not need an embedding pass.
2. A separate native verification environment, with PyTorch and Transformers matching the available platform lockfile. Set `MATN_NLI_PYTHON` to its absolute Python path and `MATN_MINICHECK_DIR` to the local MiniCheck model directory. The pinned repository is `lytang/MiniCheck-RoBERTa-Large`, revision `74c8919647e61ed0f71bc177d94f10930f090068`. The directory must be named `MiniCheck-RoBERTa-Large` and contain the byte-identical `acquisition.json` supplied in `config/minicheck-acquisition.json` (SHA256 `ca617cb5d612c538fc02db7ba732e39b0d40bcef8e08137cf459fb6818d3b026`). Download the pinned upstream files separately and copy that metadata file into the model directory; `matn_verification/l4_files.py` and `l4_worker.py` define and verify the contract. Neither weights nor receipts are distributed. A missing verifier produces unavailable/partial results rather than a verified answer.
3. OCR requires a separate `.venv-ocr-rapid` environment from `requirements-ocr-rapid-linux.lock.txt`, and local files matching every hash/path in `matn_reading/ocr/rapidocr_settings.json` and `regions.py`. The layout model is required too. GLM-OCR on loopback provides independent numeric checks; its configured model tag and limits are in `matn_reading/ocr/glm.py`. OCR and local document generation block external egress. Do not use unverified substitute weights and report the old identity.

Model setup is an advanced manual step in this export. Platform lockfiles are environment records, not universal installers. Windows PowerPoint output remains unmeasured. No model licence is conveyed by this project's pending licence; check each upstream model's terms separately.

## Public-source research

Search requires an explicit allowance and a separately configured Tavily account. Provide `TAVILY_API_KEY` in the process environment or the external configuration supported by `matn_research/providers.py`; never commit it. The preflight requires account qualification and available credit evidence. It is not a purchase flow. No searches run on startup or in CI. Source fetching is networked only in the explicit research journey; uploaded documents are processed locally.

The fresh-topic candidate failed the pre-registered acceptance rule. Use saved reviewed evidence for demonstrations; a successful source-span check does not establish axis relevance. The original delivery gallery and its meeting ledgers are private operational artifacts and are not bundled here. An empty public `eval/registry.json` represents the absence of private evaluation documents, not a published test split. Historical evaluation commands need their own data and will not reproduce scores from this repository alone.

## Development checks

Install `requirements-ci.txt`, then run the exact CI command in `scripts/ci-fast.sh`. Enable the shipped hooks with `git config core.hooksPath .githooks`; they enforce forbidden-file checks, offline tests, Conventional Commits and the public owner's no-agent-trailer convention. The private development checkout uses a different trailer convention; the public export deliberately follows the owner's explicit publication instructions.

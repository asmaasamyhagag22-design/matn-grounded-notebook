# Contributing to Matn

## Setup

On Ubuntu, install Python 3.12 and the rendering and JavaScript dependencies. From the repository root, create a virtual environment and enable the Git hooks.

```bash
sudo apt-get install libreoffice-impress fonts-crosextra-carlito fonts-noto-core fonts-liberation nodejs
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-ci.txt
git config core.hooksPath .githooks
```

See [local setup](docs/local-setup.md) for the fixture walkthrough and local inference.

## Tests and commits

```bash
bash scripts/ci-fast.sh
python -B -m pytest tests checks -q -p no:cacheprovider
```

The first command matches offline CI. The second includes the slow tests. The pre-commit hook checks staged files and runs the fast tests for Python changes. The pre-push hook runs the full suite.

Use a [Conventional Commit](https://www.conventionalcommits.org/) subject such as `fix: preserve citation offsets`. Add a short body explaining why the change is needed and leave out trailers.

## Licence boundaries

Keep new PyMuPDF imports under `eval/` and leave the existing exceptions listed in [ADR 0001](docs/adr/0001-pymupdf-agpl-eval-tooling-only.md) frozen. Use `pdftotext` only as an external CLI for evaluation cross-checks. [ADR 0002](docs/adr/0002-pdftotext-gpl-eval-cross-check-only.md)

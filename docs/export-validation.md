# Public export validation

This export packages the Matn v3.1 runtime, the three original presentation templates, licensed icons and deterministic tests. [public-export.json](../public-export.json) records the source runtime and SHA-256 hashes of the exported files. The inventory excludes the manifest itself.

The offline workflow installs `requirements-ci.txt` in a fresh Python 3.12 environment and runs `bash scripts/ci-fast.sh`. The local run passed 594 tests with 8 slow tests deselected. Tests exercise quote validation, sentence retraction, number, unit and scope checks, document-aware retrieval and packing, and policy overrides with fake model adapters. The AGPL and GPL CLI boundary checks run in the same suite. The fixture walkthrough exercises the loopback app with a zero search budget. Attaching synthetic JSON produces a cited source overview, and submitting a question returns the fixture notice without a model call.

The hero was captured from a local v3.1 run with the two credited public PDFs and a zero search budget. The published benchmark tables describe the earlier measurements. [Results and methodology](results.md)

The export includes an empty evaluation registry and synthetic fixtures. Source PDFs, weights and evaluation data are provisioned separately.

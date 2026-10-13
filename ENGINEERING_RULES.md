# Matn engineering rules

Matn is a local, offline PDF → summary → presentation tool. This development copy uses public documents only.
Delivery safeguards and their status are recorded in `docs/PRE_DELIVERY_CHECKLIST.md`.

1. Public documents only. Never open restricted ministry material or the commercial book, and never send ministry documents to a cloud service.
2. Numbers and IDs are never invented. Code copies and verifies them against the source. A model must not invent, convert or recompute source numbers.
3. Test first for behavior changes: establish a failing test, make a small diff, run tests until green, then commit with a message explaining what changed and why. Tests must pass before every commit.
4. The test split is sealed. Never tune on `eval/gold/test/`. Access it only for recorded milestone measurements with `EVAL_MILESTONE=1`; never tune after seeing the results. Sealed gold is omitted from this public repository. Registry split entries remain to enforce the boundary.
5. Ask before deleting work, rewriting history or changing test expectations. Act only within the explicitly approved scope. Approval applies to the changes named by the owner; a general instruction to continue does not approve additional changes.
6. Network access is limited to loopback by default. Installs, downloads, model pulls and remote Git operations require named owner approval. Approved evaluation acquisition uses `MATN_ALLOW_NETWORK=1`.
7. Keep prompts in versioned files. Every run records the code commit, model digest, prompt versions and parameters.
8. Keep paths portable with `pathlib`, support Ubuntu and Windows, and write code comments in English.
9. Logs contain hashes and IDs only, never document text, source-containing prompts or secrets. Keep reports short, in Egyptian Arabic, with code and technical terms in English.
10. Never commit environments, node modules, models, caches, run outputs, PDFs, extracted page text, secrets, the commercial book or derived material, or files over 5 MB. Presentation source templates under `design/templates/` are the documented PPTX exception.
11. Preserve the license boundaries in ADR 0001 and ADR 0002. New PyMuPDF imports belong only in evaluation tooling pending legal review; existing importers are frozen, not approved. The secondary GPL text extractor runs only as an external evaluation CLI.
12. Never bypass hooks or use `--no-verify`. Do not reword a blocked operation to evade a guard. Only non-operative text may be reworded when the action is already approved, with the instance recorded.
13. Deterministic IDs and hashes must derive from verified inputs. Fail closed on missing, mismatched or unverified evidence. Never treat unavailable table cells or chart text as validated numerical evidence.
14. Every cited statement must bind to source blocks for the named entity, not a neighboring entity in the same chunk. Model labels and model screening must retain their provenance and must never imply human validation.

Work on `foundation`. Use the configured environment interpreter with `-m pytest -q`.
Set `core.hooksPath` to `.githooks`: pre-commit enforces forbidden staged files and runs the fast subset for Python changes; pre-push runs the full suite. Slow cases are listed in `conftest.py`.

Pipeline: `inspect_pdf.py`, `document_store.py`, `select_source.py`, `matn_summarization/`, `matn_presentation/`, `app.py`.
Contracts: `matn_contracts/`. Evaluation: `eval/`. Decisions: `docs/adr/`. Guards: `checks/`.

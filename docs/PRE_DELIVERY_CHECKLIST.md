# Pre-delivery checklist

Owner decision, 2026-10-02: speed first on the development copy, which uses public documents only. The safeguards
below were removed, disabled, or deferred, and each one must be re-enabled and checked before the system is handed
to the ministry. Tick an item only with evidence (a commit, a test, or a report under `reports/`).

## Removed or disabled on 2026-10-02

- [ ] **Claude guard hooks (R1–R5).** They were unregistered in `.claude/settings.json` (the registration is in `f617c96`). The code and tests stay in
      `.claude/hooks/guard.py` and `.claude/hooks/test_guard.py`. Re-register them, then start a new session (hook
      config is read at session start) and prove each rule live.
- [ ] **Fast-suite timing budget** (`checks/fast_budget.py`, `checks/test_fast_budget.py`). Decide whether delivery
      needs it. Pre-commit still runs the fast tests, with no time limit.
- [ ] **The long rule set** in the old `CLAUDE.md` (rules 1–15), restorable from git history. Review which rules the
      delivered system needs.

## Deferred hardening

- [ ] **Network block plus an egress test.** A check that proves the pipeline opens no socket except 127.0.0.1.
- [ ] **Offline install on Ubuntu.** A Linux wheelhouse for one chosen Python version (3.11 vs 3.12, `pydantic-core`
      and `hypothesis` are compiled wheels), installed with `--no-index`, then verified (audit F-04).
- [ ] **F-03 no-proxy opener** for every Ollama call (`audit/proposed-diffs/`).
- [ ] **Streamlit bound to loopback** (127.0.0.1), with its startup network call disabled.
- [ ] **Ollama:** auto-update off and cloud models disabled (audit F-53).
- [ ] **PyMuPDF AGPL decision** (ADR-0001): accept the AGPL, buy a commercial license, or migrate. Also settle the
      pdftotext license question (ADR-0002).
- [ ] **Logs never contain document content**: hashes and IDs only, with a test that scans the run logs.
- [ ] **A full audit** of the delivered tree, like `audit/AUDIT.md`.
- [ ] **A cross-review of the whole codebase** by an independent agent or person.

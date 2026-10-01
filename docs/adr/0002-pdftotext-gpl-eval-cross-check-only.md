# ADR-0002: pdftotext (GPL) is an external CLI for eval cross-checks only

- **Status:** Accepted, 2026-10-01 (user decision 3, Step 0 part 2). Open for the same legal review as ADR-0001.
- **Enforced by:** `checks/test_gpl_cli_boundary.py` (runs in pre-commit G2 and pre-push G4).

## Context

The gold reference is verified against PyMuPDF text (ADR-0001). So that it does not depend on one extractor's quirks,
`eval/cross_check.py` re-checks every gold quote with a second extractor. The only one on this machine, with nothing
installed, is `pdftotext` bundled with Git for Windows:

| Fact | Evidence (read 2026-10-01) |
|---|---|
| Path | `C:\Program Files\Git\mingw64\bin\pdftotext.exe` (`cygpath -w /mingw64/bin/pdftotext.exe`) |
| Version and vendor | `pdftotext -v`: `pdftotext version 4.06 [www.xpdfreader.com]`, `Copyright 1996-2025 Glyph & Cog, LLC` |
| License file | none found: no Xpdf or Poppler entry under `/mingw64/share`, `/usr/share/licenses`; `Git/LICENSE.txt` is Git's GPL v2 and does not mention Xpdf |
| Git for Windows notes | `ReleaseNotes.html:3679` says it "Includes poppler" for PDF diffs; the shipped binary's banner says Xpdf |

The user's decision 3 records pdftotext as GPL. Which GPL version, and the license of this exact build, could not be
confirmed from anything on this machine, so it needs the legal review that ADR-0001 asks for.

## Decision

1. `pdftotext` may be used **only as an external program, from eval tooling** (`eval/`), to cross-check gold quotes and
   text-layer health. It runs as a separate process (`subprocess`); nothing links to it, and its output never ships.
2. **Pipeline code never calls, wraps or depends on it**: not as a fallback extractor, not through an environment
   variable such as `MATN_PDFTOTEXT`, not in scripts. "Pipeline code" is every code file outside `eval/`.
3. It is never installed or downloaded by Matn. Where it is missing (for example on a fresh Ubuntu machine), the
   cross-check tests skip and the cross-check script refuses with a clear message; nothing falls back silently.

## Enforcement

`checks/test_gpl_cli_boundary.py` (with `checks/gpl_cli_boundary.py`) fails when any code file that a commit could
contain (tracked, or untracked and not ignored: `.py`, `.sh`, `.ps1`, `.psm1`, `.bat`, `.cmd`, and the suffix-less
hook scripts in `.githooks/`) mentions `pdftotext`, case-insensitively, outside `eval/` and the guard itself. A
mention in a comment counts too: the rule is "no dependency", and a comment is where one usually starts.

Blind spots: a program name built at runtime (`"pdf" + "totext"`), other Xpdf or Poppler programs (`pdftoppm`,
`pdfinfo`, …; not covered by this decision, listed as an open question), and code outside the repository.

## Consequences

- Cross-check results depend on the pdftotext build (vendor and version are recorded in the cross-check report and
  in `eval/gold/MANIFEST.json`).
- Questions for legal review, in addition to ADR-0001's: (a) is internal eval-only use of a GPL command-line program
  acceptable? (b) should the same rule cover the rest of the Xpdf/Poppler tool family?

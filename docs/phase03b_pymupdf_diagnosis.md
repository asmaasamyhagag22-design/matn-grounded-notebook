# Phase 03B PyMuPDF diagnosis

## Result

The originally reproduced four full-suite failures were caused by Windows
Application Control / Code Integrity blocking the native PyMuPDF layout
extension. This is confirmed by a reproduced Python import error and correlated
Code Integrity Events 3077 and 3089. No Windows security setting was changed.

The current state has subsequently recovered without a project or security
policy change made by this remediation: PyMuPDF imports successfully and the
complete suite passes. The historical block evidence is retained because the
cause of the earlier failures was real even though it is not active now.

## Reproduction

The suite was run from the project virtual environment with:

```powershell
.\.venv\Scripts\python.exe -m pytest -vv --tb=long *> pymupdf_failures.txt
```

Result: `79 passed, 4 failed`. Every failure reaches
`import pymupdf.features as rf_features` and then fails while loading
`pymupdf\_features.pyd` with:

```text
ImportError: DLL load failed while importing _features: An Application Control policy has blocked this file.
```

The full traceback is preserved in `pymupdf_failures.txt`.

## Environment evidence

- Interpreter: `C:\Users\asmaa\Documents\notebooklm\matn\.venv\Scripts\python.exe`
- Python: 3.11.9, MSC v.1938, 64-bit AMD64
- Platform: `Windows-10-10.0.26200-SP0`
- PyMuPDF: 1.28.2
- PyMuPDF import: successful from `.venv\Lib\site-packages\pymupdf\__init__.py`
- `fitz` distribution: not separately installed
- `pip check`: `No broken requirements found.`

The collected command output is preserved in `pymupdf-environment.txt`.

## Current recovery validation

On 2026-09-30, the same project virtual environment successfully imported
PyMuPDF 1.28.2 from `.venv\Lib\site-packages\pymupdf\__init__.py`. A fresh
Code Integrity query covering the preceding 15 minutes returned no Events
3033, 3076, 3077, or 3089. The focused suite passed `77 passed`, and two fresh
complete-suite executions passed `102 passed` (31.04 seconds and 25.23
seconds). The verbose second result is preserved in
`pymupdf_recovery_validation.txt`.

The available evidence does not identify which external reputation or policy
state changed, so this report does not attribute the recovery to an
administrator action, reinstall, or code change.

## Code Integrity evidence

Immediately after the reproduced failures, Event 3077 reported:

- blocked file: `\Device\HarddiskVolume3\Users\asmaa\Documents\notebooklm\matn\.venv\Lib\site-packages\pymupdf\_features.pyd`
- parent process: `\Device\HarddiskVolume3\Users\asmaa\AppData\Local\Programs\Python\Python311\python.exe`
- policy name: `VerifiedAndReputableDesktop`
- policy ID: `27555.1000.240208`
- policy GUID: `{0283ac0f-fff1-49ae-ada1-8a933130cad6}`
- policy hash: `2668895A5B233A80432D00D67251D7B7F52686A3FB13780F4B242C5A1F937A01`
- status: `0xc0e90002`
- requested signing level: 2
- validated signing level: 1
- SHA-1 hash: `366CE687B20CE52FD3128A8AD77D1B5052D944CA`
- SHA-256 hash: `6596F9C41DA292644A26E1BC4C9B0796E0A918A33899FDE9BA36775B4A7C333A`
- SHA-1 flat hash: `AEC0C196A12D1434F2275BCFE8DDA62C77BACCB5`
- SHA-256 flat hash: `76EA68DAF4C3C87D5CA1EA91E9520A259124DE5F1F6FEEDAC721D1C47AB58AA5`

The correlated Event 3089 (same Activity ID) reported:

- total signature count: 0
- signature type: 0
- validated signing level: 0
- verification error: 0
- publisher: `Unknown`
- issuer: `Unknown`

The requested formatted event capture is preserved in
`codeintegrity-events.txt`. The values above were additionally read from the
event XML because the formatted `Message` field omits the signature and hash
fields.

## Required remediation if the block recurs

This was Branch 1 (App Control/WDAC confirmed). No administrator action is
currently required because the import and full test gate now pass. If the same
block recurs, an administrator must approve a policy-compliant remediation,
such as an allow rule for the exact approved PyMuPDF native module/version or
installation through the organization's managed-installer/signing process.
The allow decision should be made against the recorded file identity and
hashes rather than a broad Python or user-writable directory exception.

Reinstalling into another ordinary user-created virtual environment is not an
evidence-based fix: the block is on the native module's signing/reputation
status, not a missing dependency, architecture mismatch, `fitz` conflict, or
broken package dependency graph. The project does not disable or weaken Smart
App Control, WDAC, AppLocker, or Defender.

The full-test acceptance gate is no longer blocked by PyMuPDF in the current
environment because the suite has been rerun successfully. A future recurrence
of the same import error should block acceptance until the administrator path
above is completed and the suite passes again.

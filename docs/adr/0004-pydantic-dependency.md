# ADR-0004: Pydantic v2 for contracts; Hypothesis for tests only

- **Status:** Accepted for Step 1, 2026-10-02. Exact resolved versions and wheel hashes are pending the owner's
  wheelhouse download.
- **Decision owner:** project owner, Step 1 plan approval.
- **Scope:** the standalone `matn_contracts/` package and its tests. This ADR does not wire the contracts into the
  existing pipeline.

## Context

Step 1 needs one executable source of truth for validation and JSON Schema. The domain contracts must reject extra
fields, be frozen, enforce cross-field invariants, survive JSON round-trips, and export committed schemas. The draft
contracts must export narrower schemas that can be passed directly to Ollama's `format` parameter, so model output
is constrained before conversion into code-owned domain objects.

The repository currently has three dependency layers:

- `requirements.txt`: direct runtime dependencies;
- `requirements-dev.txt`: includes the runtime requirements and adds development/test tools;
- `requirements.lock.txt`: one flat, alphabetically sorted set of exact resolved pins used to prepare the offline
  wheelhouse.

The ignored `wheelhouse/` contains binary wheels and `SHA256SUMS.txt`. Each checksum line is a lowercase SHA-256,
two spaces, then the wheel filename. The existing preparation script downloads binary wheels only for Windows and
Python 3.11; the offline installer uses `--no-index --find-links` against the lock file.

Pydantic is not currently installed in the project virtual environment. Hypothesis is also absent. The standing
rule forbids agents from installing or downloading dependencies, so the owner will perform both actions and paste
the output before Step 1 implementation continues.

## Decision

1. Add Pydantic v2 (`pydantic>=2,<3` until the owner resolves an exact version) as a direct runtime dependency.
2. Add Hypothesis (`hypothesis>=6,<7` until exact resolution) as a development/test-only dependency. Production
   installation from `requirements.txt` must not install Hypothesis.
3. Use Pydantic models as the executable contract definitions and use `model_json_schema()` for committed JSON
   Schema snapshots and Ollama `format` schemas.
4. Keep the domain and LLM-facing draft models separate. Pydantic validates both, but conversion code owns full
   IDs and verification status.
5. After the owner downloads and installs the wheels, verify imports and versions, inspect the installed wheel
   metadata, record every exact resolved pin in the lock using the repository's existing flat format, and record
   the SHA-256 of every newly added wheel.
6. Mark Hypothesis and dependencies pulled only for it as dev/test-only in the lock documentation; keep Hypothesis
   out of `requirements.txt`.

## Why Pydantic v2

Pydantic v2 combines runtime validation, immutable model configuration, discriminated and cross-field validation,
and JSON Schema export. That removes a second hand-maintained schema representation. The exported draft schemas can
be passed directly to Ollama, while the same Python types validate the response before conversion. This directly
reduces schema drift at the LLM boundary.

## Alternatives rejected

### Standard-library dataclasses plus hand-written JSON Schema

Dataclasses are already used for internal transport objects, but they do not provide the required validation or
JSON Schema export. Maintaining validators, serializers, and schemas separately would recreate the drift already
visible between some existing emitted artifacts and committed schemas. Rejected because the contract and Ollama
schema could diverge silently.

### attrs

`attrs` is mature and MIT-licensed, and it provides concise immutable classes and validators. It does not by itself
provide the selected end-to-end validation plus JSON Schema workflow. Adding or maintaining a separate schema layer
would retain the same drift risk as dataclasses. Rejected for this contract boundary, not as a general criticism of
the library.

### msgspec

`msgspec` is BSD-3-Clause licensed and offers fast typed decoding and JSON Schema support. It was rejected because
the project specifically needs Pydantic v2's validation ecosystem and model/schema conventions for later pipeline
work, while performance is not the bottleneck in Step 1. Introducing a less familiar contract API would add owner
learning cost without a demonstrated runtime need.

## Licenses and transitive dependencies

The expected dependency/license set is below. Exact versions and the authoritative resolved graph will be checked
from the downloaded wheel `METADATA` before the lock is changed.

| Distribution | Role | License | Shipping policy |
|---|---|---|---|
| `pydantic` | direct runtime contract library | MIT | production runtime |
| `pydantic-core` | Pydantic validation engine; platform/Python-specific wheel | MIT | production runtime |
| `annotated-types` | Pydantic constraint metadata | MIT | production runtime |
| `typing-extensions` | typing backports; already present in the lock | PSF-2.0 | production runtime when resolved |
| `typing-inspection` | runtime inspection used by Pydantic | MIT | production runtime when resolved |
| `hypothesis` | property-based contract tests | MPL-2.0 | dev/test only; never in production install |
| `sortedcontainers` | Hypothesis runtime dependency | Apache-2.0 | dev/test only when resolved solely for Hypothesis |
| `exceptiongroup` | conditional Hypothesis dependency on older Python targets | MIT | dev/test only if the resolver selects it; normally unnecessary on Python 3.11 |

If the resolver returns any additional or different transitive dependency, work stops until its version, license,
wheel, and shipping classification are recorded here or in a superseding ADR update.

## Platform constraint

The development laptop runs Python 3.11.9. Ubuntu 24.04 ships Python 3.12. `pydantic-core` wheels are built per
Python version and per platform, so a Windows CPython 3.11 wheel cannot populate an Ubuntu CPython 3.12 wheelhouse.
The packaging track must choose one Python version for both machines and build separate platform wheelhouses for
that version. Step 1 records this as a known risk and does not choose or implement the packaging solution.

## Consequences

- Contract code cannot start until the owner completes the wheelhouse download and offline install and the agent
  verifies the result.
- `requirements.txt` will gain only the exact Pydantic runtime pin after verification.
- `requirements-dev.txt` will gain only the exact Hypothesis dev/test pin after verification.
- `requirements.lock.txt` will gain the exact resolved Pydantic and Hypothesis dependency graph after verification.
- The ignored wheelhouse will gain platform-specific wheels and updated hashes; wheel files remain uncommitted.
- Hypothesis property tests become required because the approved dependency will be available, but they remain
  test-only and do not enter the production installation.

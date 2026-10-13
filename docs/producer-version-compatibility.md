# Producer compatibility — policy-conformance revision 1

Pre-registered before restarting post-R-lite.3 retrieval (2026-10-13).

The owner-approved r-lite-3 producer must be accepted both when preparing a validated
structure and when selecting a stored source for retrieval. r-lite-2 remains accepted
for comparison. No other producer version is admitted. Tokenizer, index version, model
digest, source selection and transport guards remain unchanged.

The first closure attempt updated ingest acceptance but failed at the second existing
hardcoded guard in SQLite before any retrieval metric. Correct that single stored-version
membership check; preserve the interrupted database and call ledger and reuse its
SHA-keyed vectors. This is one correction to implement the already decided compatibility
policy, not a retrieval configuration change or a rule tuned against results.

# Evaluation set sources

Every PDF in this folder must be public and listed here, one table row per file. `eval/register.py` reads this table
and refuses to run if a PDF has no row, a row has no `publisher` or `url`, or the folder does not hold exactly 5 PDFs.
The PDFs themselves are git-ignored; their sha256 is pinned in `eval/registry.json`.

| file | title | publisher | url | license | doc_type |
|---|---|---|---|---|---|
| 2601.14525v1.pdf | Towards Execution-Grounded Automated AI Research | arXiv (Si et al.) | https://arxiv.org/abs/2601.14525 | TO CONFIRM (see arXiv abstract page) | research paper |

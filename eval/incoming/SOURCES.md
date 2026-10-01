# Evaluation set sources

Every PDF in this folder must be public and listed here, one table row per file. `eval/register.py` reads this table
and refuses to run if a PDF has no row, a required cell (title, publisher, url, pdf_url, license, doc_type) is empty or
still says "TO CONFIRM", or the folder does not hold exactly 5 PDFs. The PDFs themselves are git-ignored; their
sha256 is pinned in `eval/registry.json`.

- `url` is the citation page; `pdf_url` is the file that `eval/fetch_sources.py` downloads (allowlisted hosts only).
  An empty `pdf_url` is resolved by the tool from the citation page and then written here.
- To rebuild `eval/incoming/` on another machine: `python eval/fetch_sources.py --scratch <folder outside the repo>`
  in a process with `MATN_ALLOW_NETWORK=1` (approved network use only). Bytes are checked against the registry.

| file | title | publisher | url | pdf_url | license | license_url | doc_type | notes |
|---|---|---|---|---|---|---|---|---|
| 2601.14525v1.pdf | Towards Execution-Grounded Automated AI Research | arXiv (Si et al.) | https://arxiv.org/abs/2601.14525 | https://arxiv.org/pdf/2601.14525v1 | TO CONFIRM (see arXiv abstract page) | | research_paper | local copy predates the fetch tool |
| wb_eem_2021_12.pdf | Egypt Economic Monitor, December 2021: The Far-Reaching Impact of Government Digitalization | World Bank | https://openknowledge.worldbank.org/entities/publication/300aaa4c-6fa0-5ce5-8289-093e62d76d13 | | CC BY 3.0 IGO | | economic_report | English edition (an Arabic edition also exists) |
| gao_21_519sp.pdf | Artificial Intelligence: An Accountability Framework for Federal Agencies and Other Entities | U.S. Government Accountability Office (GAO) | https://www.gao.gov/products/GAO-21-519SP | https://www.gao.gov/assets/gao-21-519sp.pdf | U.S. federal government work, not subject to U.S. copyright; may contain third-party images | | audit_framework | |
| nist_ai_600_1.pdf | Artificial Intelligence Risk Management Framework: Generative Artificial Intelligence Profile (NIST AI 600-1) | National Institute of Standards and Technology (NIST) | https://doi.org/10.6028/NIST.AI.600-1 | https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.600-1.pdf | U.S. federal government work, not subject to U.S. copyright | | technical_standard | DOI recorded, not fetched |
| egypt_ai_strategy_2025_2030.pdf | Egypt National Artificial Intelligence Strategy, Second Edition (2025-2030) | National Council for Artificial Intelligence (Egypt) | https://asu.edu.eg/141090/_mediacenter/2025/pdf/c126e0d5c610f9e67ddb37b06d388bcf.pdf | https://asu.edu.eg/141090/_mediacenter/2025/pdf/c126e0d5c610f9e67ddb37b06d388bcf.pdf | Not stated; internal evaluation use only | | national_strategy | mirror hosted by Ain Shams University; an official NCAI copy was not located |

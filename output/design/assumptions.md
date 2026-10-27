Where the case document is silent or ambiguous, we chose a reading and wrote it here. We raise the important
ones with the panel at the design review. Owner: P4 (anyone may tell P4 a new one).

| # | Gap in the brief | Our decision | Why | Raised with panel? |
|---|---|---|---|---|
| 1 | "A provided synthetic business dataset" is not attached | we generate one: departments, projects, budgets, expense claims (contract 02), seeded | the combined questions need data that matches our policy documents | |
| 2 | No corpus is given | a fictional company's documents: travel and expense policy v1.0 (scanned) and v2.0 (text), IT security SOP (DOCX), onboarding FAQ (TXT), 2 handwritten meeting notes (photos), pages of a public annual report, and one document with a planted injection | covers every scenario in case section 9 | |
| 3 | No success targets | the targets in contract 00 | the case asks us to measure, not to reach a number | |
| 4 | "Scanned and handwritten documents" are in scope but "full computer-vision pipelines" are out | one vision-model call per page, no training, no layout model | meets the scope without a CV pipeline | |
| 5 | Which version wins on conflict | show both with effective dates, say which is current (C1) | the case says surface, not hide | |
| 6 | Low-quality OCR pages | not searchable until an admin approves (X7) | "approved documents" and the cost of a misread number | |
| 7 | Cost currency and prices | USD, prices from the provider's public page with the date read | the case says "where pricing is configured" | |
| 8 | Live retrieval accuracy without ground truth | live: proxies only (top rerank score); real accuracy only on the eval set | we do not claim accuracy we cannot measure | |
| 9 | "Approved API" may mean REST | SQL templates only; a REST mock is MAY | the case allows "SQL or approved API" | |

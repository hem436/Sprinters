<!-- Contract 03. Owner: P1. Status: DRAFT until the design review, then FROZEN v1.0.
     After freezing, change only through the design-change skill: an entry in CHANGES.md and a version bump. -->
# 03 Lifecycles

Version: 1.0 · Status: DRAFT · Owner: P1 (document, page), P3 (query) · Case section(s): 7

## Document lifecycle

```mermaid
stateDiagram-v2
  [*] --> QUEUED: upload accepted (X1)
  QUEUED --> EXTRACTING: worker picks the job
  EXTRACTING --> INDEXED: all pages ok
  EXTRACTING --> PARTIAL_REVIEW: some pages NEEDS_REVIEW
  EXTRACTING --> FAILED: no page could be read
  PARTIAL_REVIEW --> INDEXED: admin approves or rejects every flagged page
  INDEXED --> SUPERSEDED: new version of the same doc_key with a later effective_date
  INDEXED --> DELETED: admin deletes
  PARTIAL_REVIEW --> DELETED: admin deletes
  FAILED --> QUEUED: admin retries
```

| From | To | Who | Condition | Side effects |
|---|---|---|---|---|
| QUEUED | EXTRACTING | worker | job taken | job status visible on admin page |
| EXTRACTING | INDEXED / PARTIAL_REVIEW / FAILED | worker | page results | ExtractionReport saved; chunks of good pages searchable |
| PARTIAL_REVIEW | INDEXED | KNOWLEDGE_ADMIN | no page left in NEEDS_REVIEW | approved pages become searchable |
| INDEXED | SUPERSEDED | system | a newer version is indexed | chunks stay searchable but `current = false`; conflict rule C1 still sees them |
| any | DELETED | KNOWLEDGE_ADMIN | | chunks and vectors removed; the row stays for history |
| FAILED | QUEUED | KNOWLEDGE_ADMIN | retry | |

Any other move returns 409 `ILLEGAL_MOVE`.

## Page review states

`INDEXED` (good) · `NEEDS_REVIEW` → `APPROVED` (searchable) or `REJECTED` (never searchable) · `SKIPPED` (blank).
Only a KNOWLEDGE_ADMIN moves a page out of NEEDS_REVIEW.

## Query pipeline (not a stored lifecycle; the stages that `query_stage` records)

```mermaid
flowchart LR
  G[guard] --> P[plan: rewrite + route]
  P -->|DOCS / BOTH| RV[retrieve_vector] --> F[fuse]
  P -->|DOCS / BOTH| RB[retrieve_bm25] --> F
  F --> RR[rerank]
  P -->|SQL / BOTH| T[tool]
  RR --> GEN[generate]
  T --> GEN
  P -->|CONVERSATIONAL| GEN
  GEN --> V[validate: citations, grounding, schema]
  V --> O[outcome rules, contract 11]
  G -->|blocked| O
```

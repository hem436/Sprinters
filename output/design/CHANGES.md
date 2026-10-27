# Design changes

The contracts were frozen at the design review. Every later change is one entry here, newest first, written
with the `design-change` skill. The panel may ask why we changed something: this file is the answer.

| Id | Time | Contract and version | What changed | Why (evidence) | Parts affected (owners told) | Agreed by |
|---|---|---|---|---|---|---|
| DC-3 | 27 Oct, 14:15 | 11 v1.0 to v1.1 | The planner's route reason (`PLANNER`, `RULE_OVERRIDE`, `ROUTE_FALLBACK`, `RULE_GREETING`), the C1 conflicts found and `conflict_not_shown` go into the `detail` of the `plan` and `validate` stage rows; no new column | the drill-down must show the router decision (8.2) and a conflict the answer hid | Arka (writes), Sinngam (store unchanged), Hemant (drill-down shows the stage detail) | proposed by Arka; Sinngam and Hemant to confirm |
| DC-2 | 27 Oct, 14:15 | 11 v1.0 to v1.1 | A repaired answer call (rule V3) is stored as purpose `answer` with prompt version `answer-v1-repair`; the list of purposes does not change | the store allows only route, answer, judge, ocr, embed; a new purpose made every repaired query fail to save (found by running the agent against the real recorder) | Arka, Sinngam | proposed by Arka; Sinngam to confirm |
| DC-1 | 27 Oct, 14:15 | 11 v1.0 to v1.1 | New reason code `OK_SMALLTALK` (outcome SUCCESS) for a greeting answered by a fixed text, checked after BLOCKED_SAFETY and before NO_EVIDENCE | a greeting has no evidence to cite, so rule 7 marked it FAILED UNGROUNDED_ANSWER | Arka (rule), Sinngam (one copy of the rules, see open item), Hemant (dashboard label) | proposed by Arka; Sinngam to confirm |

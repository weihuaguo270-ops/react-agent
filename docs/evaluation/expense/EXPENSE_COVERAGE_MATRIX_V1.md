# Expense Coverage Matrix v1

## Scope and Ruleset

- Ruleset under test: `expense-policy-sim-v1` / `project_simulation_v1`.
- Existing `business_cases.json` (8 cases) remains the immutable S1 legacy baseline.
- New rule cases are in `fixtures/expense/business_cases_expanded_v1.json`: 41 dev, 12 golden, and 16 held_out policy/contract cases, plus 16 workflow scenario descriptors. They are a candidate suite, not part of the S1 pass rate.
- `held_out` cases in the candidate suite are authored from the published policy and this matrix. Do not run them during rule development. They are visible project fixtures, so “held out” means process-isolated from tuning, not access-controlled.
- This matrix records project simulation behavior. It is not a statement about real employers.

The rule fixture is executable through `src/react_agent/apps/expense/candidate_eval.py` and `scripts/eval/acceptance/run_expense_candidate_eval.py`; the Workflow scenario descriptors remain pending Workflow support. The runner deep-copies the named template, replaces `$case_id` with the case `id`, overlays `overrides` (including explicit `null` values), then compares `expected`. `expected.valid`, `review_required`, and `error_code` describe Claim validation; `decision` describes the final rule decision; `policy_decision` describes a direct reject returned by validation. A declared `known_gap` is not silently counted as a pass; a narrowly identified gap can be reported as resolved only when its expected behavior now matches, while preserving the original fixture and held-out hash.

## Rule and Case Coverage

| Rule family | Required coverage | Candidate IDs | Current status / test layer |
|---|---|---|---|
| Common Claim envelope | Required fields, category discriminator, amount type/range, ISO date, receipt reference, pre-approval reference, currency | `D-COMMON-*`, `G-COMMON-*`, `H-COMMON-*` | Contract unit tests; add shared Claim model in S2 |
| Receipt priority and exception | Receipt present, missing receipt, missing receipt reference, affidavit with and without manager approval; receipt rule takes priority over amount approval | `D-RECEIPT-*`, `G-RECEIPT-*`, `H-RECEIPT-*` | Rule tests now; formal approval evidence binding belongs to Workflow |
| Meal | Normal, 200 USD boundary, over-limit without/with pre-approval, required fields, entertainment weekday/weekend, regular weekend meal | `D-MEAL-*`, `G-MEAL-*`, `H-MEAL-*` | Contract + decision tests; missing-purpose entertainment is a known policy/implementation mismatch |
| Transport | Each allowed tuple, unsupported tuple, invalid enum, 500 USD boundary, flight quote missing/exactly +20%/above +20% | `D-TRANS-*`, `G-TRANS-*`, `H-TRANS-*` | Rule contract now; quote adapter availability/version tests wait for Workflow simulation service |
| Lodging | City directory and tier match, unknown city, nights/date consistency, nightly ceiling, total/night calculation, market quote missing and +20% boundary | `D-LODG-*`, `G-LODG-*`, `H-LODG-*` | Rule contract now; market directory and quote provenance need explicit S2/Workflow contract |
| Office purchase | PO missing, format invalid, simulated match, unverified PO, item type missing, amount boundary | `D-PO-*`, `G-PO-*`, `H-PO-*` | Rule contract now; registry lookup/outage tests wait for simulated procurement adapter |
| Cross-cutting policy | Base/non-base currency, monthly threshold and e-group threshold, business-critical trip pre-approval, unsupported/unknown policy facts | `D-CROSS-*`, `G-CROSS-*`, `H-CROSS-*` | Contract tests; calendar/holiday behavior remains “no automatic exemption”, with no calendar service |
| Decision/approval lifecycle | Review routing, approval pending/approve/reject/escalate, stale decision hash, changed Claim version, no approval for rejected/needs-review decisions | `W-APPROVAL-*` | Workflow integration/E2E; not executable in the current legacy evaluator |
| Persistence and idempotency | Draft create/update, submit freeze, repeated submit, same-key replay, cross-claim key conflict, version conflict, append-only audit, no side effect on blocked permission | `W-STORE-*`, `W-AUDIT-*` | Storage/permission integration; requires S2 shared contracts and parent Workflow |
| Human handoff | Reason-code routing, duplicate active case, assignment/claim/resolve/escalate, handoff resolution bound to claim version and decision hash | `W-HANDOFF-*` | Workflow integration/E2E; human case service is not implemented |

## Split Policy

| Split | Use | Case authoring rule |
|---|---|---|
| `dev` | Fast feedback while implementing S2/Workflow | Exercise all known branches, invalid inputs, and boundary pairs. Expected outcomes come from the policy, not the current implementation. |
| `golden` | Stable acceptance regression | Curated policy invariants and previously reviewed combinations; changes require an explicit policy-version update. |
| `held_out` | Final candidate check | At least one independently selected case for every category and cross-cutting family; do not tune rules against its output. Run only after dev/golden stabilize. |

Canonical held-out manifest hash: `sha256({'policy_version': policy_version, 'cases': held_out_cases})` after parsing the JSON and serializing with UTF-8, `ensure_ascii=false`, sorted object keys, and separators `(',', ':')` is `f8801e86298c59260b8d510df9c965f953bcbc5430672fefdbb50b523457da36`.

Do not interpret case count as coverage by itself. Acceptance requires every published rule to map to a case, every result class (`approve_*`, `reject_*`, `needs_review`, `invalid_claim`) to be exercised, and every state-changing Workflow transition to have both allowed and blocked-path evidence.

## Workflow Scenarios to Add with Implementation

| ID family | Scenarios | Expected invariant |
|---|---|---|
| `W-STORE-*` | Create draft; update draft increments version; submit freezes version; update submitted Claim conflicts; duplicate create/submit idempotent replay | A submitted Claim version is immutable; retries do not create duplicate tasks or decisions. |
| `W-APPROVAL-*` | Decision requires review; approval pending; approve; reject; escalate; stale `decision_hash`; stale Claim version; permission denied | Only a matching approval record can change Claim terminal state; escalation stays non-terminal. |
| `W-AUDIT-*` | Record decision, approval, status transition, denied write, idempotent replay | Events are append-only, linked to Claim/version/request, and denied writes leave business state unchanged. |
| `W-HANDOFF-*` | Route by reason code; repeat same handoff; claim/assign; resolve; escalate; resolve against stale version/hash | One active case per Claim/version/reason; case completion alone never approves a Claim. |
| `W-ADAPTER-*` | Quote and procurement registry match, miss, stale data, timeout/unavailable | Unknown or unavailable evidence routes to review/fail-closed; never silently passes. |

## Known Policy/Implementation Questions Exposed by the Matrix

1. `expense_policy_v2.json` says entertainment without a business purpose is `reject_policy`, while `validate_claim()` currently reports missing required fields as `invalid_claim` first. S2 must encode the chosen precedence and add a regression case.
2. The formal validator currently does not enforce the transport category limit, even though the published policy sets 500 USD per claim. S2 must apply that limit in the shared Decision contract and retain the boundary cases.
3. The policy says quote/procurement facts come from simulation services, but current validation accepts claim-supplied `market_price*` and `purchase_order_verified`. Workflow adapters must become the trusted source; these fields must not be treated as verified merely because a client supplied them.
4. Holiday policy says there is no automatic exemption, but there is no holiday calendar input/service. Do not invent a calendar outcome in v1; test that ordinary weekend date alone does not reject, and defer holiday-specific cases until a calendar contract exists.
5. Lodging `city_tiers` includes aliases and `other`, while the directory currently maps only a subset. Unknown destination remains `needs_review`; unsupported directory labels need a contract decision before expanding the city fixture.

## Exit Gates

- Every policy row above maps to a stable case ID or an explicitly deferred Workflow ID.
- New fixture schema validates, and the old 8-case S1 fixture/report hashes remain unchanged.
- Dev/golden expectations are reviewed before running implementation candidates; held-out expectations are frozen and hashed before candidate tuning.
- S2 contract tests and Workflow tests are added in their respective implementation batches; this planning fixture is not reported as passing until those tests actually execute.

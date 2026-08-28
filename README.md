# LedgerLens AI

LedgerLens AI is an AI-assisted finance operations controller designed for automated payment reconciliation. It identifies operational exceptions across multi-source financial data, investigates ambiguous cases using isolated AI, and enforces strict, deterministic safety policies before simulating any controlled financial action.

## Why LedgerLens?

Financial reconciliation involves merging payment records, merchant ledgers, bank settlements, fees, and adjustments. These sources often disagree due to timing lags, duplicates, missing settlements, or unexpected fees. Purely rule-based systems struggle to resolve genuinely ambiguous cases, but granting an AI unrestricted authority over financial actions is fundamentally unsafe. 

LedgerLens solves this through a layered architecture:
- **Deterministic logic handles provable cases** mathematically and safely.
- **AI investigates only genuinely ambiguous cases** that rules cannot resolve.
- **Policy remains authoritative over every final action**, regardless of AI recommendations.

> **Deterministic when possible. AI when necessary. Human when uncertain.**

## Core Architecture

```text
Data
 ↓
Dataset Validator
 ↓
Deterministic Reconciliation Engine
 ↓
 ├── Deterministic cases ──────────────┐
 │                                      ↓
 └── Ambiguous cases → AI Investigator
                         ↓
                  Policy Engine
                         ↓
              Controlled Action Simulator
                         ↓
                    Audit Trail
```

**AI recommendations are advisory.**
**The Policy Engine is authoritative.**
**All actions are simulated.**

## What It Detects

| Classification        | Description                                                       |
| --------------------- | ----------------------------------------------------------------- |
| `EXACT_MATCH`         | Payment and settlement match perfectly                            |
| `FEE_DEDUCTION`       | Discrepancy is fully explained by standard processing fees        |
| `TIMING_LAG`          | Settlement is expected but outside the immediate timing window    |
| `DUPLICATE`           | Multiple bank settlements reference the same payment identifier   |
| `MISSING_SETTLEMENT`  | Settlement is absent after the maximum acceptable time window     |
| `UNKNOWN_TRANSACTION` | Settlement cannot be matched to any known merchant ledger entry   |
| `REFUND_ADJUSTMENT`   | Ambiguous adjustment verified as a valid operational refund       |
| `LEDGER_MISMATCH`     | Severe financial mismatch requiring immediate human investigation |

The first six are deterministic classifications. Only ambiguous adjustment or mismatch scenarios are routed to the AI Investigator.

## AI Investigator

**IMPORTANT AI DISCLOSURE:** The current repository uses `MockAIProvider`, a deterministic provider designed for reproducible testing and demonstration. 

The AI Investigator:
- receives only the operational evidence package
- has no access to ground truth or evaluation labels
- cannot access another case's evidence
- produces structured, enum-bound recommendations
- is strictly validated before policy evaluation
- supports bounded retries and safe failure
- cannot directly execute financial actions

**AI validation results in this repository measure the deterministic mock provider and integration framework. They should not be interpreted as real-world LLM accuracy.**

## Policy Engine — The Safety Boundary

The Policy Engine is the absolute safety boundary of the system. It enforces the rule that an AI recommendation can never bypass deterministic financial controls. 

Every case flows through:
`AI recommendation` → `deterministic policy evaluation` → `authorized action`

For example, on a critical `LEDGER_MISMATCH` case:
* **AI recommendation:** `AUTO_RESOLVE`
* **Policy evaluation:** `LEDGER_MISMATCH` requires strict escalation
* **Final action:** `ESCALATE`

**The AI cannot bypass the Policy Engine.**

## Controlled Action Simulation

LedgerLens does not directly mutate financial state:
- No real financial operation occurs.
- No payment, refund, or settlement API is called.
- Actions are strictly simulated in-memory.
- Idempotency prevents duplicate execution.
- Conflicting actions are blocked safely.
- Unexpected failures degrade gracefully to `FAILED_SAFE`.

## Audit Trail

Every decision produces an operational trace log. The audit trail is:
- **append-only**
- **read-only** from the frontend
- **deterministic**, generating identifiers without UUID randomness or system-clock dependence
- securely linked to policy evaluation and execution outcomes

## Evaluation

LedgerLens strictly separates runtime execution from evaluation.
- `evaluator.py` is an offline evaluation component.
- Hidden ground truth is completely isolated from the runtime workflow.
- The runtime system never reads `ground_truth.json`.
- Deterministic engine performance is measured against the hidden labels.
- AI results currently use the deterministic mock provider and are reported as mock-provider validation, not real-world LLM benchmark results.

### HOLDOUT Evaluation Snapshot
The offline evaluator produces the following verified figures on the 1,000-case holdout dataset:
- 1,000 total cases (950 deterministic, 50 AI-routed)
- 100% deterministic classification accuracy
- 100% routing accuracy
- 100% action accuracy
- 100% end-to-end classification accuracy
- 0% exact-match false-positive rate
- 0% false escalation rate
- 5% additional resolution coverage from AI

*Mock AI validation: 100% on the controlled evaluation fixtures.*

## Dataset Coverage

| Split | Total Cases | Deterministic | AI |
| --- | --- | --- | --- |
| DEV | 100 | 95 | 5 |
| VALIDATION | 500 | 475 | 25 |
| HOLDOUT | 1000 | 950 | 50 |

## Frontend

The LedgerLens frontend is a read-only React + Vite + TypeScript application powered by static workflow JSON artifacts. It relies on no backend API, no database, and no real financial integrations. 

Available views include:
- **Overview:** High-level metrics and dataset summaries
- **Case Explorer:** Powerful filtering across reference IDs, routes, classifications, and status
- **Case Details:** Complete operational lifecycle tracing
- **AI Investigations:** Focused metrics on AI reasoning and recommendations
- **Policy & Safety:** Transparent visualization of AI safety overrides
- **Audit Trail:** Append-only operational trace logs

A persistent `SIMULATION MODE` warning guarantees operators understand the read-only, simulated nature of the environment.

## Demo

To run the curated end-to-end deterministic demonstration from the repository root:

```bash
set PYTHONPATH=src
python -m ledgerlens.workflow --demo
```

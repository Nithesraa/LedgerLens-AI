# LedgerLens AI

### Deterministic-first AI Finance Operations Controller

LedgerLens AI is a finance operations prototype built for the **Razorpay AI Buildathon — Track 04**.

It is designed to reconcile multi-source payment data, identify operational exceptions, investigate genuinely ambiguous cases with AI, enforce deterministic financial safety policies, and simulate the resulting actions through a completely controlled execution layer.

> **Deterministic when possible. AI when necessary. Human when uncertain.**

The most important architectural principle is simple:

**AI can recommend. Policy decides. Execution is always controlled.**

---

## Why LedgerLens?

Financial reconciliation systems cannot safely depend on an AI model to make unrestricted decisions.

A payment discrepancy may be:

- A normal payment
- A standard processing-fee deduction
- A settlement arriving later than expected
- A duplicate settlement
- A missing settlement
- An unknown transaction
- A refund adjustment
- A ledger mismatch requiring investigation

LedgerLens therefore does **not** send every transaction to AI.

Instead, it follows a layered decision architecture:

```text
                    OPERATIONAL DATA
                           │
                           ▼
                 ┌───────────────────┐
                 │ Dataset Validator │
                 └─────────┬─────────┘
                           │
                           ▼
              ┌─────────────────────────┐
              │ Deterministic Engine    │
              │                         │
              │ Rules • Decimal Math    │
              │ Tolerances • Timelines  │
              └────────────┬────────────┘
                           │
                  ┌────────┴─────────┐
                  │                  │
            Deterministic        Ambiguous
                  │                  │
                  │                  ▼
                  │          ┌───────────────┐
                  │          │ AI Investigator│
                  │          └───────┬───────┘
                  │                  │
                  └────────┬─────────┘
                           ▼
                 ┌───────────────────┐
                 │   Policy Engine   │
                 │                   │
                 │ AI is advisory.   │
                 │ Policy is         │
                 │ authoritative.    │
                 └─────────┬─────────┘
                           │
                           ▼
              ┌─────────────────────────┐
              │ Controlled Action       │
              │ Simulator               │
              │                         │
              │ Simulated • Idempotent  │
              │ Failure-safe            │
              └────────────┬────────────┘
                           │
                           ▼
                    ┌─────────────┐
                    │ Audit Trail │
                    │  Read-only  │
                    └─────────────┘
```

---

# Core Architecture

## 1. Dataset Validator

The validator checks the incoming operational datasets before reconciliation begins.

It protects the rest of the pipeline from malformed or structurally inconsistent input.

---

## 2. Deterministic Reconciliation Engine

The deterministic engine resolves cases that can be safely classified using explicit financial and operational rules.

It uses:

* `Decimal` arithmetic for monetary calculations
* Explicit monetary tolerance
* Deterministic settlement windows
* Deterministic evaluation dates
* Structural validation
* Duplicate detection
* Cross-source consistency checks
* Stable ordering for reproducible output

Typical deterministic classifications include:

| Classification        | Meaning                                                           |
| --------------------- | ----------------------------------------------------------------- |
| `EXACT_MATCH`         | Payment and settlement reconcile exactly                          |
| `FEE_DEDUCTION`       | Settlement is explained by the configured fee                     |
| `TIMING_LAG`          | Settlement is expected but outside the immediate timing condition |
| `DUPLICATE`           | Multiple settlements are associated with the same payment         |
| `MISSING_SETTLEMENT`  | Expected settlement is not present                                |
| `UNKNOWN_TRANSACTION` | Bank transaction cannot be associated safely                      |

The engine does not use AI to solve cases that can already be resolved deterministically.

---

# 3. AI Investigator

Only cases explicitly routed to:

```text
AI_INVESTIGATOR
```

are passed to the AI investigation layer.

The investigator receives an evidence package containing operational information such as:

* Payment information
* Merchant ledger entries
* Bank settlements
* Adjustments
* Configuration
* Deterministic calculations
* Decision trace

The AI does **not** receive:

* Hidden ground truth
* Evaluation labels
* Expected classifications
* Expected actions
* Expected routes
* Other cases' evidence

The AI output is validated before it can influence the next stage.

### AI validation includes

* Structured output validation
* Enum validation
* Evidence-reference validation
* Confidence threshold validation
* Bounded retry handling
* Safe failure handling

Low-confidence or failed investigations are safely escalated.

---

# 4. Policy Engine

The Policy Engine is the **authoritative safety boundary**.

The AI Investigator can recommend an action, but it cannot authorize that action.

The Policy Engine evaluates the complete case and determines the final authorized action.

### Policy examples

| Case                      | Policy     | Authorized Action |
| ------------------------- | ---------- | ----------------- |
| `EXACT_MATCH`             | `ALLOW`    | `AUTO_RESOLVE`    |
| `FEE_DEDUCTION`           | `ALLOW`    | `AUTO_RESOLVE`    |
| `TIMING_LAG`              | `MONITOR`  | `MONITOR`         |
| `MISSING_SETTLEMENT`      | `ESCALATE` | `ESCALATE`        |
| `DUPLICATE`               | `DENY`     | `ESCALATE`        |
| `UNKNOWN_TRANSACTION`     | `DENY`     | `ESCALATE`        |
| Valid `REFUND_ADJUSTMENT` | `ALLOW`    | `AUTO_RESOLVE`    |
| `LEDGER_MISMATCH`         | `ESCALATE` | `ESCALATE`        |
| AI review failure         | `ESCALATE` | `ESCALATE`        |
| Low confidence            | `ESCALATE` | `ESCALATE`        |
| Invalid evidence          | `DENY`     | `ESCALATE`        |

### Important safety invariant

A particularly important demonstration is the `LEDGER_MISMATCH` case.

If AI recommends:

```text
AUTO_RESOLVE
```

the Policy Engine can override that recommendation:

```text
AI Recommendation
       │
       ▼
AUTO_RESOLVE
       │
       ▼
Policy Engine
       │
       ▼
SAFETY OVERRIDE
       │
       ▼
ESCALATE
```

This demonstrates that AI is **not the final authority**.

---

# 5. Controlled Action Simulator

LedgerLens deliberately does not perform real financial operations.

The execution layer is a controlled in-memory simulator.

Every execution explicitly represents:

```text
simulated = true
real_financial_action = false
```

The simulator provides:

* Idempotency
* Duplicate suppression
* Conflict detection
* Failure-safe behavior
* Append-only audit records
* Deterministic audit identifiers

Example execution states include:

```text
SIMULATED_EXECUTED
DUPLICATE_SUPPRESSED
CONFLICT_BLOCKED
FAILED_SAFE
```

No payment gateway, banking API, or financial mutation endpoint is called.

---

# 6. Audit Trail

Every operational decision can produce an audit record containing information such as:

* Operational reference
* Route
* Classification
* Policy decision
* Authorized action
* Execution status
* Policy version
* Evaluation date
* Evidence references
* Deterministic audit identifier

Audit identifiers are generated deterministically rather than using random UUID generation.

The audit layer is designed to be:

**Append-only • Deterministic • Read-only**

---

# End-to-End Workflow

The complete runtime flow is:

```text
CSV Operational Data
        │
        ▼
Dataset Validation
        │
        ▼
Deterministic Reconciliation
        │
        ├──────────────► Deterministic Result
        │
        ▼
   AI Investigator
        │
        ▼
AI Investigation Result
        │
        └──────────────┐
                       ▼
                 Policy Engine
                       │
                       ▼
             Controlled Simulator
                       │
                       ▼
                  Audit Trail
```

The workflow is implemented by:

```text
ledgerlens.workflow
```

---

# Demo

LedgerLens includes a curated demo containing **8 representative decision paths**.

The demo dynamically discovers representative cases from the DEV dataset.

The eight paths demonstrate:

1. `EXACT_MATCH`
2. `FEE_DEDUCTION`
3. `TIMING_LAG`
4. `MISSING_SETTLEMENT`
5. `DUPLICATE`
6. `UNKNOWN_TRANSACTION`
7. AI `REFUND_ADJUSTMENT`
8. AI `LEDGER_MISMATCH` → Policy Override → `ESCALATE`

This allows the complete safety architecture to be demonstrated without hardcoding transaction IDs into the UI.

---

# Quickstart

## Backend

From the repository root:

### Windows PowerShell

```powershell
$env:PYTHONPATH="src"
```

### Windows CMD

```cmd
set PYTHONPATH=src
```

Then run the demo:

```bash
python -m ledgerlens.workflow --demo
```

---

## Run a single case

```bash
python -m ledgerlens.workflow --case RZP_DEV_000001
```

The single-case workflow produces the unified case representation through:

```text
Reconciliation
      ↓
AI Investigation (when required)
      ↓
Policy
      ↓
Simulation
      ↓
Audit
```

---

## Run a complete dataset split

### DEV

```bash
python -m ledgerlens.workflow --split dev
```

### VALIDATION

```bash
python -m ledgerlens.workflow --split validation
```

### HOLDOUT

```bash
python -m ledgerlens.workflow --split holdout
```

An optional audit output can be generated:

```bash
python -m ledgerlens.workflow --split dev --audit-output outputs/dev_audit.json
```

---

# Frontend Demo

LedgerLens includes a React + Vite frontend for visualizing the operational workflow.

The frontend is intentionally read-only.

It consumes the pre-generated workflow artifacts from:

```text
frontend/public/data/
```

No backend web server is required.

## Start the frontend

```bash
cd frontend
npm install
npm run dev
```

Then open the local Vite development URL displayed by Vite.

---

# Frontend

The dashboard provides several operational views.

### Overview

Provides:

* Dataset summary
* Deterministic vs AI routing
* Reconciliation outcomes
* AI investigation metrics
* Policy distribution
* Controlled execution metrics
* Safety architecture
* 8-case demo story

### Case Explorer

Allows operators to:

* Search operational references
* Filter by route
* Filter by classification
* Filter by policy decision
* Filter by execution status
* Navigate through paginated cases

### Case Details

Provides the complete lifecycle of an individual case:

```text
Reconciliation
      ↓
AI Investigation
      ↓
Policy Decision
      ↓
Execution
      ↓
Audit
```

AI is explicitly marked as advisory.

---

### AI Investigations

Shows only cases that required AI investigation.

The interface exposes:

* Confidence
* Investigation status
* Subtype
* Reasoning
* Evidence references
* Recommended action

---

### Policy & Safety

Visualizes the authoritative policy layer.

The UI explicitly communicates:

> **AI recommendations are advisory. The Policy Engine is authoritative.**

AI overrides are highlighted when the final policy action differs from the AI recommendation.

---

### Audit Trail

Provides a read-only operational log.

Audit records cannot be modified through the UI.

The interface explicitly identifies the audit trail as:

```text
READ ONLY
```

---

# Dataset Scale

The project includes three operational splits:

| Split      | Total Cases | Deterministic | AI |
| ---------- | ----------: | ------------: | -: |
| DEV        |         100 |            95 |  5 |
| VALIDATION |         500 |           475 | 25 |
| HOLDOUT    |       1,000 |           950 | 50 |

The same pipeline operates across all three datasets.

---

# Evaluation

LedgerLens contains a separate offline evaluation framework.

The evaluator is intentionally separated from the runtime workflow.

```text
Runtime
──────────────
Operational Data
      ↓
Reconciliation
      ↓
AI
      ↓
Policy
      ↓
Simulation


Offline Evaluation
──────────────────
Engine Output
      +
Hidden Ground Truth
      ↓
Evaluator
      ↓
Metrics
```

The runtime system never reads the hidden ground truth.

---

## Run Evaluation

For example:

```bash
python -m ledgerlens.evaluator --split holdout
```

The evaluation framework measures deterministic classification, AI investigation performance, routing behavior, and end-to-end outcomes.

---

# HOLDOUT Evaluation Snapshot

The validated HOLDOUT benchmark contains:

```text
1,000 total cases
950 deterministic cases
50 AI-routed cases
```

The evaluation results show:

```text
Deterministic Classification Accuracy    100%
AI Classification Accuracy               100%
AI Subtype Accuracy                      100%
AI Action Accuracy                       100%
End-to-End Classification Accuracy       100%
End-to-End Action Accuracy               100%
```

The AI layer adds resolution coverage for cases that the deterministic engine intentionally leaves for investigation.

---

# Safety Architecture

LedgerLens is deliberately designed around the principle that an AI model should not directly control financial operations.

### The system enforces:

```text
AI Recommendation
       │
       ▼
Validation
       │
       ▼
Deterministic Policy
       │
       ▼
Authorized Action
       │
       ▼
Controlled Simulation
       │
       ▼
Audit
```

Not:

```text
AI
 │
 └──► Execute Money Movement
```

This distinction is central to the design.

---

# Security Boundaries

The runtime architecture intentionally contains no:

* Real payment API integration
* Banking API integration
* Database
* External financial mutation
* Authentication service
* Production payment credentials
* Ground-truth access
* Evaluation dependency
* Network-dependent AI provider
* Random execution state
* System-clock-dependent reconciliation logic

The current AI provider is a deterministic mock provider designed for reproducible testing and demonstration.

---

# Ground Truth Isolation

Hidden evaluation labels are isolated under:

```text
evaluation/
```

The operational runtime does not consume these labels.

The frontend also does not receive or expose them.

This separation prevents evaluation information from becoming an accidental runtime input.

---

# Determinism

Reproducibility is a first-class design requirement.

The system avoids runtime dependence on:

* `uuid4`
* `Math.random()`
* `Date.now()`
* `datetime.now()`
* Batch insertion order
* Audit-trail length

Financial calculations use explicit `Decimal` arithmetic and deterministic configuration values.

Audit identifiers are generated deterministically.

The same operational input should therefore produce the same logical output.

---

# Testing

The repository contains extensive automated coverage across the backend and frontend.

## Backend

Run:

```bash
pytest tests/ -v --basetemp="$env:TEMP\pytest-razorpay-final"
```

The backend regression suite has been verified with:

```text
240 passed
```

---

## Frontend

From `frontend/`:

```bash
npm run lint
```

```bash
npx vitest run
```

```bash
npm run build
```

The frontend test suite currently contains:

```text
39 passed
```

---

# Project Structure

```text
LedgerLens/
│
├── data/
│   ├── dev/
│   ├── validation/
│   └── holdout/
│
├── evaluation/
│   ├── dev/
│   ├── validation/
│   └── holdout/
│
├── src/
│   └── ledgerlens/
│       ├── config.py
│       ├── validator.py
│       ├── generator.py
│       ├── reconciliation.py
│       ├── evaluator.py
│       ├── ai_investigator.py
│       ├── policy.py
│       └── workflow.py
│
├── tests/
│
├── frontend/
│   ├── public/
│   │   └── data/
│   │       ├── dev.json
│   │       ├── validation.json
│   │       └── holdout.json
│   │
│   └── src/
│       ├── adapters/
│       ├── components/
│       ├── hooks/
│       ├── pages/
│       ├── types/
│       └── ...
│
├── scripts/
│
└── README.md
```

---

# Design Principles

LedgerLens is built around five principles:

### 1. Deterministic First

If a case can be resolved mathematically and safely, do not invoke AI.

### 2. AI Only Where Needed

AI is reserved for genuinely ambiguous operational cases.

### 3. Policy Is Authoritative

AI recommendations never bypass deterministic safety policy.

### 4. Execution Is Simulated

This prototype cannot move real money.

### 5. Audit Is Read-Only

Every decision should be traceable without allowing the UI to alter financial history.

---

# Technology Stack

## Backend

* Python 3.10+
* Standard library
* `dataclasses`
* `Decimal`
* `asyncio`
* Pytest

## Frontend

* React 19
* TypeScript
* Vite
* Vitest
* CSS

No large UI framework or backend web framework is required.

---

# What This Prototype Demonstrates

LedgerLens is not intended to claim production payment-processing capability.

Instead, it demonstrates how an AI-assisted finance operations system can be architected with strong safety boundaries.

The key demonstration is:

```text
Can AI help investigate financial exceptions?
                │
                ▼
              YES
                │
                ▼
Should AI have unrestricted authority?
                │
                ▼
               NO
                │
                ▼
        Deterministic Policy
                │
                ▼
     Controlled Final Action
                │
                ▼
          Complete Audit
```

This architecture allows AI to contribute where deterministic rules are insufficient while retaining deterministic control over final financial decisions.

---

# Razorpay Buildathon

**Track:** AI Finance / Finance Operations

**Project:** LedgerLens AI

**Core concept:**

> **Deterministic when possible. AI when necessary. Human when uncertain.**

LedgerLens demonstrates an AI-assisted reconciliation controller that combines deterministic financial reasoning, isolated AI investigation, authoritative policy enforcement, simulated execution, and auditable decision tracing.

---

## Project Status

**Submission Ready**

```text
✓ Dataset validation
✓ Deterministic reconciliation
✓ AI investigation
✓ AI evidence isolation
✓ Policy engine
✓ Safety overrides
✓ Controlled execution
✓ Idempotency
✓ Deterministic audit trail
✓ End-to-end workflow
✓ Offline evaluation
✓ React operations dashboard
✓ Case explorer
✓ AI investigation view
✓ Policy & safety view
✓ Audit trail
✓ Responsive UI
✓ Automated tests
✓ Production frontend build
```

---

## Final Principle

**LedgerLens does not ask AI to control money.**

It gives AI a carefully bounded role in investigating ambiguity, while deterministic policy remains responsible for deciding what is actually allowed.

> **AI recommends.
> Policy decides.
> Execution simulates.
> Audit remembers.**

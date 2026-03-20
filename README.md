# Team Claude Lab

## Participants
- Peeranut Ngaorungsri (Project Lead)
- Visit Tangjitsamarnmitr (PM)
- Zhen Jiang Ong (Presenter)
- Kyle Allen Cueto (AI Developer)

## Scenario
Scenario 5: Agentic AI for Trade Finance Document Validation

## What We Built
A fully working Trade Finance Document Validation Agent powered by the Claude Agent SDK. The agent autonomously validates Invoice and Purchase Order (PO) documents before approving cross-border money transfers — catching missing fields, line-item calculation errors, and inter-document discrepancies without human review.

The agent exposes three MCP tools: `validate_invoice`, `validate_po`, and `cross_validate_invoice_po`. It reads both documents, runs each tool in sequence, then delivers a structured APPROVED/REJECTED recommendation with supporting evidence. Sample documents (`sample_invoice.json`, `sample_po.json`) representing a Singapore-to-Thailand trade transaction are included and run end-to-end.

Everything in `main.py` runs. The validation logic, agent loop, and MCP server wiring are all functional. The only thing that is scaffolding is the sample data — in production these would be pulled from a document management system rather than static JSON files.

## Challenges Attempted
| # | Challenge | Status | Notes |
|---|---|---|---|
| 1 | Invoice individual validation (fields + line item math) | Done | Catches missing fields, qty × price mismatches, currency checks |
| 2 | PO individual validation (fields + Incoterms check) | Done | Validates delivery fields and known Incoterms codes |
| 3 | Cross-validation Invoice vs PO | Done | Checks PO reference, buyer/seller, currency, amount, payment terms, line items |
| 4 | Agentic loop with Claude Agent SDK + MCP | Done | Agent autonomously decides tool call order and compiles final report |

## Key Decisions
**Claude Agent SDK over raw API** — We used `claude_agent_sdk` with an MCP server instead of calling the Anthropic API directly. This let us define tools as Python functions with `@tool` decorators and have the agent manage the multi-step validation loop automatically, saving significant boilerplate.

**Three separate tools instead of one** — Splitting into `validate_invoice`, `validate_po`, and `cross_validate_invoice_po` gave the agent clear, composable steps and made each validation independently testable. A single monolithic tool would have been harder to debug and less reusable.

**Strict approval gate** — All three validations must pass (zero errors) for a transfer to be APPROVED. A warning-only result still gets approved, mirroring real trade finance practice where advisory warnings don't block payment.

## How to Run It

```bash
# 1. Install dependencies (Python 3.11+ required)
pip install -r requirements.txt

# 2. Set your Anthropic API key
export ANTHROPIC_API_KEY=your_api_key_here

# 3. Run the validation agent against the sample documents
python main.py
```

No Docker needed. The agent will validate `sample_invoice.json` against `sample_po.json` and print a full APPROVED/REJECTED report to stdout.

## If We Had Another Day
1. **PDF/image ingestion** — Accept scanned invoices and POs via Claude's vision capability instead of requiring pre-parsed JSON
2. **Web UI** — A simple upload form where users can drop two documents and see the validation result in a browser
3. **Database persistence** — Log every validation run with timestamps and outcomes for audit trail purposes
4. **Multi-currency FX check** — Validate that invoice amounts converted at current rates stay within PO tolerance
5. **Webhook integration** — Push APPROVED decisions directly to a payment gateway rather than printing to stdout

The biggest thing held together with tape: sample data is hardcoded file paths. A real system needs document retrieval from an ERP or DMS.

## How We Used Claude Code
Claude Code scaffolded the entire `main.py` in one shot from a plain-English description of what the agent should do. The `@tool` decorator pattern, MCP server wiring, and async agent loop were all generated correctly on the first attempt — that alone saved an hour of SDK spelunking.

The biggest time save was the cross-validation logic. Describing the seven business rules (PO reference match, buyer/seller match, currency, amount ceiling, payment terms, line items) in natural language and getting working Python immediately was the standout moment. What surprised us most was how well it handled edge cases like case-insensitive name comparison and floating-point tolerance for line item totals — details we hadn't explicitly asked for.

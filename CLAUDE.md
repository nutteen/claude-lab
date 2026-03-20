# CLAUDE.md

## Project

**Trade Finance Document Validation Agent** — a hackathon project that uses the Anthropic Claude Agent SDK to validate trade finance documents (Invoices and Purchase Orders) before approving cross-border money transfers.

The agent orchestrates three MCP tools to:
1. Validate Invoice documents for completeness and calculation accuracy
2. Validate Purchase Order documents for completeness and calculation accuracy
3. Cross-validate Invoice against PO to detect discrepancies (buyer/seller mismatch, currency mismatch, over-invoicing, etc.)

Final output is a structured APPROVED / REJECTED recommendation.

## Tech Stack

- **Language:** Python 3
- **AI Framework:** `claude-agent-sdk` (Anthropic's Claude Agent SDK with MCP server support)
- **Async runtime:** `anyio`
- **Key SDK types:** `ClaudeSDKClient`, `ClaudeAgentOptions`, `create_sdk_mcp_server`, `@tool` decorator

## Commands

### Install dependencies
```bash
pip install -r requirements.txt
```

### Run the agent
```bash
python main.py
```
This validates `sample_invoice.json` against `sample_po.json` using the agent.

## Architecture

### System diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                         main.py                                 │
│                                                                 │
│  sample_invoice.json ──┐                                        │
│  sample_po.json ───────┼──► validate_trade_documents()          │
│                        │         │                              │
│                        │         ▼                              │
│                        │   create_sdk_mcp_server()              │
│                        │   registers 3 @tool functions          │
│                        │         │                              │
│                        │         ▼                              │
│                        │   ClaudeSDKClient(options)             │
│                        │         │                              │
│                        └────────►│ client.query(prompt)         │
│                                  │                              │
└──────────────────────────────────┼─────────────────────────────┘
                                   │
                    ┌──────────────▼──────────────┐
                    │      Claude API (LLM)        │
                    │   model: claude-sonnet-4-6   │
                    │   max_turns: 20              │
                    └──────────────┬──────────────┘
                                   │ tool calls (MCP)
                    ┌──────────────▼──────────────┐
                    │    Local MCP Server          │
                    │   "trade-finance-tools"      │
                    │                              │
                    │  ┌──────────────────────┐   │
                    │  │  validate_invoice    │   │
                    │  ├──────────────────────┤   │
                    │  │  validate_po         │   │
                    │  ├──────────────────────┤   │
                    │  │  cross_validate_     │   │
                    │  │    invoice_po        │   │
                    │  └──────────────────────┘   │
                    └──────────────┬──────────────┘
                                   │ JSON results
                    ┌──────────────▼──────────────┐
                    │   Streamed output to stdout  │
                    │   AssistantMessage (text)    │
                    │   ResultMessage (stop reason)│
                    └─────────────────────────────┘
```

### Validation sequence

```
Claude Agent
    │
    ├─1─► validate_invoice(invoice_json)
    │         └─► checks: required fields, line math, currency, bank details
    │             returns: {is_valid, errors[], warnings[], validation_summary}
    │
    ├─2─► validate_po(po_json)
    │         └─► checks: required fields, line math, Incoterms
    │             returns: {is_valid, errors[], warnings[], validation_summary}
    │
    ├─3─► cross_validate_invoice_po(invoice_json, po_json)
    │         └─► checks: PO ref, buyer, seller, currency, amount, terms, line items
    │             returns: {cross_validation_result: APPROVED|REJECTED, ...}
    │
    └─4─► Final report with APPROVED / REJECTED recommendation
```

### Entry point
`main.py` — single-file application. No build step required.

### Tools (MCP)
Three async tool functions decorated with `@tool` and registered on a local MCP server:

| Tool | Input | Key checks |
|------|-------|-----------|
| `validate_invoice` | `invoice_json: str` | 12 required fields, line item math (±0.01), currency allowlist, bank detail completeness |
| `validate_po` | `po_json: str` | 12 required fields, line item math (±0.01), Incoterms code recognition |
| `cross_validate_invoice_po` | `invoice_json: str`, `po_json: str` | PO ref match, buyer/seller/currency match, over-invoicing check, payment terms, line item descriptions |

Agent is capped at `max_turns=20` with `permission_mode="bypassPermissions"`.

## Sample Data

- `sample_invoice.json` — Invoice INV-2024-0042, GlobalTech Exports Ltd. → Siam Commerce Co., USD 25,000
- `sample_po.json` — Purchase Order PO-2024-0099, matching the invoice above

## Key Business Rules

**Invoice validation errors (hard failures):**
- Missing any of 12 required fields
- Line item `quantity × unit_price ≠ total` (tolerance: ±0.01)
- Sum of line item totals ≠ `total_amount`

**PO validation errors (hard failures):**
- Missing any of 12 required fields
- Same line item math checks

**Cross-validation (any discrepancy → REJECTED):**
- `invoice.po_reference` must match `po.po_number`
- Buyer name, seller name, currency must match (case-insensitive)
- Invoice total must not exceed PO total (over-invoicing check)
- Payment terms must match
- Line item descriptions must match exactly (set comparison, lowercase)

## Environment

Requires `ANTHROPIC_API_KEY` to be set in the environment:
```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

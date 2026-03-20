# CLAUDE.md — Trade Finance Document Validation Agent

## Project Overview
An agentic AI system built with the **Claude Agent SDK** that validates trade finance documents (Invoices and Purchase Orders) before approving cross-border money transfers. The agent runs a structured 3-step validation pipeline using MCP tools.

## Tech Stack
- **Language**: Python 3.11+
- **AI**: Claude Agent SDK (`claude-agent-sdk`) + Anthropic API
- **Async runtime**: `anyio`
- **Tools protocol**: MCP (Model Context Protocol) via `create_sdk_mcp_server`

## Project Structure
```
claude-lab/
├── main.py                      # Agent + all 3 validation tools
├── requirements.txt             # Dependencies
├── sample_invoice_success.json  # Valid invoice (expect APPROVED)
├── sample_invoice_failure.json  # Invalid invoice (expect REJECTED)
├── sample_po_success.json       # Valid PO
└── sample_po_failure.json       # Invalid PO with mismatches
```

## How to Run

```bash
# Install dependencies
pip install -r requirements.txt

# Set API key
export ANTHROPIC_API_KEY=your_key_here

# Run against success scenario
python main.py

# To test failure scenario, edit the bottom of main.py:
# anyio.run(validate_trade_documents, "sample_invoice_failure.json", "sample_po_failure.json")
```

## Architecture

### Agent Flow
1. Agent receives both invoice and PO document content
2. Calls `validate_invoice` tool → checks fields, line item math, bank details
3. Calls `validate_po` tool → checks fields, delivery info, Incoterms
4. Calls `cross_validate_invoice_po` tool → checks PO reference, buyer/seller, currency, amount, payment terms, line items
5. Returns structured APPROVED/REJECTED report

### MCP Tools (`main.py`)
| Tool | Purpose |
|------|---------|
| `validate_invoice` | Validates invoice fields, line item calculations, bank details |
| `validate_po` | Validates PO fields, delivery date/address, Incoterms |
| `cross_validate_invoice_po` | Cross-checks invoice against PO for discrepancies |

### Approval Logic
- **APPROVED**: All 3 tools pass with zero errors (warnings are allowed)
- **REJECTED**: Any single error in any tool → transfer blocked

## Key Validation Rules
- Line item totals must equal `quantity × unit_price` (±0.01 tolerance)
- Invoice `total_amount` must equal sum of all line item totals
- Invoice amount must not exceed PO amount (over-invoicing check)
- Buyer name, seller name, currency, and payment terms must match between Invoice and PO
- `po_reference` in invoice must match `po_number` in PO
- Valid currencies: USD, EUR, GBP, JPY, CNY, SGD, THB, HKD

## When Modifying This Project
- All validation logic lives in `main.py` — tools are decorated with `@tool`
- To add a new validation rule, add it inside the relevant tool function and append to `errors` or `warnings`
- `errors` block approval; `warnings` do not
- To test with new documents, create JSON files matching the existing sample structure and pass them to `validate_trade_documents(invoice_path, po_path)`
- Do not change `permission_mode` from `"bypassPermissions"` — the agent needs to call its own MCP tools freely

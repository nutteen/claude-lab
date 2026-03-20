"""
Trade Finance Validation — MCP Server

Exposes the trade finance validation agent as MCP tools so any MCP client
(Claude Desktop, another claude-agent-sdk agent, or any MCP-compatible app)
can call validation as a tool.

Exposed tools:
  - validate_trade_documents   full pipeline (invoice + PO → APPROVED/REJECTED)
  - validate_invoice           individual invoice validation
  - validate_po                individual PO validation

Run modes:
  python mcp_server.py            # stdio  (Claude Desktop / claude-agent-sdk)
  python mcp_server.py --sse      # HTTP SSE on http://localhost:8000/sse
"""

import argparse
import json
import sys
import anthropic
from mcp.server.fastmcp import FastMCP

# Parse port early so FastMCP is initialized with the correct value.
_parser = argparse.ArgumentParser(add_help=False)
_parser.add_argument("--port", type=int, default=8000)
_known, _ = _parser.parse_known_args()

mcp = FastMCP("trade-finance-validator", host="0.0.0.0", port=_known.port)
_client = anthropic.Anthropic()


# ── Shared validation logic ───────────────────────────────────────────────────

def _validate_invoice_logic(data: dict) -> dict:
    errors, warnings = [], []

    required_fields = {
        "invoice_number": "Invoice number",
        "invoice_date": "Invoice date",
        "seller_name": "Seller name",
        "seller_address": "Seller address",
        "buyer_name": "Buyer name",
        "buyer_address": "Buyer address",
        "po_reference": "PO reference number",
        "line_items": "Line items",
        "total_amount": "Total amount",
        "currency": "Currency",
        "payment_terms": "Payment terms",
        "bank_details": "Bank/payment details",
    }
    for field, label in required_fields.items():
        if not data.get(field):
            errors.append(f"Missing required field: {label} ({field})")

    line_items = data.get("line_items", [])
    if not isinstance(line_items, list) or len(line_items) == 0:
        errors.append("Line items must be a non-empty list")
    else:
        for i, item in enumerate(line_items, start=1):
            for f in ["description", "quantity", "unit_price", "total"]:
                if f not in item:
                    errors.append(f"Line item {i}: missing '{f}'")
            if all(k in item for k in ["quantity", "unit_price", "total"]):
                calculated = round(item["quantity"] * item["unit_price"], 2)
                if abs(calculated - item["total"]) > 0.01:
                    errors.append(
                        f"Line item {i} total mismatch: "
                        f"{item['quantity']} × {item['unit_price']} = {calculated}, "
                        f"but total shows {item['total']}"
                    )

    if line_items and "total_amount" in data:
        line_sum = round(sum(item.get("total", 0) for item in line_items), 2)
        if abs(line_sum - data["total_amount"]) > 0.01:
            errors.append(
                f"Invoice total ({data['total_amount']}) does not match "
                f"sum of line items ({line_sum})"
            )

    valid_currencies = ["USD", "EUR", "GBP", "JPY", "CNY", "SGD", "THB", "HKD"]
    if data.get("currency") and data["currency"] not in valid_currencies:
        warnings.append(f"Non-standard currency code: {data['currency']}")

    if isinstance(data.get("bank_details"), dict):
        for bf in ["bank_name", "account_number", "swift_code"]:
            if not data["bank_details"].get(bf):
                warnings.append(f"Bank detail incomplete: missing '{bf}'")

    return {
        "document_type": "Invoice",
        "invoice_number": data.get("invoice_number", "N/A"),
        "is_valid": len(errors) == 0,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "errors": errors,
        "warnings": warnings,
        "validation_summary": ("PASSED" if not errors else "FAILED")
        + f" — {len(errors)} error(s), {len(warnings)} warning(s)",
    }


def _validate_po_logic(data: dict) -> dict:
    errors, warnings = [], []

    required_fields = {
        "po_number": "PO number",
        "po_date": "PO date",
        "buyer_name": "Buyer name",
        "buyer_address": "Buyer address",
        "seller_name": "Seller name",
        "seller_address": "Seller address",
        "line_items": "Line items",
        "total_amount": "Total amount",
        "currency": "Currency",
        "payment_terms": "Payment terms",
        "delivery_date": "Delivery date",
        "delivery_address": "Delivery address",
    }
    for field, label in required_fields.items():
        if not data.get(field):
            errors.append(f"Missing required field: {label} ({field})")

    line_items = data.get("line_items", [])
    if not isinstance(line_items, list) or len(line_items) == 0:
        errors.append("Line items must be a non-empty list")
    else:
        for i, item in enumerate(line_items, start=1):
            for f in ["description", "quantity", "unit_price", "total"]:
                if f not in item:
                    errors.append(f"Line item {i}: missing '{f}'")
            if all(k in item for k in ["quantity", "unit_price", "total"]):
                calculated = round(item["quantity"] * item["unit_price"], 2)
                if abs(calculated - item["total"]) > 0.01:
                    errors.append(
                        f"Line item {i} total mismatch: "
                        f"{item['quantity']} × {item['unit_price']} = {calculated}, "
                        f"but total shows {item['total']}"
                    )

    if line_items and "total_amount" in data:
        line_sum = round(sum(item.get("total", 0) for item in line_items), 2)
        if abs(line_sum - data["total_amount"]) > 0.01:
            errors.append(
                f"PO total ({data['total_amount']}) does not match "
                f"sum of line items ({line_sum})"
            )

    known_incoterms = ["EXW","FCA","CPT","CIP","DAP","DPU","DDP","FAS","FOB","CFR","CIF"]
    if data.get("incoterms"):
        code = data["incoterms"].split()[0].upper()
        if code not in known_incoterms:
            warnings.append(f"Unrecognized Incoterms code: {code}")
    else:
        warnings.append("Incoterms not specified (recommended for trade finance)")

    return {
        "document_type": "Purchase Order",
        "po_number": data.get("po_number", "N/A"),
        "is_valid": len(errors) == 0,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "errors": errors,
        "warnings": warnings,
        "validation_summary": ("PASSED" if not errors else "FAILED")
        + f" — {len(errors)} error(s), {len(warnings)} warning(s)",
    }


def _ai_compare(field_name: str, value_a: str, value_b: str) -> dict:
    """Call Claude directly to semantically compare two field values."""
    response = _client.messages.create(
        model="claude-opus-4-6",
        max_tokens=512,
        thinking={"type": "adaptive"},
        system=(
            "You are a trade finance compliance expert. Determine whether two field values "
            "from different documents refer to the same real-world entity. Consider "
            "abbreviations, legal suffixes (Ltd/Limited/LLC), address formats, product "
            "name variations, and common paraphrasing. "
            "Respond ONLY with a JSON object — no extra text."
        ),
        messages=[{
            "role": "user",
            "content": (
                f"Field: {field_name}\n"
                f"Value A: {value_a}\n"
                f"Value B: {value_b}\n\n"
                "Do these refer to the same entity?\n"
                'Respond: {"match": true/false, "confidence": "high/medium/low", "reasoning": "..."}'
            ),
        }],
    )
    raw = next(b.text for b in response.content if b.type == "text")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = {"match": False, "confidence": "low", "reasoning": raw}
    return {"field": field_name, "value_a": value_a, "value_b": value_b, **parsed}


def _run_full_pipeline(invoice: dict, po: dict) -> dict:
    """Run all three validation stages and return the combined report."""

    # Stage 1 & 2 — individual document validation
    inv_result = _validate_invoice_logic(invoice)
    po_result = _validate_po_logic(po)

    # Stage 3a — deterministic cross-checks
    det_matches, det_discrepancies = [], []

    inv_po_ref = (invoice.get("po_reference") or "").strip()
    po_number = (po.get("po_number") or "").strip()
    if inv_po_ref == po_number:
        det_matches.append(f"PO reference matches: {po_number}")
    else:
        det_discrepancies.append(
            f"PO reference mismatch — Invoice: '{inv_po_ref}', PO: '{po_number}'"
        )

    inv_currency = invoice.get("currency", "")
    po_currency = po.get("currency", "")
    if inv_currency == po_currency:
        det_matches.append(f"Currency matches: {inv_currency}")
    else:
        det_discrepancies.append(
            f"Currency mismatch — Invoice: '{inv_currency}', PO: '{po_currency}'"
        )

    inv_total = invoice.get("total_amount", 0)
    po_total = po.get("total_amount", 0)
    if inv_total <= po_total:
        det_matches.append(f"Invoice amount ({inv_total}) within PO amount ({po_total})")
    else:
        det_discrepancies.append(
            f"Over-invoicing — Invoice: {inv_total}, PO: {po_total}"
        )

    inv_terms = (invoice.get("payment_terms") or "").strip()
    po_terms = (po.get("payment_terms") or "").strip()
    if inv_terms == po_terms:
        det_matches.append(f"Payment terms match: {inv_terms}")
    else:
        det_discrepancies.append(
            f"Payment terms mismatch — Invoice: '{inv_terms}', PO: '{po_terms}'"
        )

    # Stage 3b — AI semantic comparison
    fuzzy_fields = [
        ("buyer_name",
         invoice.get("buyer_name", ""), po.get("buyer_name", "")),
        ("seller_name",
         invoice.get("seller_name", ""), po.get("seller_name", "")),
        ("line_item_descriptions",
         "; ".join(i.get("description","") for i in invoice.get("line_items",[])),
         "; ".join(i.get("description","") for i in po.get("line_items",[]))),
        ("seller_address",
         invoice.get("seller_address",""), po.get("seller_address","")),
    ]

    ai_results = [_ai_compare(f, a, b) for f, a, b in fuzzy_fields]
    ai_discrepancies = [
        r for r in ai_results
        if not r.get("match") and r.get("confidence") in ("high", "medium")
    ]
    ai_matches = [r for r in ai_results if r.get("match")]

    # Final decision
    all_discrepancies = det_discrepancies + [
        f"[AI] {r['field']} mismatch ({r['confidence']} confidence): "
        f"'{r['value_a']}' vs '{r['value_b']}' — {r['reasoning']}"
        for r in ai_discrepancies
    ]

    docs_valid = inv_result["is_valid"] and po_result["is_valid"]
    approved = docs_valid and len(all_discrepancies) == 0

    return {
        "decision": "APPROVED" if approved else "REJECTED",
        "approved_for_transfer": approved,
        "invoice_number": invoice.get("invoice_number", "N/A"),
        "po_number": po.get("po_number", "N/A"),
        "transfer_amount": inv_total,
        "transfer_currency": inv_currency,
        "invoice_validation": inv_result,
        "po_validation": po_result,
        "cross_validation": {
            "deterministic_matches": det_matches,
            "deterministic_discrepancies": det_discrepancies,
            "ai_comparisons": ai_results,
            "ai_discrepancies": [r["field"] for r in ai_discrepancies],
        },
        "all_discrepancies": all_discrepancies,
        "recommendation": (
            f"All checks passed. Transfer of {inv_total} {inv_currency} can be APPROVED."
            if approved
            else f"{len(all_discrepancies)} discrepancy(ies) found. Do NOT transfer."
        ),
    }


# ── MCP Tools ─────────────────────────────────────────────────────────────────

@mcp.tool()
def validate_trade_documents(invoice_json: str, po_json: str) -> str:
    """
    Run the full trade finance validation pipeline on an Invoice and a Purchase Order.

    Validates each document individually (required fields, arithmetic), then
    cross-validates them — exact checks (PO reference, currency, amounts, payment
    terms) plus AI-powered semantic comparison (company names, addresses, line item
    descriptions) to catch abbreviation or formatting differences.

    Returns a JSON report with APPROVED or REJECTED decision and full reasoning.

    Args:
        invoice_json: The Invoice document as a JSON string.
        po_json:      The Purchase Order document as a JSON string.
    """
    try:
        invoice = json.loads(invoice_json)
        po = json.loads(po_json)
    except json.JSONDecodeError as e:
        return json.dumps({"error": f"Invalid JSON input: {e}"})

    result = _run_full_pipeline(invoice, po)
    return json.dumps(result, indent=2)


@mcp.tool()
def validate_invoice(invoice_json: str) -> str:
    """
    Validate a single Invoice document for trade finance compliance.

    Checks all required fields, line item arithmetic, total consistency,
    currency codes, and bank detail completeness.

    Args:
        invoice_json: The Invoice document as a JSON string.
    """
    try:
        data = json.loads(invoice_json)
    except json.JSONDecodeError as e:
        return json.dumps({"error": f"Invalid JSON input: {e}"})

    return json.dumps(_validate_invoice_logic(data), indent=2)


@mcp.tool()
def validate_po(po_json: str) -> str:
    """
    Validate a single Purchase Order (PO) document for trade finance compliance.

    Checks all required fields, line item arithmetic, total consistency,
    delivery information, and Incoterms.

    Args:
        po_json: The Purchase Order document as a JSON string.
    """
    try:
        data = json.loads(po_json)
    except json.JSONDecodeError as e:
        return json.dumps({"error": f"Invalid JSON input: {e}"})

    return json.dumps(_validate_po_logic(data), indent=2)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Trade Finance Validation MCP Server")
    parser.add_argument(
        "--sse",
        action="store_true",
        help="Run as HTTP SSE server on http://localhost:8000/sse (default: stdio)",
    )
    parser.add_argument("--port", type=int, default=8000, help="Port for SSE mode")
    args = parser.parse_args()

    if args.sse:
        print(f"Starting MCP server (SSE) on http://0.0.0.0:{args.port}/sse")
        mcp.run(transport="sse")
    else:
        mcp.run(transport="stdio")

"""
Trade Finance Document Validation Agent
Validates Invoice and Purchase Order (PO) documents before approving money transfers.
"""

import anyio
import json
import anthropic
from claude_agent_sdk import (
    tool,
    create_sdk_mcp_server,
    ClaudeSDKClient,
    ClaudeAgentOptions,
    AssistantMessage,
    TextBlock,
    ResultMessage,
)

_anthropic_client = anthropic.Anthropic()


# ─── Validation Tools ─────────────────────────────────────────────────────────

@tool(
    "validate_invoice",
    "Validate a trade finance Invoice document. Checks all required fields, "
    "line item calculations, and business rules. Input is a JSON string.",
    {"invoice_json": str},
)
async def validate_invoice(args):
    try:
        data = json.loads(args["invoice_json"])
    except json.JSONDecodeError as e:
        return {"content": [{"type": "text", "text": json.dumps({"error": f"Invalid JSON: {e}"})}]}

    errors = []
    warnings = []

    # Required top-level fields for trade finance invoices
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

    # Validate each line item
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
                        f"qty({item['quantity']}) × unit({item['unit_price']}) "
                        f"= {calculated}, but total shows {item['total']}"
                    )

    # Invoice total must equal sum of line item totals
    if line_items and "total_amount" in data:
        line_sum = round(sum(item.get("total", 0) for item in line_items), 2)
        if abs(line_sum - data["total_amount"]) > 0.01:
            errors.append(
                f"Invoice total ({data['total_amount']}) does not match "
                f"sum of line items ({line_sum})"
            )

    # Currency check
    valid_currencies = ["USD", "EUR", "GBP", "JPY", "CNY", "SGD", "THB", "HKD"]
    if data.get("currency") and data["currency"] not in valid_currencies:
        warnings.append(f"Non-standard currency code: {data['currency']}")

    # Bank details check
    if isinstance(data.get("bank_details"), dict):
        for bf in ["bank_name", "account_number", "swift_code"]:
            if not data["bank_details"].get(bf):
                warnings.append(f"Bank detail incomplete: missing '{bf}'")

    result = {
        "document_type": "Invoice",
        "invoice_number": data.get("invoice_number", "N/A"),
        "is_valid": len(errors) == 0,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "errors": errors,
        "warnings": warnings,
        "validation_summary": (
            "PASSED" if not errors else "FAILED"
        ) + f" — {len(errors)} error(s), {len(warnings)} warning(s)",
    }
    return {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]}


@tool(
    "validate_po",
    "Validate a trade finance Purchase Order (PO) document. Checks all required fields, "
    "line item calculations, and business rules. Input is a JSON string.",
    {"po_json": str},
)
async def validate_po(args):
    try:
        data = json.loads(args["po_json"])
    except json.JSONDecodeError as e:
        return {"content": [{"type": "text", "text": json.dumps({"error": f"Invalid JSON: {e}"})}]}

    errors = []
    warnings = []

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

    # Validate each line item
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
                        f"qty({item['quantity']}) × unit({item['unit_price']}) "
                        f"= {calculated}, but total shows {item['total']}"
                    )

    # PO total must equal sum of line item totals
    if line_items and "total_amount" in data:
        line_sum = round(sum(item.get("total", 0) for item in line_items), 2)
        if abs(line_sum - data["total_amount"]) > 0.01:
            errors.append(
                f"PO total ({data['total_amount']}) does not match "
                f"sum of line items ({line_sum})"
            )

    # Incoterms check (optional but common in trade finance)
    known_incoterms = ["EXW", "FCA", "CPT", "CIP", "DAP", "DPU", "DDP", "FAS", "FOB", "CFR", "CIF"]
    if data.get("incoterms"):
        incoterm_code = data["incoterms"].split()[0].upper()
        if incoterm_code not in known_incoterms:
            warnings.append(f"Unrecognized Incoterms code: {incoterm_code}")
    else:
        warnings.append("Incoterms not specified (recommended for trade finance)")

    result = {
        "document_type": "Purchase Order",
        "po_number": data.get("po_number", "N/A"),
        "is_valid": len(errors) == 0,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "errors": errors,
        "warnings": warnings,
        "validation_summary": (
            "PASSED" if not errors else "FAILED"
        ) + f" — {len(errors)} error(s), {len(warnings)} warning(s)",
    }
    return {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]}


@tool(
    "ai_compare_fields",
    "Use AI to semantically compare two field values that may represent the same thing "
    "despite different phrasing, abbreviations, or formatting. Use this for company names, "
    "addresses, and line item descriptions where exact string matching is unreliable. "
    "Returns a JSON result with match decision, confidence, and reasoning.",
    {"field_name": str, "value_a": str, "value_b": str},
)
async def ai_compare_fields(args):
    field_name = args["field_name"]
    value_a = args["value_a"]
    value_b = args["value_b"]

    response = _anthropic_client.messages.create(
        model="claude-opus-4-6",
        max_tokens=512,
        thinking={"type": "adaptive"},
        system=(
            "You are a trade finance compliance expert. Your job is to determine whether "
            "two field values from different documents refer to the same real-world entity. "
            "Consider abbreviations, legal suffixes (Ltd/Limited/LLC), address formats, "
            "product name variations, and common paraphrasing. "
            "Respond ONLY with a JSON object — no extra text."
        ),
        messages=[{
            "role": "user",
            "content": (
                f"Field: {field_name}\n"
                f"Value A: {value_a}\n"
                f"Value B: {value_b}\n\n"
                "Do these two values refer to the same entity?\n"
                "Respond with this exact JSON structure:\n"
                '{{"match": true/false, "confidence": "high/medium/low", "reasoning": "..."}}'
            ),
        }],
    )

    raw = next(b.text for b in response.content if b.type == "text")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = {"match": False, "confidence": "low", "reasoning": raw}

    result = {
        "field": field_name,
        "value_a": value_a,
        "value_b": value_b,
        **parsed,
    }
    return {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]}


@tool(
    "cross_validate_invoice_po",
    "Cross-validate an Invoice against its corresponding Purchase Order to detect "
    "discrepancies before approving a money transfer. Both inputs are JSON strings.",
    {"invoice_json": str, "po_json": str},
)
async def cross_validate_invoice_po(args):
    try:
        invoice = json.loads(args["invoice_json"])
        po = json.loads(args["po_json"])
    except json.JSONDecodeError as e:
        return {"content": [{"type": "text", "text": json.dumps({"error": f"Invalid JSON: {e}"})}]}

    discrepancies = []
    matches = []

    # ── Deterministic checks (exact values only) ──────────────────────────────

    # 1. PO reference — exact code match required
    inv_po_ref = (invoice.get("po_reference") or "").strip()
    po_number = (po.get("po_number") or "").strip()
    if inv_po_ref and po_number and inv_po_ref == po_number:
        matches.append(f"PO reference matches: {po_number}")
    else:
        discrepancies.append(
            f"PO reference mismatch — Invoice references '{inv_po_ref}', "
            f"but PO number is '{po_number}'"
        )

    # 2. Currency — exact ISO code match required
    inv_currency = invoice.get("currency", "")
    po_currency = po.get("currency", "")
    if inv_currency == po_currency:
        matches.append(f"Currency matches: {inv_currency}")
    else:
        discrepancies.append(
            f"Currency mismatch — Invoice: '{inv_currency}', PO: '{po_currency}'"
        )

    # 3. Invoice amount must not exceed PO amount
    inv_total = invoice.get("total_amount", 0)
    po_total = po.get("total_amount", 0)
    if inv_total <= po_total:
        matches.append(
            f"Invoice amount ({inv_total} {inv_currency}) is within "
            f"PO amount ({po_total} {po_currency})"
        )
    else:
        discrepancies.append(
            f"Invoice amount ({inv_total}) exceeds PO amount ({po_total}) — "
            "over-invoicing detected"
        )

    # 4. Payment terms — exact match required
    inv_terms = (invoice.get("payment_terms") or "").strip()
    po_terms = (po.get("payment_terms") or "").strip()
    if inv_terms and po_terms and inv_terms == po_terms:
        matches.append(f"Payment terms match: {inv_terms}")
    else:
        discrepancies.append(
            f"Payment terms mismatch — Invoice: '{inv_terms}', PO: '{po_terms}'"
        )

    # ── Fields requiring AI semantic comparison ────────────────────────────────
    # Return these as pending so the agent knows to call ai_compare_fields on them.

    fuzzy_checks = [
        {
            "field": "buyer_name",
            "label": "Buyer name",
            "value_invoice": invoice.get("buyer_name", ""),
            "value_po": po.get("buyer_name", ""),
        },
        {
            "field": "seller_name",
            "label": "Seller name",
            "value_invoice": invoice.get("seller_name", ""),
            "value_po": po.get("seller_name", ""),
        },
        {
            "field": "line_item_descriptions",
            "label": "Line item descriptions",
            "value_invoice": "; ".join(
                item.get("description", "") for item in invoice.get("line_items", [])
            ),
            "value_po": "; ".join(
                item.get("description", "") for item in po.get("line_items", [])
            ),
        },
        {
            "field": "seller_address",
            "label": "Seller address",
            "value_invoice": invoice.get("seller_address", ""),
            "value_po": po.get("seller_address", ""),
        },
    ]

    result = {
        "invoice_number": invoice.get("invoice_number", "N/A"),
        "po_number": po.get("po_number", "N/A"),
        "transfer_amount": inv_total,
        "transfer_currency": inv_currency,
        "deterministic_matches": matches,
        "deterministic_discrepancies": discrepancies,
        "pending_ai_checks": fuzzy_checks,
        "note": (
            "Deterministic checks complete. "
            "Call ai_compare_fields for each item in pending_ai_checks, "
            "then produce the final APPROVED / REJECTED decision."
        ),
    }
    return {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]}


# ─── Agent Setup ──────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a Trade Finance Document Validation Agent specializing in
validating financial documents for cross-border money transfers.

Your responsibilities:
1. Validate Invoice documents for completeness and accuracy using validate_invoice
2. Validate Purchase Order (PO) documents for completeness and accuracy using validate_po
3. Run cross_validate_invoice_po — this handles exact fields (PO reference, currency,
   amounts, payment terms) deterministically and returns a list of pending_ai_checks
4. For each item in pending_ai_checks, call ai_compare_fields to semantically compare
   fields like company names, addresses, and product descriptions where exact string
   matching is unreliable (e.g. "GlobalTech Exports Ltd." vs "GlobalTech Exports Limited")
5. Combine all results and produce a final APPROVED / REJECTED decision

Validation rules:
- Deterministic discrepancies (wrong PO reference, currency mismatch, over-invoicing,
  payment terms mismatch) → always a hard REJECT regardless of AI results
- AI comparison result of match=false with confidence=high → treat as discrepancy
- AI comparison result of match=false with confidence=medium/low → flag as a warning,
  request human review, do not auto-approve
- All checks must pass for APPROVED
"""


async def validate_trade_documents(
    invoice_path: str,
    po_path: str,
    case_label: str = "",
) -> None:
    """Run the trade finance validation agent on a given invoice and PO file."""

    with open(invoice_path) as f:
        invoice_data = f.read()
    with open(po_path) as f:
        po_data = f.read()

    prompt = f"""
Please validate the following trade finance documents and determine if the
money transfer should be APPROVED or REJECTED.

=== INVOICE ===
{invoice_data}

=== PURCHASE ORDER ===
{po_data}

Steps:
1. Validate the Invoice using the validate_invoice tool
2. Validate the PO using the validate_po tool
3. Cross-validate both documents using the cross_validate_invoice_po tool
4. Provide a final validation report with your APPROVED / REJECTED recommendation
"""

    server = create_sdk_mcp_server(
        "trade-finance-tools",
        tools=[validate_invoice, validate_po, cross_validate_invoice_po],
    )

    options = ClaudeAgentOptions(
        system_prompt=SYSTEM_PROMPT,
        mcp_servers={"trade-finance": server},
        max_turns=20,
        permission_mode="bypassPermissions",
        allowed_tools=[
            "mcp__trade-finance__validate_invoice",
            "mcp__trade-finance__validate_po",
            "mcp__trade-finance__cross_validate_invoice_po",
            "mcp__trade-finance__ai_compare_fields",
        ],
    )

    label = f"  {case_label}  " if case_label else "  TRADE FINANCE DOCUMENT VALIDATION AGENT  "
    border = "=" * max(60, len(label) + 4)
    print(f"\n{border}")
    print(label)
    print(f"  Invoice : {invoice_path}")
    print(f"  PO      : {po_path}")
    print(border)

    async with ClaudeSDKClient(options=options) as client:
        await client.query(prompt)
        async for message in client.receive_response():
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        print(block.text)
            elif isinstance(message, ResultMessage):
                print(f"\n{border}")
                print(f"  Done — stop reason: {message.stop_reason}")
                print(border)


# ─── Test Cases ───────────────────────────────────────────────────────────────

TEST_CASES = [
    {
        "label": "CASE 1 — SUCCESS: All information matches, transfer should be APPROVED",
        "invoice": "sample_invoice_success.json",
        "po": "sample_po_success.json",
    },
    {
        "label": "CASE 2 — FAILURE: Mandatory information mismatches, transfer should be REJECTED",
        "invoice": "sample_invoice_failure.json",
        "po": "sample_po_failure.json",
    },
]


# ─── Entry Point ──────────────────────────────────────────────────────────────

async def run_all_cases() -> None:
    for case in TEST_CASES:
        await validate_trade_documents(
            invoice_path=case["invoice"],
            po_path=case["po"],
            case_label=case["label"],
        )


if __name__ == "__main__":
    anyio.run(run_all_cases)

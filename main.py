"""
Trade Finance Document Validation Agent
Validates Invoice and Purchase Order (PO) documents before approving money transfers.
"""

import anyio
import json
from claude_agent_sdk import (
    tool,
    create_sdk_mcp_server,
    ClaudeSDKClient,
    ClaudeAgentOptions,
    AssistantMessage,
    TextBlock,
    ResultMessage,
)


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

    # 1. PO reference in invoice must match PO number
    inv_po_ref = (invoice.get("po_reference") or "").strip()
    po_number = (po.get("po_number") or "").strip()
    if inv_po_ref and po_number and inv_po_ref == po_number:
        matches.append(f"PO reference matches: {po_number}")
    else:
        discrepancies.append(
            f"PO reference mismatch — Invoice references '{inv_po_ref}', "
            f"but PO number is '{po_number}'"
        )

    # 2. Buyer name must match
    inv_buyer = (invoice.get("buyer_name") or "").strip().lower()
    po_buyer = (po.get("buyer_name") or "").strip().lower()
    if inv_buyer and po_buyer and inv_buyer == po_buyer:
        matches.append(f"Buyer name matches: {invoice.get('buyer_name')}")
    else:
        discrepancies.append(
            f"Buyer name mismatch — Invoice: '{invoice.get('buyer_name')}', "
            f"PO: '{po.get('buyer_name')}'"
        )

    # 3. Seller name must match
    inv_seller = (invoice.get("seller_name") or "").strip().lower()
    po_seller = (po.get("seller_name") or "").strip().lower()
    if inv_seller and po_seller and inv_seller == po_seller:
        matches.append(f"Seller name matches: {invoice.get('seller_name')}")
    else:
        discrepancies.append(
            f"Seller name mismatch — Invoice: '{invoice.get('seller_name')}', "
            f"PO: '{po.get('seller_name')}'"
        )

    # 4. Currency must match
    inv_currency = invoice.get("currency", "")
    po_currency = po.get("currency", "")
    if inv_currency == po_currency:
        matches.append(f"Currency matches: {inv_currency}")
    else:
        discrepancies.append(
            f"Currency mismatch — Invoice: '{inv_currency}', PO: '{po_currency}'"
        )

    # 5. Invoice amount must not exceed PO amount
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

    # 6. Payment terms must match
    inv_terms = (invoice.get("payment_terms") or "").strip()
    po_terms = (po.get("payment_terms") or "").strip()
    if inv_terms and po_terms and inv_terms == po_terms:
        matches.append(f"Payment terms match: {inv_terms}")
    else:
        discrepancies.append(
            f"Payment terms mismatch — Invoice: '{inv_terms}', PO: '{po_terms}'"
        )

    # 7. Line item descriptions should align
    inv_descriptions = {item.get("description", "").strip().lower() for item in invoice.get("line_items", [])}
    po_descriptions = {item.get("description", "").strip().lower() for item in po.get("line_items", [])}
    if inv_descriptions == po_descriptions:
        matches.append("All line item descriptions match between Invoice and PO")
    else:
        only_in_invoice = inv_descriptions - po_descriptions
        only_in_po = po_descriptions - inv_descriptions
        if only_in_invoice:
            discrepancies.append(f"Items in Invoice not found in PO: {only_in_invoice}")
        if only_in_po:
            discrepancies.append(f"Items in PO not found in Invoice: {only_in_po}")

    approved = len(discrepancies) == 0

    result = {
        "cross_validation_result": "APPROVED" if approved else "REJECTED",
        "approved_for_transfer": approved,
        "invoice_number": invoice.get("invoice_number", "N/A"),
        "po_number": po.get("po_number", "N/A"),
        "transfer_amount": inv_total,
        "transfer_currency": inv_currency,
        "matches_count": len(matches),
        "discrepancies_count": len(discrepancies),
        "matches": matches,
        "discrepancies": discrepancies,
        "recommendation": (
            f"All {len(matches)} check(s) passed. Money transfer of "
            f"{inv_total} {inv_currency} can be APPROVED."
            if approved
            else f"{len(discrepancies)} discrepancy(ies) found. "
            "Do NOT proceed with transfer until all issues are resolved."
        ),
    }
    return {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]}


# ─── Agent Setup ──────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a Trade Finance Document Validation Agent specializing in
validating financial documents for cross-border money transfers.

Your responsibilities:
1. Validate Invoice documents for completeness and accuracy
2. Validate Purchase Order (PO) documents for completeness and accuracy
3. Cross-validate Invoice against PO to detect discrepancies before approving transfers
4. Provide a clear, structured validation report with APPROVED or REJECTED decision

Always use the provided validation tools — do NOT make assumptions about document validity
without running the tools. Present your final decision clearly with supporting evidence.

For a money transfer to be approved, ALL of the following must be true:
- Invoice passes individual validation (no errors)
- PO passes individual validation (no errors)
- Cross-validation between Invoice and PO passes (no discrepancies)
"""


async def validate_trade_documents(invoice_path: str, po_path: str) -> None:
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
        ],
    )

    print("=" * 60)
    print("  TRADE FINANCE DOCUMENT VALIDATION AGENT")
    print("=" * 60)

    async with ClaudeSDKClient(options=options) as client:
        await client.query(prompt)
        async for message in client.receive_response():
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        print(block.text)
            elif isinstance(message, ResultMessage):
                print("\n" + "=" * 60)
                print(f"  Agent finished. Stop reason: {message.stop_reason}")
                print("=" * 60)


# ─── Entry Point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    anyio.run(
        validate_trade_documents,
        "sample_invoice.json",
        "sample_po.json",
    )

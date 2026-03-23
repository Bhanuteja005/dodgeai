import json
import re

from fastapi import APIRouter

from app.db import DatabaseUnavailableError
from app.db import get_cursor
from app.models import ChatRequest, ChatResponse
from app.services.gemini_service import generate_sql, summarize_answer
from app.services.query_service import execute_select
from app.services.schema_service import fetch_database_schema
from app.services.sql_guardrails import SqlGuardrailError, assert_safe_select

OFFTOPIC_MESSAGE = "This system is designed to answer questions related to the provided dataset only."

router = APIRouter(prefix="/api/chat", tags=["chat"])


def _format_preview_rows(rows: list[dict], columns: list[str]) -> str:
    lines: list[str] = []
    for row in rows:
        parts = [f"{col}={row.get(col) or '-'}" for col in columns]
        lines.append("- " + ", ".join(parts))
    return "\n".join(lines)


def _unique_node_ids(node_ids: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for node_id in node_ids:
        if node_id in seen:
            continue
        seen.add(node_id)
        unique.append(node_id)
    return unique


def _fallback_journal_lookup(question: str) -> tuple[str | None, list[str]]:
    match = re.search(r"(?:billing\s+document|billing)\D*(\d{6,})", question, flags=re.IGNORECASE)
    if not match:
        return None, []

    billing_doc = match.group(1)
    with get_cursor() as cur:
        cur.execute(
            """
            select
                payload ->> 'companyCode' as company_code,
                payload ->> 'fiscalYear' as fiscal_year,
                payload ->> 'accountingDocument' as accounting_document,
                payload ->> 'accountingDocumentItem' as accounting_document_item,
                payload ->> 'referenceDocument' as reference_document
            from o2c_entity_records
            where entity_type = 'journal_entry_items_accounts_receivable'
              and payload ->> 'referenceDocument' = %s
            order by payload ->> 'accountingDocument'
            limit 5
            """,
            (billing_doc,),
        )
        rows = cur.fetchall()

    graph_node_ids: list[str] = [f"billing_document_headers::{billing_doc}"]
    for row in rows:
        company_code = row.get("company_code")
        fiscal_year = row.get("fiscal_year")
        accounting_document = row.get("accounting_document")
        accounting_document_item = row.get("accounting_document_item")
        if company_code and fiscal_year and accounting_document and accounting_document_item:
            graph_node_ids.append(
                "journal_entry_items_accounts_receivable::"
                f"{company_code}::{fiscal_year}::{accounting_document}::{accounting_document_item}"
            )

    if not rows:
        return f"No journal entry was found linked to billing document {billing_doc}.", _unique_node_ids(graph_node_ids)

    journal_ids = sorted(
        {
            str(row["accounting_document"])
            for row in rows
            if row.get("accounting_document") is not None
        }
    )
    if not journal_ids:
        return f"No journal entry was found linked to billing document {billing_doc}.", _unique_node_ids(graph_node_ids)

    if len(journal_ids) == 1:
        return (
            f"The journal entry linked to billing document {billing_doc} is {journal_ids[0]}.",
            _unique_node_ids(graph_node_ids),
        )
    return (
        f"Billing document {billing_doc} is linked to journal entries: {', '.join(journal_ids)}.",
        _unique_node_ids(graph_node_ids),
    )


def _fallback_material_billing_lookup(question: str) -> tuple[str | None, list[str]]:
    # Match common SAP material identifiers like S8907367008620 or long numeric IDs.
    material_match = re.search(r"\b([A-Za-z]\d{6,}|\d{8,})\b", question)
    if not material_match:
        return None, []

    # Let billing-document questions flow to journal fallback.
    if re.search(r"billing\s+document", question, flags=re.IGNORECASE):
        return None, []

    material_id = material_match.group(1)
    if material_id.isdigit() and not re.search(r"material", question, flags=re.IGNORECASE):
        return None, []
    with get_cursor() as cur:
        cur.execute(
            """
            select
                payload ->> 'billingDocument' as billing_document,
                payload ->> 'billingDocumentItem' as billing_document_item,
                payload ->> 'material' as material,
                payload ->> 'netAmount' as net_amount,
                payload ->> 'billingQuantity' as billing_quantity,
                payload ->> 'billingQuantityUnit' as billing_quantity_unit
            from o2c_entity_records
            where entity_type = 'billing_document_items'
              and upper(payload ->> 'material') = upper(%s)
            order by payload ->> 'billingDocument', payload ->> 'billingDocumentItem'
            limit 12
            """,
            (material_id,),
        )
        item_rows = cur.fetchall()

    graph_node_ids: list[str] = [f"products::{material_id}"]
    for row in item_rows:
        billing_doc = row.get("billing_document")
        billing_item = row.get("billing_document_item")
        if billing_doc:
            graph_node_ids.append(f"billing_document_headers::{billing_doc}")
        if billing_doc and billing_item:
            graph_node_ids.append(f"billing_document_items::{billing_doc}::{billing_item}")

    if not item_rows:
        return f"No billing item records were found for material {material_id}.", _unique_node_ids(graph_node_ids)

    billing_docs = sorted(
        {
            str(row["billing_document"])
            for row in item_rows
            if row.get("billing_document")
        }
    )

    journal_map: dict[str, list[str]] = {}
    if billing_docs and re.search(r"journal|accounting", question, flags=re.IGNORECASE):
        with get_cursor() as cur:
            cur.execute(
                """
                select
                    payload ->> 'referenceDocument' as billing_document,
                    payload ->> 'companyCode' as company_code,
                    payload ->> 'fiscalYear' as fiscal_year,
                    payload ->> 'accountingDocument' as accounting_document,
                    payload ->> 'accountingDocumentItem' as accounting_document_item
                from o2c_entity_records
                where entity_type = 'journal_entry_items_accounts_receivable'
                  and payload ->> 'referenceDocument' = any(%s)
                """,
                (billing_docs,),
            )
            journal_rows = cur.fetchall()

        for row in journal_rows:
            billing_doc = str(row.get("billing_document") or "")
            accounting_doc = str(row.get("accounting_document") or "")
            if not billing_doc or not accounting_doc:
                continue
            journal_map.setdefault(billing_doc, []).append(accounting_doc)

            company_code = row.get("company_code")
            fiscal_year = row.get("fiscal_year")
            accounting_item = row.get("accounting_document_item")
            if company_code and fiscal_year and accounting_doc and accounting_item:
                graph_node_ids.append(
                    "journal_entry_items_accounts_receivable::"
                    f"{company_code}::{fiscal_year}::{accounting_doc}::{accounting_item}"
                )

    preview = _format_preview_rows(
        item_rows,
        [
            "billing_document",
            "billing_document_item",
            "material",
            "net_amount",
            "billing_quantity",
            "billing_quantity_unit",
        ],
    )
    summary = [
        f"Found {len(item_rows)} billing item record(s) for material {material_id}.",
        preview,
    ]

    if journal_map:
        journal_lines = []
        for billing_doc in billing_docs:
            journals = sorted(set(journal_map.get(billing_doc, [])))
            if journals:
                journal_lines.append(f"- billingDocument={billing_doc}, journalEntries={', '.join(journals)}")
        if journal_lines:
            summary.append("Related journal entries:")
            summary.extend(journal_lines)

    return "\n".join(summary), _unique_node_ids(graph_node_ids)


def _fallback_result_summary(sql_result: str) -> str:
    try:
        parsed = json.loads(sql_result)
    except json.JSONDecodeError:
        return "I could not summarize the query result right now."

    if not isinstance(parsed, list) or not parsed:
        return "No matching records were found in the dataset."

    sample = parsed[0]
    if isinstance(sample, dict):
        keys = list(sample.keys())[:4]
        preview = ", ".join(f"{k}={sample[k]}" for k in keys)
        return f"I found {len(parsed)} matching record(s). Example: {preview}."

    return f"I found {len(parsed)} matching record(s)."


@router.post("", response_model=ChatResponse)
def query_chat(payload: ChatRequest):
    try:
        schema_context = fetch_database_schema()
    except DatabaseUnavailableError:
        return ChatResponse(
            answer="Database connection is unavailable. Check backend DB URL and try again.",
            status="error",
            graph_node_ids=[],
        )

    try:
        sql_or_signal = generate_sql(payload.message, schema_context=schema_context)
    except Exception:
        fallback, node_ids = _fallback_material_billing_lookup(payload.message)
        if fallback:
            return ChatResponse(answer=fallback, status="ok", graph_node_ids=node_ids)
        fallback, node_ids = _fallback_journal_lookup(payload.message)
        if fallback:
            return ChatResponse(answer=fallback, status="ok", graph_node_ids=node_ids)
        return ChatResponse(
            answer="Chat model is temporarily unavailable or out of quota. Please retry shortly.",
            status="error",
            graph_node_ids=[],
        )

    if sql_or_signal.strip().upper() == "OFFTOPIC":
        return ChatResponse(answer=OFFTOPIC_MESSAGE, status="offtopic", graph_node_ids=[])

    try:
        safe_sql = assert_safe_select(sql_or_signal)
    except SqlGuardrailError:
        return ChatResponse(answer=OFFTOPIC_MESSAGE, status="offtopic", graph_node_ids=[])

    try:
        result = execute_select(safe_sql)
    except Exception:
        return ChatResponse(
            answer="I could not run that data query safely against the dataset. Try rephrasing your question.",
            status="error",
            graph_node_ids=[],
        )

    try:
        answer = summarize_answer(payload.message, result)
    except Exception:
        answer = _fallback_result_summary(result)

    return ChatResponse(answer=answer, status="ok", graph_node_ids=[])

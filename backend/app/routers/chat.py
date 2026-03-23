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
DOMAIN_KEYWORDS = (
    "order",
    "delivery",
    "billing",
    "invoice",
    "journal",
    "payment",
    "customer",
    "material",
    "product",
    "sales",
    "o2c",
    "node",
    "graph",
    "id",
)

router = APIRouter(prefix="/api/chat", tags=["chat"])
_CHAT_TABLE_READY = False


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


def _ensure_chat_table() -> None:
    global _CHAT_TABLE_READY
    if _CHAT_TABLE_READY:
        return

    with get_cursor() as cur:
        cur.execute(
            """
            create table if not exists chat_history (
                id bigserial primary key,
                question text not null,
                answer text not null,
                status text not null,
                strategy text not null,
                graph_node_ids jsonb not null default '[]'::jsonb,
                created_at timestamptz not null default now()
            )
            """
        )
        cur.execute("create index if not exists idx_chat_history_created_at on chat_history(created_at desc)")

    _CHAT_TABLE_READY = True


def _save_chat_history(
    question: str,
    answer: str,
    status: str,
    graph_node_ids: list[str],
    strategy: str,
) -> None:
    try:
        _ensure_chat_table()
        with get_cursor() as cur:
            cur.execute(
                """
                insert into chat_history(question, answer, status, strategy, graph_node_ids)
                values (%s, %s, %s, %s, %s::jsonb)
                """,
                (question, answer, status, strategy, json.dumps(graph_node_ids)),
            )
    except Exception:
        # Chat logging should not block answering.
        return


def _is_likely_offtopic(question: str) -> bool:
    normalized = question.lower()
    # Treat ID lookup requests as in-domain even if they omit business keywords.
    if re.search(r"\b[a-zA-Z]?\d{6,}\b", question):
        return False
    if "node" in normalized and re.search(r"\d", normalized):
        return False
    return not any(token in normalized for token in DOMAIN_KEYWORDS)


def _extract_billing_document(question: str) -> str | None:
    match = re.search(r"billing\s+document\D*(\d{6,})", question, flags=re.IGNORECASE)
    if match:
        return match.group(1)
    fallback_match = re.search(r"\b(\d{6,})\b", question)
    if fallback_match and "billing" in question.lower():
        return fallback_match.group(1)
    return None


def _fallback_generic_node_lookup(question: str) -> tuple[str | None, list[str]]:
    # Supports queries like "320000083 find this node out" or "show node B890..."
    candidates = re.findall(r"\b[A-Za-z]?\d{6,}\b", question)
    if not candidates:
        return None, []

    probe = candidates[0]
    with get_cursor() as cur:
        cur.execute(
            """
            with payload_hits as (
                select entity_type, external_id, label, 1 as score
                from o2c_entity_records r
                where exists (
                    select 1
                    from jsonb_each_text(r.payload) kv
                    where kv.value = %s
                )
            ),
            exact_id_hits as (
                select entity_type, external_id, label, 2 as score
                from o2c_entity_records
                where external_id = %s
            )
            select entity_type, external_id, label
            from (
                select * from exact_id_hits
                union all
                select * from payload_hits
            ) x
            group by entity_type, external_id, label
            order by max(score) desc, entity_type, external_id
            limit 10
            """,
            (probe, probe),
        )
        rows = cur.fetchall()

    if not rows:
        return f"No graph node was found for identifier {probe}.", []

    node_ids = [f"{row['entity_type']}::{row['external_id']}" for row in rows]
    preview = [f"- {row['entity_type']}::{row['external_id']}" for row in rows[:6]]
    answer = f"I found {len(rows)} node(s) linked to {probe}:\n" + "\n".join(preview)
    return answer, _unique_node_ids(node_ids)


def _fallback_top_products_by_billing_docs(question: str) -> tuple[str | None, list[str]]:
    normalized = question.lower()
    if not (
        "highest" in normalized
        and "product" in normalized
        and "billing" in normalized
    ):
        return None, []

    with get_cursor() as cur:
        cur.execute(
            """
            select
                payload ->> 'material' as material,
                count(distinct payload ->> 'billingDocument') as billing_doc_count
            from o2c_entity_records
            where entity_type = 'billing_document_items'
              and coalesce(payload ->> 'material', '') <> ''
            group by payload ->> 'material'
            order by billing_doc_count desc, material asc
            limit 10
            """
        )
        rows = cur.fetchall()

    if not rows:
        return "No product-to-billing associations were found in the dataset.", []

    lines = []
    graph_node_ids: list[str] = []
    for row in rows[:5]:
        material = str(row.get("material") or "")
        count = int(row.get("billing_doc_count") or 0)
        lines.append(f"- material={material}, billingDocuments={count}")
        if material:
            graph_node_ids.append(f"products::{material}")

    answer = "Products associated with the highest number of billing documents:\n" + "\n".join(lines)
    return answer, _unique_node_ids(graph_node_ids)


def _fallback_trace_billing_flow(question: str) -> tuple[str | None, list[str]]:
    normalized = question.lower()
    if not (
        ("trace" in normalized or "full flow" in normalized)
        and "billing" in normalized
    ):
        return None, []

    billing_doc = _extract_billing_document(question)
    if not billing_doc:
        return (
            "Please provide a billing document number to trace the full flow (Sales Order -> Delivery -> Billing -> Journal Entry).",
            [],
        )

    graph_node_ids: list[str] = [f"billing_document_headers::{billing_doc}"]

    with get_cursor() as cur:
        cur.execute(
            """
            select
                payload ->> 'billingDocumentItem' as billing_document_item,
                payload ->> 'referenceSdDocument' as delivery_document,
                payload ->> 'material' as material
            from o2c_entity_records
            where entity_type = 'billing_document_items'
              and payload ->> 'billingDocument' = %s
            order by payload ->> 'billingDocumentItem'
            """,
            (billing_doc,),
        )
        billing_items = cur.fetchall()

        delivery_docs = sorted({str(r.get("delivery_document")) for r in billing_items if r.get("delivery_document")})

        sales_orders: list[str] = []
        if delivery_docs:
            cur.execute(
                """
                select distinct payload ->> 'referenceSdDocument' as sales_order
                from o2c_entity_records
                where entity_type = 'outbound_delivery_items'
                  and payload ->> 'deliveryDocument' = any(%s)
                  and coalesce(payload ->> 'referenceSdDocument', '') <> ''
                order by sales_order
                """,
                (delivery_docs,),
            )
            sales_orders = [str(r.get("sales_order")) for r in cur.fetchall() if r.get("sales_order")]

        cur.execute(
            """
            select
                payload ->> 'companyCode' as company_code,
                payload ->> 'fiscalYear' as fiscal_year,
                payload ->> 'accountingDocument' as accounting_document,
                payload ->> 'accountingDocumentItem' as accounting_document_item
            from o2c_entity_records
            where entity_type = 'journal_entry_items_accounts_receivable'
              and payload ->> 'referenceDocument' = %s
            order by payload ->> 'accountingDocument', payload ->> 'accountingDocumentItem'
            """,
            (billing_doc,),
        )
        journal_rows = cur.fetchall()

    for row in billing_items:
        item = row.get("billing_document_item")
        if item:
            graph_node_ids.append(f"billing_document_items::{billing_doc}::{item}")

    for delivery_doc in delivery_docs:
        graph_node_ids.append(f"outbound_delivery_headers::{delivery_doc}")

    for order in sales_orders:
        graph_node_ids.append(f"sales_order_headers::{order}")

    for row in journal_rows:
        company_code = row.get("company_code")
        fiscal_year = row.get("fiscal_year")
        accounting_document = row.get("accounting_document")
        accounting_document_item = row.get("accounting_document_item")
        if company_code and fiscal_year and accounting_document and accounting_document_item:
            graph_node_ids.append(
                "journal_entry_items_accounts_receivable::"
                f"{company_code}::{fiscal_year}::{accounting_document}::{accounting_document_item}"
            )

    answer_lines = [f"Flow trace for billing document {billing_doc}:"]
    answer_lines.append(f"- Sales Orders: {', '.join(sales_orders) if sales_orders else 'None found'}")
    answer_lines.append(f"- Deliveries: {', '.join(delivery_docs) if delivery_docs else 'None found'}")
    answer_lines.append(f"- Billing: {billing_doc}")

    journal_docs = sorted({str(r.get("accounting_document")) for r in journal_rows if r.get("accounting_document")})
    answer_lines.append(f"- Journal Entries: {', '.join(journal_docs) if journal_docs else 'None found'}")

    return "\n".join(answer_lines), _unique_node_ids(graph_node_ids)


def _fallback_incomplete_sales_orders(question: str) -> tuple[str | None, list[str]]:
    normalized = question.lower()
    if not (
        "sales order" in normalized
        and ("broken" in normalized or "incomplete" in normalized or "delivered but not billed" in normalized or "billed without delivery" in normalized)
    ):
        return None, []

    graph_node_ids: list[str] = []
    with get_cursor() as cur:
        cur.execute(
            """
            with delivered as (
                select distinct
                    payload ->> 'referenceSdDocument' as sales_order,
                    payload ->> 'deliveryDocument' as delivery_document
                from o2c_entity_records
                where entity_type = 'outbound_delivery_items'
                  and coalesce(payload ->> 'referenceSdDocument', '') <> ''
                  and coalesce(payload ->> 'deliveryDocument', '') <> ''
            )
            select sales_order, delivery_document
            from delivered d
            where not exists (
                select 1
                from o2c_entity_records b
                where b.entity_type = 'billing_document_items'
                  and b.payload ->> 'referenceSdDocument' = d.delivery_document
            )
            order by sales_order, delivery_document
            limit 10
            """
        )
        delivered_not_billed = cur.fetchall()

        cur.execute(
            """
            select distinct
                payload ->> 'billingDocument' as billing_document,
                payload ->> 'referenceSdDocument' as delivery_document
            from o2c_entity_records b
            where b.entity_type = 'billing_document_items'
              and coalesce(b.payload ->> 'referenceSdDocument', '') <> ''
              and not exists (
                  select 1
                  from o2c_entity_records d
                  where d.entity_type = 'outbound_delivery_headers'
                    and d.payload ->> 'deliveryDocument' = b.payload ->> 'referenceSdDocument'
              )
            order by billing_document
            limit 10
            """
        )
        billed_without_delivery = cur.fetchall()

    if not delivered_not_billed and not billed_without_delivery:
        return "No broken or incomplete sales-order flow patterns were found in the current dataset sample.", []

    lines = ["Detected incomplete flow patterns:"]
    if delivered_not_billed:
        lines.append("Delivered but not billed:")
        for row in delivered_not_billed[:5]:
            sales_order = str(row.get("sales_order") or "")
            delivery_doc = str(row.get("delivery_document") or "")
            lines.append(f"- salesOrder={sales_order}, deliveryDocument={delivery_doc}")
            if sales_order:
                graph_node_ids.append(f"sales_order_headers::{sales_order}")
            if delivery_doc:
                graph_node_ids.append(f"outbound_delivery_headers::{delivery_doc}")

    if billed_without_delivery:
        lines.append("Billed without delivery:")
        for row in billed_without_delivery[:5]:
            billing_doc = str(row.get("billing_document") or "")
            delivery_doc = str(row.get("delivery_document") or "")
            lines.append(f"- billingDocument={billing_doc}, referencedDelivery={delivery_doc}")
            if billing_doc:
                graph_node_ids.append(f"billing_document_headers::{billing_doc}")

    return "\n".join(lines), _unique_node_ids(graph_node_ids)


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


def _fallback_required_queries(question: str) -> tuple[str | None, list[str], str]:
    handlers = (
        ("fallback_node_lookup", _fallback_generic_node_lookup),
        ("fallback_top_products", _fallback_top_products_by_billing_docs),
        ("fallback_trace_flow", _fallback_trace_billing_flow),
        ("fallback_incomplete_flows", _fallback_incomplete_sales_orders),
        ("fallback_material_lookup", _fallback_material_billing_lookup),
        ("fallback_journal_lookup", _fallback_journal_lookup),
    )
    for strategy, handler in handlers:
        answer, node_ids = handler(question)
        if answer:
            return answer, node_ids, strategy
    return None, [], ""


@router.post("", response_model=ChatResponse)
def query_chat(payload: ChatRequest):
    def respond(answer: str, status: str, node_ids: list[str], strategy: str) -> ChatResponse:
        _save_chat_history(
            question=payload.message,
            answer=answer,
            status=status,
            graph_node_ids=node_ids,
            strategy=strategy,
        )
        return ChatResponse(answer=answer, status=status, graph_node_ids=node_ids)

    try:
        schema_context = fetch_database_schema()
    except DatabaseUnavailableError:
        return respond(
            answer="Database connection is unavailable. Check backend DB URL and try again.",
            status="error",
            node_ids=[],
            strategy="db_unavailable",
        )

    deterministic_answer, deterministic_nodes, deterministic_strategy = _fallback_required_queries(payload.message)
    if deterministic_answer:
        return respond(
            answer=deterministic_answer,
            status="ok",
            node_ids=deterministic_nodes,
            strategy=deterministic_strategy,
        )

    if _is_likely_offtopic(payload.message):
        return respond(
            answer=OFFTOPIC_MESSAGE,
            status="offtopic",
            node_ids=[],
            strategy="offtopic_heuristic",
        )

    try:
        sql_or_signal = generate_sql(payload.message, schema_context=schema_context)
    except Exception:
        fallback, node_ids, strategy = _fallback_required_queries(payload.message)
        if fallback:
            return respond(answer=fallback, status="ok", node_ids=node_ids, strategy=strategy)
        if _is_likely_offtopic(payload.message):
            return respond(answer=OFFTOPIC_MESSAGE, status="offtopic", node_ids=[], strategy="offtopic_heuristic")
        return respond(
            answer="Chat model is temporarily unavailable or out of quota. Please retry shortly.",
            status="error",
            node_ids=[],
            strategy="gemini_unavailable",
        )

    if sql_or_signal.strip().upper() == "OFFTOPIC":
        return respond(answer=OFFTOPIC_MESSAGE, status="offtopic", node_ids=[], strategy="offtopic_llm")

    try:
        safe_sql = assert_safe_select(sql_or_signal)
    except SqlGuardrailError:
        return respond(answer=OFFTOPIC_MESSAGE, status="offtopic", node_ids=[], strategy="sql_guardrail")

    try:
        result = execute_select(safe_sql)
    except Exception:
        return respond(
            answer="I could not run that data query safely against the dataset. Try rephrasing your question.",
            status="error",
            node_ids=[],
            strategy="sql_execute_error",
        )

    try:
        answer = summarize_answer(payload.message, result)
    except Exception:
        answer = _fallback_result_summary(result)

    return respond(answer=answer, status="ok", node_ids=[], strategy="llm_sql")

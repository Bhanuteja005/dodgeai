import hashlib
import json
from pathlib import Path
from typing import Any

from app.config import settings
from app.db import get_cursor
from app.services.schema_profile import ENTITY_ID_FIELDS, RELATIONSHIP_RULES


def _stable_record_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha1(encoded).hexdigest()


def _read_jsonl_records(file_path: Path):
    with file_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                yield json.loads(line)


def _external_id(entity_type: str, payload: dict[str, Any]) -> str:
    fields = ENTITY_ID_FIELDS.get(entity_type, ())
    values = []
    for field in fields:
        value = payload.get(field)
        if value is None:
            break
        values.append(str(value))

    if values and len(values) == len(fields):
        return "::".join(values)

    return f"hash::{_stable_record_hash(payload)}"


def _label_for(entity_type: str, external_id: str) -> str:
    return f"{entity_type}:{external_id}"


def _upsert_entity(cur, entity_type: str, external_id: str, label: str, source_file: str, payload: dict[str, Any]):
    cur.execute(
        """
        insert into o2c_entity_records(entity_type, external_id, label, source_file, payload)
        values (%s, %s, %s, %s, %s)
        on conflict (entity_type, external_id)
        do update set payload = excluded.payload, label = excluded.label, source_file = excluded.source_file
        """,
        (entity_type, external_id, label, source_file, json.dumps(payload)),
    )


def _is_scalar(value: Any) -> bool:
    return isinstance(value, (str, int, float, bool))


def _build_index(cur) -> dict[str, dict[str, dict[str, set[str]]]]:
    cur.execute("select entity_type, external_id, payload from o2c_entity_records")
    rows = cur.fetchall()
    index: dict[str, dict[str, dict[str, set[str]]]] = {}
    for row in rows:
        entity_type = row["entity_type"]
        payload = row["payload"]
        entity_index = index.setdefault(entity_type, {})
        for field, value in payload.items():
            if not _is_scalar(value):
                continue
            field_index = entity_index.setdefault(str(field), {})
            matched_ids = field_index.setdefault(str(value), set())
            matched_ids.add(row["external_id"])
    return index


def _insert_edge(cur, source_id: str, target_id: str, source_type: str, target_type: str, rel: str):
    cur.execute(
        """
        insert into graph_edges(source_id, target_id, source_type, target_type, relationship_label)
        values (%s, %s, %s, %s, %s)
        on conflict (source_id, target_id, relationship_label) do nothing
        """,
        (source_id, target_id, source_type, target_type, rel),
    )


def run_ingestion(reset_graph_tables: bool = False):
    dataset_dir = settings.data_dir
    if not dataset_dir.exists():
        return {
            "status": "error",
            "entities_loaded": 0,
            "nodes_loaded": 0,
            "edges_loaded": 0,
            "notes": [f"Dataset directory not found: {dataset_dir}"],
        }

    entity_rows = 0
    edges_count = 0
    notes: list[str] = []

    with get_cursor() as cur:
        # Ingestion can scan and link a large graph; disable DB statement timeout for this transaction.
        cur.execute("set statement_timeout = '0'")

        if reset_graph_tables:
            cur.execute("truncate table graph_edges")
            cur.execute("truncate table o2c_entity_records")
            notes.append("Reset graph tables before loading.")

        for entity_dir in sorted(dataset_dir.iterdir()):
            if not entity_dir.is_dir():
                continue
            entity_type = entity_dir.name

            for part_file in sorted(entity_dir.glob("*.jsonl")):
                for payload in _read_jsonl_records(part_file):
                    external_id = _external_id(entity_type, payload)
                    label = _label_for(entity_type, external_id)
                    _upsert_entity(
                        cur,
                        entity_type=entity_type,
                        external_id=external_id,
                        label=label,
                        source_file=str(part_file.name),
                        payload=payload,
                    )
                    entity_rows += 1

        index = _build_index(cur)

        cur.execute(
            """
            select entity_type, external_id, payload
            from o2c_entity_records
            """
        )
        records = cur.fetchall()

        for record in records:
            source_type = record["entity_type"]
            payload = record["payload"]
            source_id = f"{source_type}::{record['external_id']}"

            for rule in RELATIONSHIP_RULES:
                if rule.source_entity != source_type:
                    continue

                source_value = payload.get(rule.source_field)
                if source_value is None:
                    continue

                target_external_ids = (
                    index.get(rule.target_entity, {})
                    .get(rule.target_field, {})
                    .get(str(source_value), set())
                )
                if not target_external_ids:
                    continue

                for target_external_id in target_external_ids:
                    target_id = f"{rule.target_entity}::{target_external_id}"
                    _insert_edge(
                        cur,
                        source_id=source_id,
                        target_id=target_id,
                        source_type=rule.source_entity,
                        target_type=rule.target_entity,
                        rel=rule.relationship_label,
                    )
                    edges_count += 1

        cur.execute("select count(*) as count from o2c_entity_records")
        node_count = int(cur.fetchone()["count"])

    notes.append("Relationship rules loaded from confirmed schema profile.")

    return {
        "status": "ok",
        "entities_loaded": entity_rows,
        "nodes_loaded": node_count,
        "edges_loaded": edges_count,
        "notes": notes,
    }

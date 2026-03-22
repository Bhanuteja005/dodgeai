from app.db import get_cursor


DEFAULT_COLORS = {
    "sales_order_headers": "#4f8cff",
    "outbound_delivery_headers": "#35c38f",
    "billing_document_headers": "#7a6ff0",
    "journal_entry_items_accounts_receivable": "#ff7c7c",
    "payments_accounts_receivable": "#f3b340",
}


def fetch_graph(limit: int = 800):
    with get_cursor() as cur:
        cur.execute(
            """
            select entity_type, external_id, label, payload
            from o2c_entity_records
            order by created_at desc
            limit %s
            """,
            (limit,),
        )
        node_rows = cur.fetchall()

        node_ids = {f"{r['entity_type']}::{r['external_id']}" for r in node_rows}

        if not node_ids:
            return {"nodes": [], "edges": []}

        cur.execute(
            """
            select source_id, target_id, source_type, target_type, relationship_label
            from graph_edges
                        where source_id = any(%s)
                            and target_id = any(%s)
                        order by created_at desc
                        limit %s
            """,
                        (list(node_ids), list(node_ids), limit * 3),
        )
        edge_rows = cur.fetchall()

    nodes = [
        {
            "id": f"{r['entity_type']}::{r['external_id']}",
            "type": r["entity_type"],
            "label": r["label"],
            "metadata": r["payload"],
            "color": DEFAULT_COLORS.get(r["entity_type"], "#8fb0ff"),
        }
        for r in node_rows
    ]

    edges = [
        {
            "source": r["source_id"],
            "target": r["target_id"],
            "source_type": r["source_type"],
            "target_type": r["target_type"],
            "relationship_label": r["relationship_label"],
        }
        for r in edge_rows
    ]

    return {"nodes": nodes, "edges": edges}


def fetch_node_details(node_id: str):
    entity_type, external_id = node_id.split("::", 1)

    with get_cursor() as cur:
        cur.execute(
            """
            select entity_type, external_id, label, payload
            from o2c_entity_records
            where entity_type = %s and external_id = %s
            """,
            (entity_type, external_id),
        )
        node = cur.fetchone()

        cur.execute(
            """
            select source_id, target_id, source_type, target_type, relationship_label
            from graph_edges
            where source_id = %s or target_id = %s
            """,
            (node_id, node_id),
        )
        edges = cur.fetchall()

        neighbor_ids: set[str] = set()
        for edge in edges:
            if edge["source_id"] != node_id:
                neighbor_ids.add(edge["source_id"])
            if edge["target_id"] != node_id:
                neighbor_ids.add(edge["target_id"])

        neighbors = []
        if neighbor_ids:
            parsed_neighbors = []
            for nid in neighbor_ids:
                n_type, n_external = nid.split("::", 1)
                parsed_neighbors.append((n_type, n_external, nid))

            for n_type, n_external, nid in parsed_neighbors:
                cur.execute(
                    """
                    select entity_type, external_id, label, payload
                    from o2c_entity_records
                    where entity_type = %s and external_id = %s
                    """,
                    (n_type, n_external),
                )
                neighbor = cur.fetchone()
                if neighbor:
                    neighbors.append(
                        {
                            "id": nid,
                            "type": neighbor["entity_type"],
                            "label": neighbor["label"],
                            "metadata": neighbor["payload"],
                            "color": DEFAULT_COLORS.get(neighbor["entity_type"], "#8fb0ff"),
                        }
                    )

    if not node:
        return None

    return {
        "id": node_id,
        "type": node["entity_type"],
        "label": node["label"],
        "metadata": node["payload"],
        "connections": len(edges),
        "edges": edges,
        "neighbors": neighbors,
    }

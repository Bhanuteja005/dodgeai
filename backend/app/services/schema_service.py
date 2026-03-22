from app.db import get_cursor


def fetch_database_schema() -> str:
    query = """
        select
            table_name,
            column_name,
            data_type
        from information_schema.columns
        where table_schema = 'public'
          and table_name in ('o2c_entity_records', 'graph_edges')
        order by table_name, ordinal_position;
    """
    rows: list[dict] = []
    with get_cursor() as cur:
        cur.execute(query)
        rows = list(cur.fetchall())

    lines: list[str] = []
    current_table = ""
    for row in rows:
        table = row["table_name"]
        if table != current_table:
            current_table = table
            lines.append(f"\nTable {table}:")
        lines.append(f"- {row['column_name']} ({row['data_type']})")

    return "\n".join(lines).strip()

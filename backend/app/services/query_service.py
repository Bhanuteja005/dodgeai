import json

from app.db import get_cursor


def execute_select(sql: str, limit: int = 300) -> str:
    guarded_sql = f"select * from ({sql}) as subquery limit {limit}"
    with get_cursor() as cur:
        cur.execute(guarded_sql)
        rows = cur.fetchall()
    return json.dumps(rows, indent=2, default=str)

import re

FORBIDDEN_SQL = re.compile(
    r"\b(insert|update|delete|drop|alter|truncate|create|grant|revoke|comment|copy)\b",
    re.IGNORECASE,
)


class SqlGuardrailError(ValueError):
    pass


def assert_safe_select(sql: str) -> str:
    normalized = sql.strip()
    if not normalized:
        raise SqlGuardrailError("Generated SQL is empty.")

    if FORBIDDEN_SQL.search(normalized):
        raise SqlGuardrailError("Only read-only SELECT queries are permitted.")

    statements = [s.strip() for s in normalized.split(";") if s.strip()]
    if len(statements) != 1:
        raise SqlGuardrailError("Only a single query statement is allowed.")

    statement = statements[0]
    lower = statement.lower()
    if not (lower.startswith("select") or lower.startswith("with")):
        raise SqlGuardrailError("Only SELECT or WITH ... SELECT statements are allowed.")

    return statement

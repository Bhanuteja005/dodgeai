from google import genai
from google.genai import types

from app.config import settings


def _ensure_api_key() -> None:
    if not settings.gemini_api_key.strip():
        raise RuntimeError("GEMINI_API_KEY is not configured.")


def _client() -> genai.Client:
    _ensure_api_key()
    return genai.Client(api_key=settings.gemini_api_key)


def generate_sql(user_question: str, schema_context: str) -> str:
    system_prompt = (
        "You are a PostgreSQL query planner for an Order-to-Cash dataset. "
        "Only answer by returning a valid PostgreSQL SELECT query and nothing else. "
        "If the user question is unrelated to the Order-to-Cash dataset, return exactly OFFTOPIC. "
        "Never generate SQL that modifies data. No INSERT, UPDATE, DELETE, DROP, ALTER, TRUNCATE, or CREATE. "
        "Use only these tables and columns:\n"
        f"{schema_context}"
    )

    resp = _client().models.generate_content(
        model=settings.gemini_model,
        config=types.GenerateContentConfig(system_instruction=system_prompt, temperature=0),
        contents=user_question,
    )
    return (resp.text or "").strip()


def summarize_answer(user_question: str, sql_result: str) -> str:
    system_prompt = (
        "You are a concise analyst. "
        "Answer only from the provided SQL result. "
        "If rows are empty, say that no matching records were found. "
        "Do not mention SQL or table internals."
    )
    payload = f"Question:\n{user_question}\n\nResult:\n{sql_result}"

    resp = _client().models.generate_content(
        model=settings.gemini_model,
        config=types.GenerateContentConfig(system_instruction=system_prompt, temperature=0.2),
        contents=payload,
    )
    return (resp.text or "I could not produce an answer from the result set.").strip()

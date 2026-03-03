import hashlib
import json
import logging
import os
import re
import threading
import uuid
from datetime import datetime, timezone

import anthropic
import functions_framework
import vertexai
from google.cloud import bigquery
from vertexai.language_models import TextEmbeddingInput, TextEmbeddingModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bq_client = bigquery.Client()
anthropic_client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

GCP_PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "")
BQ_DATASET = os.environ.get("BQ_DATASET", "chatbot")
BQ_TABLE = os.environ.get("BQ_TABLE", "website_content")
BQ_LOGS_TABLE = os.environ.get("BQ_LOGS_TABLE", "query_logs")

EMBED_MODEL = "text-multilingual-embedding-002"
_embedding_model = None


def _get_embeddings(texts: list[str], task_type: str = "RETRIEVAL_DOCUMENT") -> list[list[float]]:
    global _embedding_model
    if _embedding_model is None:
        vertexai.init(project=GCP_PROJECT_ID, location="europe-west4")
        _embedding_model = TextEmbeddingModel.from_pretrained(EMBED_MODEL)
    inputs = [TextEmbeddingInput(t, task_type=task_type) for t in texts]
    return [e.values for e in _embedding_model.get_embeddings(inputs)]


CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
}


def _cors_response(status_code: int, body: dict) -> tuple:
    headers = {"Content-Type": "application/json", **CORS_HEADERS}
    return (json.dumps(body), status_code, headers)


def _log_query(site_domain: str, question: str, answer: str) -> None:
    """Salva la domanda e la risposta in query_logs (eseguito in background)."""
    def _insert():
        try:
            table_ref = f"{GCP_PROJECT_ID}.{BQ_DATASET}.{BQ_LOGS_TABLE}"
            record = [{
                "id": str(uuid.uuid4()),
                "site_domain": site_domain,
                "question": question,
                "answer": answer,
                "asked_at": datetime.now(timezone.utc).isoformat(),
            }]
            errors = bq_client.insert_rows_json(table_ref, record)
            if errors:
                logger.warning("Errore salvataggio log: %s", errors)
        except Exception as e:
            logger.warning("Impossibile salvare il log: %s", e)

    threading.Thread(target=_insert, daemon=True).start()


def _normalize_domain(domain: str) -> str:
    return domain.removeprefix("www.")


def _fetch_context(site_domain: str, question: str) -> str:
    table_ref = f"`{GCP_PROJECT_ID}.{BQ_DATASET}.{BQ_TABLE}`"
    rows = []

    # ── 1. VECTOR_SEARCH semantico ────────────────────────────────────────────
    try:
        query_vector = _get_embeddings([question], task_type="RETRIEVAL_QUERY")[0]
        embedding_literal = "[" + ",".join(str(x) for x in query_vector) + "]"
        vector_query = f"""
            SELECT base.content, base.page_url, distance
            FROM VECTOR_SEARCH(
                (SELECT * FROM {table_ref}
                 WHERE site_domain = @site_domain
                   AND ARRAY_LENGTH(embedding) > 0),
                'embedding',
                (SELECT {embedding_literal} AS embedding),
                top_k => 10,
                distance_type => 'COSINE'
            )
            ORDER BY distance ASC
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("site_domain", "STRING", site_domain),
            ]
        )
        rows = list(bq_client.query(vector_query, job_config=job_config).result())
        logger.info("VECTOR_SEARCH: %d chunk per %s", len(rows), site_domain)
    except Exception as e:
        logger.warning("VECTOR_SEARCH fallito: %s — uso full-text", e)

    # ── 2. Fallback: full-text search ─────────────────────────────────────────
    if not rows:
        clean = re.sub(r"[^\w\s]", " ", question, flags=re.UNICODE)
        search_terms = " ".join(w for w in clean.split() if len(w) > 2)
        if search_terms:
            ft_query = f"""
                SELECT content, page_url
                FROM {table_ref}
                WHERE site_domain = @site_domain
                  AND SEARCH(content, @search_query)
                LIMIT 15
            """
            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("site_domain", "STRING", site_domain),
                    bigquery.ScalarQueryParameter("search_query", "STRING", search_terms),
                ]
            )
            rows = list(bq_client.query(ft_query, job_config=job_config).result())
            logger.info("Full-text fallback: %d chunk", len(rows))

    # ── 3. Fallback finale: chunk più recenti ─────────────────────────────────
    if not rows:
        recent_query = f"""
            SELECT content, page_url
            FROM {table_ref}
            WHERE site_domain = @site_domain
            ORDER BY indexed_at DESC
            LIMIT 10
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("site_domain", "STRING", site_domain),
            ]
        )
        rows = list(bq_client.query(recent_query, job_config=job_config).result())
        logger.info("Fallback recenti: %d chunk", len(rows))

    chunks = [f"[{row.page_url}]\n{row.content}" for row in rows]
    return "\n\n---\n\n".join(chunks)


@functions_framework.http
def chatbot(request):
    # Preflight CORS
    if request.method == "OPTIONS":
        return ("", 204, CORS_HEADERS)

    try:
        data = request.get_json(silent=True) or {}

        question = (data.get("question") or "").strip()
        site_domain = _normalize_domain((data.get("site_domain") or "").strip())

        if not question:
            return _cors_response(400, {"error": "Il campo 'question' è obbligatorio."})
        if not site_domain:
            return _cors_response(400, {"error": "Il campo 'site_domain' è obbligatorio."})

        context = _fetch_context(site_domain, question)

        if context:
            system_prompt = (
                f"Sei un assistente virtuale del sito {site_domain}. "
                "Rispondi alle domande degli utenti basandoti SOLO sul contenuto del sito riportato di seguito. "
                "Se la risposta non è contenuta nel testo fornito, dì che non hai informazioni sufficienti.\n\n"
                f"Contenuto del sito:\n{context}"
            )
        else:
            system_prompt = (
                f"Sei un assistente virtuale del sito {site_domain}. "
                "Non ho trovato contenuti indicizzati per questo sito. "
                "Informa l'utente che non hai informazioni sufficienti per rispondere."
            )

        response = anthropic_client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=system_prompt,
            messages=[{"role": "user", "content": question}],
        )

        answer = response.content[0].text
        logger.info("Risposta generata per %s — %d caratteri", site_domain, len(answer))

        _log_query(site_domain, question, answer)

        return _cors_response(200, {"answer": answer, "site": site_domain, "status": "success"})

    except anthropic.APIError as e:
        logger.error("Errore Anthropic API: %s", e)
        return _cors_response(502, {"error": "Errore temporaneo del servizio AI. Riprova."})
    except Exception as e:
        logger.error("Errore generico: %s", e, exc_info=True)
        return _cors_response(500, {"error": "Errore interno del server."})

"""
Caricamento manuale di contenuti in BigQuery.

Utilizzo:
    python import_content.py --domain carvaletbologna.it --file contenuto.txt
    python import_content.py --domain carvaletbologna.it --file contenuto.txt --url https://carvaletbologna.it/menu
    python import_content.py --domain carvaletbologna.it --file contenuto.txt --clear

Opzioni:
    --domain   Dominio del sito (es. carvaletbologna.it)
    --file     Percorso del file di testo (.txt o .md)
    --url      URL fittizia da associare ai chunk (default: https://{domain}/manuale)
    --clear    Elimina i record esistenti per quel dominio prima di importare
"""

import argparse
import hashlib
import logging
import os
import sys
from datetime import datetime, timezone

import vertexai
from google.cloud import bigquery
from vertexai.language_models import TextEmbeddingInput, TextEmbeddingModel

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

GCP_PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "")
BQ_DATASET = os.environ.get("BQ_DATASET", "chatbot")
BQ_TABLE = os.environ.get("BQ_TABLE", "website_content")
CHUNK_SIZE = 500
EMBED_MODEL = "text-multilingual-embedding-002"
EMBED_BATCH = 50

bq_client = bigquery.Client(project=GCP_PROJECT_ID)
TABLE_REF = f"{GCP_PROJECT_ID}.{BQ_DATASET}.{BQ_TABLE}"

_embedding_model = None


def _get_embeddings(texts: list[str], task_type: str = "RETRIEVAL_DOCUMENT") -> list[list[float]]:
    global _embedding_model
    if _embedding_model is None:
        vertexai.init(project=GCP_PROJECT_ID, location="europe-west4")
        _embedding_model = TextEmbeddingModel.from_pretrained(EMBED_MODEL)
    inputs = [TextEmbeddingInput(t, task_type=task_type) for t in texts]
    return [e.values for e in _embedding_model.get_embeddings(inputs)]


def _chunk_text(text: str, size: int) -> list[str]:
    words = text.split()
    chunks, current, length = [], [], 0
    for word in words:
        current.append(word)
        length += len(word) + 1
        if length >= size:
            chunks.append(" ".join(current))
            current, length = [], 0
    if current:
        chunks.append(" ".join(current))
    return chunks


def clear_domain(domain: str) -> None:
    query = f"DELETE FROM `{TABLE_REF}` WHERE site_domain = @domain"
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("domain", "STRING", domain)]
    )
    bq_client.query(query, job_config=job_config).result()
    logger.info("Record esistenti eliminati per %s", domain)


def import_file(domain: str, filepath: str, url: str) -> None:
    with open(filepath, encoding="utf-8") as f:
        text = f.read()

    chunks = _chunk_text(text, CHUNK_SIZE)
    if not chunks:
        logger.error("Il file è vuoto o non contiene testo.")
        sys.exit(1)

    now = datetime.now(timezone.utc).isoformat()
    records = []
    for chunk in chunks:
        chunk_id = hashlib.md5(f"{url}:{chunk}".encode()).hexdigest()
        records.append({
            "id": chunk_id,
            "site_domain": domain,
            "content": chunk,
            "page_url": url,
            "indexed_at": now,
        })

    logger.info("Generazione embeddings per %d chunk...", len(records))
    texts = [r["content"] for r in records]
    for i in range(0, len(records), EMBED_BATCH):
        batch_records = records[i:i + EMBED_BATCH]
        batch_texts = texts[i:i + EMBED_BATCH]
        try:
            vectors = _get_embeddings(batch_texts)
            for rec, vec in zip(batch_records, vectors):
                rec["embedding"] = vec
        except Exception as e:
            logger.warning("Errore embedding batch %d: %s — chunk senza embedding", i // EMBED_BATCH, e)

    import io
    import json as _json
    schema = [
        bigquery.SchemaField("id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("site_domain", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("content", "STRING"),
        bigquery.SchemaField("page_url", "STRING"),
        bigquery.SchemaField("indexed_at", "TIMESTAMP"),
        bigquery.SchemaField("embedding", "FLOAT64", mode="REPEATED"),
    ]
    data = "\n".join(_json.dumps(r) for r in records)
    job_config = bigquery.LoadJobConfig(
        schema=schema,
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
    )
    job = bq_client.load_table_from_file(
        io.BytesIO(data.encode()),
        TABLE_REF,
        job_config=job_config,
    )
    job.result()
    logger.info("Importati %d chunk per %s da '%s'", len(records), domain, filepath)


def main():
    parser = argparse.ArgumentParser(description="Importa contenuto manuale in BigQuery")
    parser.add_argument("--domain", required=True, help="Dominio del sito (es. carvaletbologna.it)")
    parser.add_argument("--file", required=True, help="Percorso del file .txt o .md")
    parser.add_argument("--url", help="URL da associare ai chunk (opzionale)")
    parser.add_argument("--clear", action="store_true", help="Elimina i record esistenti per il dominio prima di importare")
    args = parser.parse_args()

    if not os.path.isfile(args.file):
        logger.error("File non trovato: %s", args.file)
        sys.exit(1)

    url = args.url or f"https://{args.domain}/manuale"

    if args.clear:
        clear_domain(args.domain)

    import_file(args.domain, args.file, url)


if __name__ == "__main__":
    main()

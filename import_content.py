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

from google.cloud import bigquery

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

GCP_PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "")
BQ_DATASET = os.environ.get("BQ_DATASET", "chatbot")
BQ_TABLE = os.environ.get("BQ_TABLE", "website_content")
CHUNK_SIZE = 500

bq_client = bigquery.Client(project=GCP_PROJECT_ID)
TABLE_REF = f"{GCP_PROJECT_ID}.{BQ_DATASET}.{BQ_TABLE}"


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

    errors = bq_client.insert_rows_json(TABLE_REF, records)
    if errors:
        logger.error("Errori BigQuery: %s", errors)
        sys.exit(1)

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

"""
Visualizza le domande ricevute dal chatbot, raggruppate per dominio.

Utilizzo:
    python query_logs.py                          # tutte le domande, tutti i domini
    python query_logs.py --domain carvaletbologna.it
    python query_logs.py --days 7                 # ultimi 7 giorni
    python query_logs.py --domain edysma.com --days 30
"""

import argparse
import os
from datetime import datetime, timezone, timedelta

from google.cloud import bigquery

GCP_PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "")
BQ_DATASET = os.environ.get("BQ_DATASET", "chatbot")
BQ_LOGS_TABLE = os.environ.get("BQ_LOGS_TABLE", "query_logs")

bq_client = bigquery.Client(project=GCP_PROJECT_ID)
TABLE_REF = f"`{GCP_PROJECT_ID}.{BQ_DATASET}.{BQ_LOGS_TABLE}`"


def fetch_logs(domain: str | None, days: int | None) -> list:
    conditions = []
    params = []

    if domain:
        conditions.append("site_domain = @domain")
        params.append(bigquery.ScalarQueryParameter("domain", "STRING", domain))

    if days:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        conditions.append("asked_at >= @since")
        params.append(bigquery.ScalarQueryParameter("since", "TIMESTAMP", since.isoformat()))

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    query = f"""
        SELECT site_domain, question, asked_at
        FROM {TABLE_REF}
        {where}
        ORDER BY site_domain, asked_at DESC
    """
    job_config = bigquery.QueryJobConfig(query_parameters=params)
    return list(bq_client.query(query, job_config=job_config).result())


def print_grouped(rows: list) -> None:
    if not rows:
        print("Nessuna domanda trovata.")
        return

    grouped: dict[str, list] = {}
    for row in rows:
        grouped.setdefault(row.site_domain, []).append(row)

    total = 0
    for domain, entries in grouped.items():
        print(f"\n{'═' * 60}")
        print(f"  {domain}  ({len(entries)} domande)")
        print(f"{'═' * 60}")
        for entry in entries:
            ts = entry.asked_at.strftime("%d/%m/%Y %H:%M") if entry.asked_at else "—"
            print(f"  [{ts}]  {entry.question}")
        total += len(entries)

    print(f"\nTotale: {total} domande su {len(grouped)} domini")


def main():
    parser = argparse.ArgumentParser(description="Visualizza log domande chatbot")
    parser.add_argument("--domain", help="Filtra per dominio (es. carvaletbologna.it)")
    parser.add_argument("--days", type=int, help="Mostra solo gli ultimi N giorni")
    args = parser.parse_args()

    rows = fetch_logs(args.domain, args.days)
    print_grouped(rows)


if __name__ == "__main__":
    main()

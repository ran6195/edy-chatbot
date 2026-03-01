"""
Web scraper → BigQuery
Crawla le pagine di uno o più siti e carica i chunk di testo in BigQuery.

Utilizzo:
    # Siti di default (configurati in SITES)
    python scraper.py

    # Sito singolo con opzioni
    python scraper.py --site https://elettrificati.it --max-pages 50
    python scraper.py --site https://elettrificati.it --max-pages 50 \\
        --priority https://www.elettrificati.it/chi-e-elettrificati \\
        --priority https://www.elettrificati.it/promozioni

    # Sovrascrive i record esistenti per il dominio
    python scraper.py --site https://elettrificati.it --clear
"""

import argparse
import hashlib
import logging
import os
import time
import urllib.parse
import urllib.robotparser
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup
from google.cloud import bigquery

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ── Configurazione ────────────────────────────────────────────────────────────
GCP_PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "")
BQ_DATASET = os.environ.get("BQ_DATASET", "chatbot")
BQ_TABLE = os.environ.get("BQ_TABLE", "website_content")

# Siti di default (usati quando si lancia senza argomenti)
DEFAULT_SITES = [
    "https://edysma.com",
    "https://carvaletbologna.it",
    "https://snowequipmentshop.com",
]

DEFAULT_MAX_PAGES = 5
CHUNK_SIZE = 500
REQUEST_TIMEOUT = 10
CRAWL_DELAY = 1.0

HEADERS = {
    "User-Agent": "ChatbotScraper/1.0 (educational project; contact: info@example.com)"
}

# ── BigQuery ──────────────────────────────────────────────────────────────────
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


def _extract_text(soup: BeautifulSoup) -> str:
    tags = soup.find_all(["h1", "h2", "h3", "p", "li"])
    parts = []
    for tag in tags:
        text = tag.get_text(separator=" ", strip=True)
        if len(text) > 30:
            parts.append(text)
    return "\n".join(parts)


def _internal_links(soup: BeautifulSoup, base_url: str) -> list[str]:
    parsed_base = urllib.parse.urlparse(base_url)
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith("#") or href.startswith("mailto:") or href.startswith("tel:"):
            continue
        full = urllib.parse.urljoin(base_url, href)
        parsed = urllib.parse.urlparse(full)
        if parsed.netloc == parsed_base.netloc and parsed.scheme in ("http", "https"):
            clean = urllib.parse.urlunparse(parsed._replace(fragment="", query=""))
            links.append(clean)
    return links


def _robots_allowed(base_url: str) -> urllib.robotparser.RobotFileParser:
    rp = urllib.robotparser.RobotFileParser()
    rp.set_url(urllib.parse.urljoin(base_url, "/robots.txt"))
    try:
        rp.read()
    except Exception:
        pass
    return rp


def _normalize(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    return urllib.parse.urlunparse(parsed._replace(fragment="", query=""))


def clear_domain(domain: str) -> None:
    query = f"DELETE FROM `{TABLE_REF}` WHERE site_domain = @domain"
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("domain", "STRING", domain)]
    )
    bq_client.query(query, job_config=job_config).result()
    logger.info("Record esistenti eliminati per %s", domain)


def _normalize_domain(domain: str) -> str:
    return domain.removeprefix("www.")


def crawl_site(base_url: str, max_pages: int, priority_urls: list[str]) -> list[dict]:
    """Crawla il sito rispettando la priorità degli URL indicati."""
    domain = _normalize_domain(urllib.parse.urlparse(base_url).netloc)
    rp = _robots_allowed(base_url)

    # Le URL prioritarie vanno in testa alla coda, poi la home
    priority_normalized = [_normalize(u) for u in priority_urls]
    queue = list(dict.fromkeys(priority_normalized + [_normalize(base_url)]))

    visited = set()
    records = []

    session = requests.Session()
    session.headers.update(HEADERS)

    while queue and len(visited) < max_pages:
        url = queue.pop(0)
        if url in visited:
            continue
        if not rp.can_fetch(HEADERS["User-Agent"], url):
            logger.info("robots.txt blocca: %s", url)
            continue

        try:
            resp = session.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
            resp.raise_for_status()
            if "text/html" not in resp.headers.get("Content-Type", ""):
                continue

            visited.add(url)
            logger.info("[%s] (%d/%d) %s", domain, len(visited), max_pages, url)

            soup = BeautifulSoup(resp.text, "html.parser")
            text = _extract_text(soup)

            if text.strip():
                for chunk in _chunk_text(text, CHUNK_SIZE):
                    chunk_id = hashlib.md5(f"{url}:{chunk}".encode()).hexdigest()
                    records.append({
                        "id": chunk_id,
                        "site_domain": domain,
                        "content": chunk,
                        "page_url": url,
                        "indexed_at": datetime.now(timezone.utc).isoformat(),
                    })

            # Link interni: quelli delle pagine prioritarie vanno in testa
            new_links = [
                _normalize(l) for l in _internal_links(soup, url)
                if _normalize(l) not in visited and _normalize(l) not in queue
            ]
            if url in priority_normalized:
                queue = new_links + queue  # priorità: in testa
            else:
                queue.extend(new_links)

            time.sleep(CRAWL_DELAY)

        except requests.RequestException as e:
            logger.warning("Errore fetch %s: %s", url, e)

    logger.info("[%s] Pagine crawlate: %d — chunk: %d", domain, len(visited), len(records))
    return records


def upload_to_bigquery(records: list[dict]) -> None:
    if not records:
        logger.info("Nessun record da caricare.")
        return

    # Inserisce in batch da 500 righe
    batch_size = 500
    for i in range(0, len(records), batch_size):
        batch = records[i:i + batch_size]
        errors = bq_client.insert_rows_json(TABLE_REF, batch)
        if errors:
            logger.error("Errori BigQuery nel batch %d: %s", i // batch_size, errors)
            raise RuntimeError("Inserimento fallito")

    logger.info("Caricati %d record in %s", len(records), TABLE_REF)


def main():
    parser = argparse.ArgumentParser(description="Web scraper → BigQuery")
    parser.add_argument("--site", help="URL del sito da crawlare (es. https://elettrificati.it)")
    parser.add_argument("--max-pages", type=int, default=DEFAULT_MAX_PAGES, help=f"Numero massimo di pagine (default: {DEFAULT_MAX_PAGES})")
    parser.add_argument("--priority", action="append", default=[], metavar="URL", help="URL prioritario (ripetibile)")
    parser.add_argument("--clear", action="store_true", help="Elimina i record esistenti per il dominio prima di importare")
    args = parser.parse_args()

    if args.site:
        sites = [args.site]
    else:
        sites = DEFAULT_SITES

    all_records = []
    for site in sites:
        domain = urllib.parse.urlparse(site).netloc
        if args.clear:
            clear_domain(domain)
        records = crawl_site(site, args.max_pages, args.priority)
        all_records.extend(records)

    upload_to_bigquery(all_records)
    logger.info("Scraping completato. Totale chunk: %d", len(all_records))


if __name__ == "__main__":
    main()

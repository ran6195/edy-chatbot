"""
Web scraper → BigQuery
Crawla prime 5 pagine per sito e carica i chunk di testo in BigQuery.

Utilizzo:
    python scraper.py
"""

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

SITES = [
    "https://edysma.com",
    "https://carvaletbologna.it",
    "https://snowequipmentshop.com",
]

MAX_PAGES = 5
CHUNK_SIZE = 500  # caratteri
REQUEST_TIMEOUT = 10
CRAWL_DELAY = 1.0  # secondi tra le richieste

HEADERS = {
    "User-Agent": "ChatbotScraper/1.0 (educational project; contact: info@example.com)"
}

# ── BigQuery ──────────────────────────────────────────────────────────────────
bq_client = bigquery.Client(project=GCP_PROJECT_ID)
TABLE_REF = f"{GCP_PROJECT_ID}.{BQ_DATASET}.{BQ_TABLE}"


def _chunk_text(text: str, size: int) -> list[str]:
    """Divide il testo in blocchi da ~size caratteri rispettando le frasi."""
    words = text.split()
    chunks, current = [], []
    length = 0
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
    """Estrae testo da tag rilevanti."""
    tags = soup.find_all(["h1", "h2", "h3", "p", "li"])
    parts = []
    for tag in tags:
        text = tag.get_text(separator=" ", strip=True)
        if len(text) > 30:  # skip testo troppo breve
            parts.append(text)
    return "\n".join(parts)


def _internal_links(soup: BeautifulSoup, base_url: str) -> list[str]:
    """Restituisce gli URL interni trovati nella pagina."""
    parsed_base = urllib.parse.urlparse(base_url)
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith("#") or href.startswith("mailto:") or href.startswith("tel:"):
            continue
        full = urllib.parse.urljoin(base_url, href)
        parsed = urllib.parse.urlparse(full)
        if parsed.netloc == parsed_base.netloc and parsed.scheme in ("http", "https"):
            # Normalizza rimuovendo fragment e query
            clean = urllib.parse.urlunparse(parsed._replace(fragment="", query=""))
            links.append(clean)
    return links


def _robots_allowed(base_url: str) -> urllib.robotparser.RobotFileParser:
    rp = urllib.robotparser.RobotFileParser()
    robots_url = urllib.parse.urljoin(base_url, "/robots.txt")
    rp.set_url(robots_url)
    try:
        rp.read()
    except Exception:
        pass  # se non accessibile, assume tutto permesso
    return rp


def crawl_site(base_url: str) -> list[dict]:
    """Crawla il sito e restituisce una lista di record pronti per BigQuery."""
    domain = urllib.parse.urlparse(base_url).netloc
    rp = _robots_allowed(base_url)

    visited = set()
    to_visit = [base_url]
    records = []

    session = requests.Session()
    session.headers.update(HEADERS)

    while to_visit and len(visited) < MAX_PAGES:
        url = to_visit.pop(0)
        if url in visited:
            continue
        if not rp.can_fetch(HEADERS["User-Agent"], url):
            logger.info("robots.txt blocca: %s", url)
            continue

        try:
            resp = session.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
            resp.raise_for_status()
            content_type = resp.headers.get("Content-Type", "")
            if "text/html" not in content_type:
                continue

            visited.add(url)
            logger.info("[%s] Crawled %s", domain, url)

            soup = BeautifulSoup(resp.text, "html.parser")
            text = _extract_text(soup)

            if not text.strip():
                continue

            for chunk in _chunk_text(text, CHUNK_SIZE):
                chunk_id = hashlib.md5(f"{url}:{chunk}".encode()).hexdigest()
                records.append(
                    {
                        "id": chunk_id,
                        "site_domain": domain,
                        "content": chunk,
                        "page_url": url,
                        "indexed_at": datetime.now(timezone.utc).isoformat(),
                    }
                )

            # Aggiungi link interni da visitare
            for link in _internal_links(soup, url):
                if link not in visited and link not in to_visit:
                    to_visit.append(link)

            time.sleep(CRAWL_DELAY)

        except requests.RequestException as e:
            logger.warning("Errore fetch %s: %s", url, e)

    logger.info("[%s] Pagine crawlate: %d — chunk: %d", domain, len(visited), len(records))
    return records


def upload_to_bigquery(records: list[dict]) -> None:
    if not records:
        logger.info("Nessun record da caricare.")
        return

    errors = bq_client.insert_rows_json(TABLE_REF, records)
    if errors:
        logger.error("Errori BigQuery: %s", errors)
        raise RuntimeError(f"Inserimento fallito con {len(errors)} errori")
    logger.info("Caricati %d record in %s", len(records), TABLE_REF)


def main():
    all_records = []
    for site in SITES:
        records = crawl_site(site)
        all_records.extend(records)

    upload_to_bigquery(all_records)
    logger.info("Scraping completato. Totale chunk: %d", len(all_records))


if __name__ == "__main__":
    main()

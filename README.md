# Chatbot Web — Fase 1

Widget di chat AI floating, basato su RAG con BigQuery e Claude (Anthropic).

## Stack

| Componente | Tecnologia |
|---|---|
| Backend | Python 3.12, GCP Cloud Functions (gen2) |
| LLM | Claude (`claude-sonnet-4-6`) via API Anthropic |
| Database | Google BigQuery |
| Frontend | Vanilla JS (IIFE, nessuna dipendenza) |
| Scraper | Python, requests + BeautifulSoup4, noise removal |

---

## Script disponibili

| Script | Descrizione |
|---|---|
| `scraper.py` | Crawla i siti e popola BigQuery |
| `import_content.py` | Carica manualmente un file di testo in BigQuery |
| `query_logs.py` | Visualizza le domande ricevute, raggruppate per dominio |
| `setup.sh` | Deploy completo su GCP |

---

## Prerequisites

- [gcloud CLI](https://cloud.google.com/sdk/docs/install) installato e autenticato
- Python 3.12+
- Account GCP con fatturazione abilitata
- API key Anthropic

---

## Setup

### 1. Configura le variabili

```bash
cp .env.example .env
# Modifica .env con i tuoi valori reali
```

### 2. Crea il venv e installa le dipendenze

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-scraper.txt
```

### 3. Esegui lo scraper per popolare BigQuery

```bash
export $(grep -v '^#' .env | xargs)

# Siti di default (configurati in SITES)
python scraper.py

# Sito singolo con opzioni
python scraper.py --site https://esempio.it --max-pages 50

# URL prioritari (visitati per primi)
python scraper.py --site https://esempio.it --max-pages 50 \
    --priority https://esempio.it/chi-siamo \
    --priority https://esempio.it/contatti

# Sovrascrive i record esistenti per il dominio
python scraper.py --site https://esempio.it --clear
```

### 3b. Crea il search index su BigQuery (una volta sola)

```bash
bq query --use_legacy_sql=false \
  "CREATE SEARCH INDEX IF NOT EXISTS idx_content \
   ON \`${GCP_PROJECT_ID}.${BQ_DATASET}.website_content\`(content)"
```

Necessario per abilitare la full-text search nel backend.

### 4. Deploy su GCP

```bash
export $(grep -v '^#' .env | xargs)
bash setup.sh
```

Lo script abilita le API GCP, crea dataset e tabelle BigQuery, carica la API key in Secret Manager e deploya la Cloud Function.

### 5. Integra il widget nel sito

```html
<!-- Prima della chiusura di </body> — aggiungere defer -->
<script src="/path/to/chatbot-widget.js" defer></script>
```

> **Nota:** l'attributo `defer` è necessario per garantire che il widget venga inizializzato dopo il caricamento del DOM.

---

## Contenuto manuale — `import_content.py`

Per siti con poco testo o poche pagine, è possibile caricare manualmente un file `.txt` o `.md` con informazioni aggiuntive.

```bash
source .venv/bin/activate
export $(grep -v '^#' .env | xargs)

# Importa un file per un dominio
python import_content.py --domain carvaletbologna.it --file contenuto.txt

# Con URL personalizzata
python import_content.py --domain carvaletbologna.it --file menu.txt --url https://carvaletbologna.it/menu

# Sostituisce tutti i contenuti esistenti per il dominio
python import_content.py --domain carvaletbologna.it --file contenuto.txt --clear
```

I contenuti manuali si sommano a quelli dello scraper (a meno che non si usi `--clear`).

---

## Log delle domande — `query_logs.py`

Visualizza le domande ricevute dal chatbot, salvate automaticamente in BigQuery.

```bash
source .venv/bin/activate
export $(grep -v '^#' .env | xargs)

# Tutte le domande, tutti i domini
python query_logs.py

# Solo un dominio
python query_logs.py --domain carvaletbologna.it

# Ultimi 7 giorni
python query_logs.py --days 7

# Combinati
python query_logs.py --domain edysma.com --days 30
```

---

## Test

```bash
# Risposta valida
curl -X POST $FUNCTION_URL \
  -H "Content-Type: application/json" \
  -d '{"question": "Cosa fate?", "site_domain": "edysma.com"}'
# Atteso: {"answer": "...", "site": "edysma.com", "status": "success"}

# Errore 400 — question vuota
curl -X POST $FUNCTION_URL \
  -H "Content-Type: application/json" \
  -d '{"question": "", "site_domain": "edysma.com"}'

# Sito non indicizzato
curl -X POST $FUNCTION_URL \
  -H "Content-Type: application/json" \
  -d '{"question": "Ciao", "site_domain": "nonesistepiù.it"}'
```

---

## Siti target

| Sito | Categoria | Pagine | Chunk |
|---|---|---|---|
| edysma.com | Agenzia digitale | 30 | 250 |
| carvaletbologna.it | Parcheggio valet Bologna | 10 | 196 |
| snowequipmentshop.com | E-commerce attrezzature invernali | 3 | 4 |
| elettrificati.it | Wallbox e ricarica elettrica | 50 | 369 |

---

## Architettura retrieval

Il backend usa una strategia RAG (Retrieval-Augmented Generation) a due livelli:

1. **Full-text search** — `SEARCH(content, @query)` su BigQuery (richiede search index). Restituisce fino a 15 chunk che contengono le parole della domanda. I caratteri speciali (`?`, `!`, ecc.) vengono rimossi prima di passare la query a BigQuery.
2. **Fallback** — se la ricerca non trova risultati (parole troppo rare o sito con contenuto limitato), vengono restituiti i 10 chunk più recenti per dominio.

I chunk includono il titolo della pagina e l'URL come prefisso, così Claude sa sempre da quale pagina proviene ogni informazione.

### Qualità dello scraper

Lo scraper rimuove automaticamente elementi di rumore prima di estrarre il testo:
- Tag strutturali: `nav`, `footer`, `header`, `aside`, `script`, `style`, ecc.
- Elementi per classe/id: cookie banner, popup, modal, breadcrumb, sidebar, widget
- Testi duplicati nella stessa pagina (deduplicazione)

---

## Troubleshooting

**`ANTHROPIC_API_KEY` non trovata nel deploy**
→ Verifica che il secret esista in Secret Manager e che il Compute SA abbia il ruolo `roles/secretmanager.secretAccessor`.

**BigQuery: nessun risultato**
→ Controlla che lo scraper sia stato eseguito e che `site_domain` corrisponda esattamente all'hostname del sito (es. `edysma.com` senza `www.`). Il prefisso `www.` viene normalizzato automaticamente sia dallo scraper che dal backend.

**Risposte poco pertinenti / solo pagine legal o cookie**
→ Il sito probabilmente ha poche pagine crawlabili con contenuto utile. Usa `import_content.py` per caricare manualmente un file `.txt` con le informazioni rilevanti.

**Il widget non appare**
→ Assicurati che il tag `<script>` abbia l'attributo `defer`, oppure che sia posizionato prima di `</body>`.

**CORS error dal browser**
→ La Cloud Function risponde già con gli header CORS corretti. Assicurati che l'URL in `chatbot-widget.js` sia quello esatto della function (incluso il prefisso `https://`).

**Errore BigQuery `streaming buffer` con `--clear`**
→ BigQuery non permette DELETE su righe appena inserite (buffer attivo ~90 min). Attendi prima di usare `--clear`, oppure esegui senza `--clear`: i nuovi chunk (più recenti) verranno restituiti per primi dalla query.

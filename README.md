# Chatbot Web — Fase 1

Widget di chat AI floating, basato su RAG con BigQuery e Claude (Anthropic).

## Stack

| Componente | Tecnologia |
|---|---|
| Backend | Python 3.12, GCP Cloud Functions (gen2) |
| LLM | Claude (`claude-sonnet-4-6`) via API Anthropic |
| Database | Google BigQuery |
| Frontend | Vanilla JS (IIFE, nessuna dipendenza) |
| Scraper | Python, requests + BeautifulSoup4 |

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
python scraper.py
```

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

| Sito | Categoria |
|---|---|
| edysma.com | Agenzia digitale |
| carvaletbologna.it | Parcheggio valet Bologna |
| snowequipmentshop.com | E-commerce attrezzature invernali |

---

## Troubleshooting

**`ANTHROPIC_API_KEY` non trovata nel deploy**
→ Verifica che il secret esista in Secret Manager e che il Compute SA abbia il ruolo `roles/secretmanager.secretAccessor`.

**BigQuery: nessun risultato**
→ Controlla che lo scraper sia stato eseguito e che `site_domain` corrisponda esattamente all'hostname del sito (es. `edysma.com` senza `www.`).

**Il widget non appare**
→ Assicurati che il tag `<script>` abbia l'attributo `defer`, oppure che sia posizionato prima di `</body>`.

**CORS error dal browser**
→ La Cloud Function risponde già con gli header CORS corretti. Assicurati che l'URL in `chatbot-widget.js` sia quello esatto della function (incluso il prefisso `https://`).

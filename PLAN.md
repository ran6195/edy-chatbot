# Piano Implementazione: Chatbot Web - Fase 1

## Decisioni Architetturali

- **Claude**: API key Anthropic diretta (non Vertex AI), model `claude-sonnet-4-5-20251001`
- **GCP project**: già disponibile (inserire il PROJECT_ID negli script)
- **Dati test**: scraper reale (prime 5 pagine per sito), non dati inventati
- **Ambiente locale**: Python venv (`.venv`)

---

## File da Creare (in ordine)

### 1. `requirements.txt` — Dipendenze Cloud Function
```
google-cloud-bigquery==3.14.0
anthropic>=0.27.0
functions-framework==3.5.0
```

### 2. `requirements-scraper.txt` — Dipendenze scraper locale
```
requests
beautifulsoup4
google-cloud-bigquery
```

### 3. `main.py` — Cloud Function Backend
- Gestione CORS (OPTIONS + headers su ogni risposta)
- Validazione input (question non vuota, site_domain presente)
- Query BigQuery con parametro bindato (`@site_domain`, LIMIT 5)
- System prompt RAG con contesto recuperato
- Chiamata Claude via `anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])`
  - Model: `claude-sonnet-4-5-20251001`
  - max_tokens: 1024
- Risposta JSON `{answer, site, status}`
- Error handling globale con Cloud Logging

### 4. `chatbot-widget.js` — Frontend Widget
- IIFE per isolamento namespace
- Button floating fixed bottom-right, z-index 9998
- Modal chat 420px × 550px, z-index 9999, border-radius 12px
- Gradiente blu `#667eea → #764ba2`
- Messaggi: utente (destra, blu) vs assistant (sinistra, grigio)
- Rilevamento automatico `window.location.hostname` come site_domain
- `CLOUD_FUNCTION_URL` configurabile (placeholder da aggiornare post-deploy)
- Loading indicator "Pensando..."
- Retry automatico (1 retry su network error)
- Responsive: <600px → 95% viewport
- Enter per invio + validazione input vuoto

### 5. `scraper.py` — Web Scraper per BigQuery
- Crea venv: `python3 -m venv .venv && source .venv/bin/activate`
- Crawl prime 5 pagine per sito (edysma.net, carvaletbologna.it, snowequipmentshop.com)
- Parse HTML con BeautifulSoup (`<p>`, `<h1>`, `<h2>`, `<h3>`)
- Trova link interni, crawla max 4 pagine aggiuntive
- Chunk testo in blocchi da ~500 caratteri
- Carica direttamente in BigQuery
- Rispetta robots.txt, skip pagine non raggiungibili

### 6. `.env.example` — Config Template
```
ANTHROPIC_API_KEY=sk-ant-...
GCP_PROJECT_ID=your-project-id
GCP_REGION=europe-west1
BQ_DATASET=chatbot
BQ_TABLE=website_content
```

### 7. `setup.sh` — Script Deploy GCP
- Enable APIs (bigquery, cloudfunctions, logging, secretmanager)
- Crea BigQuery dataset `chatbot` e tabella `website_content`
- Carica `ANTHROPIC_API_KEY` in GCP Secret Manager
- Deploy Cloud Function con:
  - `--runtime python312`
  - `--memory 512MB`
  - `--timeout 60s`
  - `--set-secrets ANTHROPIC_API_KEY=ANTHROPIC_API_KEY:latest`
  - `--allow-unauthenticated`
- Output URL endpoint

### 8. `README.md` — Documentazione
- Prerequisites (gcloud CLI, Python 3.12)
- Setup step-by-step con venv
- Test cURL
- Integrazione widget (`<script src="...">`)
- Troubleshooting

---

## Schema BigQuery

```sql
CREATE TABLE `{project}.chatbot.website_content` (
  id STRING,
  site_domain STRING,
  content STRING,
  page_url STRING,
  indexed_at TIMESTAMP
);
```

---

## Verifica Post-Deploy

```bash
# Test 1: domanda valida
curl -X POST $FUNCTION_URL \
  -H "Content-Type: application/json" \
  -d '{"question": "Cosa è EDYSMA?", "site_domain": "edysma.net"}'
# Risposta attesa: {"answer": "...", "site": "edysma.net", "status": "success"}

# Test 2: question vuota → HTTP 400
# Test 3: site_domain inesistente → risposta "nessun contenuto trovato"
```

---

## Siti Target

1. `edysma.net` — agenzia digitale
2. `carvaletbologna.it` — ristorante
3. `snowequipmentshop.com` — e-commerce attrezzature invernali

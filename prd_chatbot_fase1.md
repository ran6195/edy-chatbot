# Product Requirements Document (PRD)
## Chatbot Web - Fase 1: Test Iniziale

**Data:** Febbraio 2025  
**Versione:** 1.0  
**Scope:** Implementazione fase di test semplice ma completa  
**Target:** Google Cloud Platform (Vertex AI + BigQuery + Cloud Functions)

---

## 1. Executive Summary

Sviluppare un **chatbot intelligente end-to-end** funzionante per il primo test, con capacità di:
- Ricevere domande da un widget web
- Elaborarle tramite Claude (Vertex AI)
- Fornire risposte basate su contenuti estratti da siti web
- Operare su Google Cloud Platform con infrast ruttura serverless

**Risultato finale:** Widget floating su 3 siti + Backend API + Database RAG, tutto funzionante e testabile in 4-5 ore.

---

## 2. Requisiti Funzionali

### 2.1 Frontend - Widget JavaScript

**Descrizione:**
Un widget interattivo sempre visibile nei siti web che permette agli utenti di interrogare il chatbot.

**Specifiche Tecniche:**

| Aspetto | Requisito |
|---------|-----------|
| **Positioning** | Button floating fixed, bottom-right (position: fixed; bottom: 20px; right: 20px;) |
| **Visibility** | Visibile su tutti i viewport (mobile, tablet, desktop) senza overlap contenuti |
| **Toggle** | Click su button apre/chiude modal chat |
| **Modal** | Dimensioni: 420px width, max 550px height, border-radius: 12px |
| **Messages** | Display conversazione con stile user (destra, blu) vs assistant (sinistra, grigio) |
| **Input** | Campo testo + bottone Invia; supportare Enter per invio |
| **Loading** | Indicatore "Pensando..." mentre backend elabora |
| **Styling** | Gradiente blu (667eea → 764ba2), animazioni smooth, CORS headers gestiti |
| **Responsiveness** | Ridimensiona su mobile (<600px width → max 95% viewport width) |
| **Script Isolation** | Nessun conflitto con JS del sito (namespace own or IIFE) |

**Payload Inviato:**
```json
{
  "question": "string (testo domanda utente)",
  "site_domain": "string (es. edysma.net)"
}
```

**Payload Ricevuto:**
```json
{
  "answer": "string (risposta da Claude)",
  "site": "string (dominio originale)",
  "status": "success|error"
}
```

**Error Handling:**
- Mostrare messaggi di errore user-friendly
- Retry automatico per timeout transitori
- Log errori in console browser per debug

---

### 2.2 Backend API - Cloud Function

**Descrizione:**
Endpoint HTTP POST che orchestrazione il flusso RAG (Retrieval-Augmented Generation).

**URL Endpoint:**
```
POST https://{region}-{project}.cloudfunctions.net/chatbot-handler
```

**Input:**
```json
{
  "question": "string",
  "site_domain": "string"
}
```

**Output:**
```json
{
  "answer": "string",
  "site": "string",
  "status": "success" | "error"
}
```

**Flusso Logico:**

1. **Validazione Input**
   - Verificare che question sia presente e non vuota
   - Verificare che site_domain sia valido
   - Ritornare HTTP 400 se invalido

2. **Retrieval (RAG)**
   - Query BigQuery tabella `chatbot.website_content`
   - Filtrare per `site_domain = @site_domain`
   - Recuperare top-5 risultati (colonne: content, page_url)
   - Concatenare contenuti in unico string separati da "---"
   - Se nessun risultato: usare fallback "Nessun contenuto trovato"

3. **Augmentation**
   - Creare system prompt con contesto recuperato:
   ```
   Sei un assistente utile per il sito: {site_domain}
   
   Rispondi SOLO basandoti su questo contenuto dal sito:
   {context_chunks}
   
   Se la domanda non è coperta, di' chiaramente che l'informazione non è disponibile.
   
   Rispondi in italiano.
   ```

4. **Generation**
   - Chiamare Claude via AnthropicVertex (Vertex AI)
   - Model: `claude-sonnet-4-5@20250929`
   - max_tokens: 1024
   - Temperature: default (0.7)
   - Timeout: 30 secondi

5. **Response**
   - Estrarre testo risposta da message.content[0].text
   - Ritornare JSON con status="success"
   - Applicare CORS header: `Access-Control-Allow-Origin: *`

**Error Handling:**
- Try-catch globale per qualsiasi eccezione
- Ritornare HTTP 500 con messaggio errore JSON se fallisce
- Log errore in Cloud Logging con stack trace

**Performance Requirements:**
- Latency target: <5 secondi (p95)
- Availability: 99.5% uptime
- Timeout: 60 secondi massimo

---

### 2.3 Data Layer - BigQuery

**Descrizione:**
Database che archivia contenuti estratti dai siti, usato per il retrieval RAG.

**Schema Tabella: `chatbot.website_content`**

```sql
CREATE TABLE `{project}.chatbot.website_content` (
  id STRING,
  site_domain STRING,           -- es. "edysma.net"
  content STRING,               -- testo del contenuto (chunk)
  page_url STRING,              -- URL della pagina di provenienza
  indexed_at TIMESTAMP          -- data indicizzazione
);
```

**Indici:**
- Primary: (site_domain, indexed_at)
- Full-text search su content (opzionale per fase 1)

**Dati di Test:**
Popolazione manuale con 3-5 righe per sito:

```json
[
  {
    "id": "1",
    "site_domain": "edysma.net",
    "content": "EDYSMA è un'agenzia digitale specializzata in web design e consulenza online...",
    "page_url": "https://edysma.net",
    "indexed_at": "2025-02-11T10:00:00Z"
  },
  {
    "id": "2",
    "site_domain": "carvaletbologna.it",
    "content": "Carvaletto è un ristorante tradizionale bolognese con piatti della cucina emiliana...",
    "page_url": "https://carvaletbologna.it",
    "indexed_at": "2025-02-11T10:00:00Z"
  },
  {
    "id": "3",
    "site_domain": "snowequipmentshop.com",
    "content": "Snow Equipment Shop vende attrezzature invernali di qualità: sci, snowboard...",
    "page_url": "https://snowequipmentshop.com",
    "indexed_at": "2025-02-11T10:00:00Z"
  }
]
```

**Query Esecuzione:**
```sql
SELECT content, page_url
FROM `{project}.chatbot.website_content`
WHERE site_domain = @site_domain
LIMIT 5
```

---

## 3. Requisiti Non-Funzionali

### 3.1 Infrastructure & Deployment

| Requisito | Specifica |
|-----------|-----------|
| **Cloud Provider** | Google Cloud Platform (GCP) |
| **Compute** | Cloud Functions (Python 3.12) |
| **Database** | BigQuery |
| **LLM** | Claude Sonnet 4.5 via Vertex AI |
| **Region** | europe-west1 (o altra region EU) |
| **Authentication** | Application Default Credentials (gcloud auth) |
| **CORS** | Allow all origins (`*`) per test |
| **Memory Function** | 512 MB |
| **Timeout Function** | 60 secondi |

### 3.2 Security (Fase 1 - Test)

- ✓ HTTPS obbligatorio (GCP gestisce)
- ✓ API key non richiesto per test (unauthenticated)
- ✓ Nessun dato sensibile in logs
- ✓ CORS aperto per test (restringlere in prod)

### 3.3 Observability

| Aspetto | Requisito |
|---------|-----------|
| **Logging** | Cloud Logging (standard di GCP) |
| **Metrics** | Request count, latency, error rate |
| **Debug** | Stack trace completi in errori |
| **Accessibility** | gcloud functions logs read --limit 50 |

### 3.4 Performance SLA

- Latency p50: <2s
- Latency p95: <5s
- Latency p99: <10s
- Availability: 99.5%

---

## 4. Componenti Tecnici da Sviluppare

### 4.1 Cloud Function Backend

**File:** `main.py`

**Dipendenze:**
```
google-cloud-bigquery==3.14.0
anthropic==0.27.0
functions-framework==3.5.0
```

**Struttura Pseudo-codice:**

```python
import functions_framework
from google.cloud import bigquery
from anthropic import AnthropicVertex
import json

@functions_framework.http
def chatbot_handler(request):
    # 1. Handle CORS OPTIONS
    if request.method == 'OPTIONS':
        return cors_response()
    
    # 2. Parse input
    data = request.get_json()
    question = data.get('question', '').strip()
    site_domain = data.get('site_domain', '')
    
    if not question:
        return error_response("Question required", 400)
    
    try:
        # 3. Retrieval from BigQuery
        bq_client = bigquery.Client()
        results = query_bigquery(bq_client, site_domain)
        context = format_context(results)
        
        # 4. Augmentation - create system prompt
        system_prompt = create_system_prompt(site_domain, context)
        
        # 5. Generation - call Claude
        anthropic_client = AnthropicVertex(
            project_id="YOUR-PROJECT-ID",
            region="global"
        )
        response = anthropic_client.messages.create(
            model="claude-sonnet-4-5@20250929",
            max_tokens=1024,
            system=system_prompt,
            messages=[{"role": "user", "content": question}]
        )
        
        answer = response.content[0].text
        
        # 6. Return response
        return success_response(answer, site_domain)
    
    except Exception as e:
        log_error(e)
        return error_response(str(e), 500)
```

**Funzioni Helper:**
- `cors_response()` - ritorna headers CORS
- `query_bigquery(client, site_domain)` - esecue query
- `format_context(results)` - concatena contenuti
- `create_system_prompt(site, context)` - crea prompt
- `success_response(answer, site)` - ritorna JSON 200
- `error_response(msg, status)` - ritorna JSON error

**File:** `requirements.txt`
Vedi sezione "Dipendenze"

---

### 4.2 Frontend Widget

**File:** `chatbot-widget.js`

**Responsabilità:**
- Creare DOM button floating
- Creare DOM modal chat
- Gestire click events (open/close)
- Inviare richieste fetch a API backend
- Renderizzare messaggi conversazione
- Gestire loading state
- Implementare retry logica per errori transitori

**Configurazione:**
```javascript
const CLOUD_FUNCTION_URL = 'https://...'; // Impostare prima del deploy
const SITE_DOMAIN = window.location.hostname; // Rileva automaticamente
```

**Funzioni Principali:**
- `createButton()` - crea button floating
- `createChatContainer()` - crea modal chat
- `toggleChat()` - apri/chiudi modal
- `sendMessage()` - invia domanda al backend
- `addMessage(text, isUser)` - renderizza messaggio
- `showLoading()` / `hideLoading()` - stato loading

**Styling:**
- Tailwind CSS classes oppure inline styles
- Responsive (mobile-first)
- Smooth animations
- Z-index: 9998 (button), 9999 (container)

---

### 4.3 Setup GCP

**Script di Setup:**

```bash
#!/bin/bash

PROJECT_ID="chatbot-test"

# 1. Create project
gcloud projects create $PROJECT_ID --name="Chatbot Test"

# 2. Set project
gcloud config set project $PROJECT_ID

# 3. Enable APIs
gcloud services enable aiplatform.googleapis.com
gcloud services enable bigquery.googleapis.com
gcloud services enable cloudfunctions.googleapis.com
gcloud services enable storage-api.googleapis.com
gcloud services enable logging.googleapis.com

# 4. Request Claude access
echo "Vai a: https://console.cloud.google.com/vertex-ai/publishers/anthropic/model-garden/claude-sonnet-4-5"
echo "Clicca GET ACCESS e completa il form"
```

---

## 5. Data & Configuration

### 5.1 Siti da Supportare

Fase 1 supporta 3 siti:

1. **edysma.net** - Agenzia digitale
2. **carvaletbologna.it** - Ristorante
3. **snowequipmentshop.com** - E-commerce attrezzature

Ogni sito ha `site_domain` unico usato per filtrare contenuti in BigQuery.

### 5.2 Dati di Test

Popolazione manuale di BigQuery con contenuti di esempio (vedi sezione 2.3).

Non serve crawler automatico in fase 1 - inserimento manuale è sufficiente.

---

## 6. Testing Requirements

### 6.1 Test Manuale

**Test 1: Widget Visibile**
- [ ] Button floating appare su ogni sito
- [ ] Button ha emoji 💬 e colore gradiente
- [ ] Click apre modal chat
- [ ] Click chiude modal chat

**Test 2: Input Domanda**
- [ ] Utente scrive testo in input field
- [ ] Premi Enter o clicca Invia
- [ ] Domanda scompare da input field
- [ ] Messaggio utente appare in chat (destra, blu)

**Test 3: API Response**
- [ ] Backend riceve domanda
- [ ] BigQuery estrae contenuti per site_domain
- [ ] Claude genera risposta in <5 secondi
- [ ] Risposta ritorna al widget

**Test 4: Display Risposta**
- [ ] Risposta appare in chat (sinistra, grigio)
- [ ] Testo formattato e leggibile
- [ ] Scroll automatico verso basso
- [ ] Utente può continuare conversazione

**Test 5: Error Handling**
- [ ] URL backend sbagliato → mostra errore user-friendly
- [ ] Network timeout → mostra errore e possibilità retry
- [ ] Question vuota → non invia (validazione client)
- [ ] Backend error → mostra messaggio errore

### 6.2 Test cURL (Backend)

```bash
# Test 1: Domanda valida
curl -X POST https://europe-west1-chatbot-test.cloudfunctions.net/chatbot-handler \
  -H "Content-Type: application/json" \
  -d '{
    "question": "Cosa è EDYSMA?",
    "site_domain": "edysma.net"
  }'

# Risposta attesa: HTTP 200 con { "answer": "...", "site": "edysma.net", "status": "success" }

# Test 2: Question vuota
curl -X POST ... -d '{"question": "", "site_domain": "edysma.net"}'
# Risposta attesa: HTTP 400 con errore

# Test 3: Site domain non trovato
curl -X POST ... -d '{"question": "Test", "site_domain": "nonexistent.com"}'
# Risposta attesa: HTTP 200 con answer che dice "Nessun contenuto trovato"
```

### 6.3 Validation Checklist

- [ ] Cloud Function deployata e URL accessible
- [ ] BigQuery dataset e tabella creati
- [ ] Dati di test caricati in BigQuery
- [ ] Claude access requestato e confermato
- [ ] Widget script integrato nei 3 siti
- [ ] Button visibile su tutti i siti
- [ ] Chat apre/chiude correttamente
- [ ] Domanda inviata e risposta ricevuta in <5s
- [ ] cURL test passa
- [ ] Cloud Logging mostra richieste
- [ ] Nessun errore JavaScript in console browser
- [ ] CORS headers corretti
- [ ] Mobile responsiveness OK

---

## 7. Acceptance Criteria

Fase 1 è considerata **COMPLETATA** quando:

1. ✅ Widget floating visibile su tutti i 3 siti
2. ✅ Utente può aprire/chiudere chat con click
3. ✅ Utente può scrivere domanda e inviarla
4. ✅ Backend riceve domanda e la elabora
5. ✅ Claude genera risposta in <5 secondi
6. ✅ Risposta appare nel widget in italiano
7. ✅ Nessun errore JavaScript in browser console
8. ✅ cURL test della API passa
9. ✅ Cloud Logging mostra richieste senza errori
10. ✅ Documento README con istruzioni di deployment

---

## 8. Deliverables

### 8.1 Codice

- [ ] `main.py` - Cloud Function backend (completo e testato)
- [ ] `requirements.txt` - Dipendenze Python
- [ ] `chatbot-widget.js` - Widget JavaScript (minificato opzionale)
- [ ] `setup.sh` - Script setup GCP (automazione)

### 8.2 Documentazione

- [ ] `README.md` - Istruzioni deploy e test
- [ ] `ARCHITECTURE.md` - Diagramma e flow tecnico
- [ ] `DEPLOYMENT_GUIDE.md` - Step-by-step per deployare
- [ ] `TESTING_GUIDE.md` - Come testare manualmente

### 8.3 Configurazione

- [ ] `.env.example` - Variabili d'ambiente template
- [ ] `test-data.json` - Dati di test per BigQuery

### 8.4 Validazione

- [ ] Checklist test (todos) completata
- [ ] Screenshots di widget funzionante su 3 siti
- [ ] Log cURL test di successo
- [ ] Cloud Logging export con 10+ richieste di test

---

## 9. Timeline & Milestones

| Milestone | Durata Stimata | Descrizione |
|-----------|----------------|-------------|
| Setup GCP | 30 min | Creazione progetto, abilitazione servizi, richiesta accesso Claude |
| BigQuery Setup | 1 ora | Creazione dataset, tabella, caricamento dati test |
| Backend Development | 1-1.5 ore | Sviluppo main.py, testing cURL, debug |
| Frontend Development | 30-45 min | Sviluppo chatbot-widget.js, integrazione siti |
| End-to-End Testing | 30 min | Test manuale, fixing bugs, validazione |
| **TOTALE** | **4-5 ore** | |

---

## 10. Risorse & Contacts

### 10.1 Accesso GCP

- **Project ID:** chatbot-test (da creare)
- **Region:** europe-west1 (default) o us-central1
- **Vertex AI Models:** claude-sonnet-4-5@20250929

### 10.2 Documentazione Esterna

- Anthropic Claude API: https://docs.claude.com/en/api/claude-on-vertex-ai
- BigQuery Python: https://cloud.google.com/bigquery/docs/quickstarts/load-data-python
- Cloud Functions: https://cloud.google.com/functions/docs/quickstart/deploy-http-function
- GCP Free Tier: https://cloud.google.com/free

---

## 11. Assumptions & Constraints

### Assumptions

- GCP account con billing abilitato è disponibile
- Accesso a Claude su Vertex AI sarà concesso entro 2 ore
- Siti target sono accessibili e stable
- Nessuna integrazione con sistemi legacy (fase 1 standalone)

### Constraints

- **No authentication** - widget è pubblico (nessun login richiesto)
- **No multi-lingua** - risposte solo in italiano per fase 1
- **No conversation memory** - ogni domanda è indipendente (no history across sessions)
- **Manual data population** - no crawler automatico in fase 1
- **Basic RAG** - solo filtraggio testo, no vettori/embeddings
- **5-second response window** - user experience dipende da latency

---

## 12. Risk Mitigation

| Rischio | Probabilità | Impatto | Mitigazione |
|---------|-----------|--------|-----------|
| Accesso Claude ritardato | Media | Alto | Richiedere early, user internal-only |
| GCP quota limit | Bassa | Alto | Monitor usage, request quota increase |
| Network latency | Media | Medio | Use closest region (europe-west1) |
| BigQuery query slow | Bassa | Medio | Add indexes, limit results to 5 |
| JavaScript conflicts | Media | Medio | Use IIFE, test su clean domain |

---

## 13. Success Metrics (Fase 1)

| Metrica | Target |
|---------|--------|
| Time to First Response | <5 secondi |
| Uptime | >99% |
| Error Rate | <1% |
| Widget Load Time | <500ms |
| User Satisfaction (Manual Test) | Positivo |

---

## Notes

- Questo PRD è per la **Fase 1 (Test)** solamente
- Fasi successive aggiungeranno: crawler automatico, vector search, multi-lingua, analytics
- Costi GCP stimati: €7-14/mese (scenario attuale)
- Architettura è disegnata per scalare senza refactor maggiori

---

**Documento approvato per lo sviluppo della Fase 1**

Data: Febbraio 2025

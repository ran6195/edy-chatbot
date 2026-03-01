#!/usr/bin/env bash
set -euo pipefail

# ── Configurazione — modifica questi valori ───────────────────────────────────
PROJECT_ID="${GCP_PROJECT_ID:?Imposta la variabile GCP_PROJECT_ID}"
REGION="${GCP_REGION:-europe-west1}"
ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:?Imposta la variabile ANTHROPIC_API_KEY}"
BQ_DATASET="${BQ_DATASET:-chatbot}"
BQ_TABLE="${BQ_TABLE:-website_content}"
FUNCTION_NAME="chatbot"

echo "==> Progetto GCP: $PROJECT_ID — Regione: $REGION"

# ── 1. Abilita API necessarie ─────────────────────────────────────────────────
echo "==> Abilitazione API..."
gcloud services enable \
  bigquery.googleapis.com \
  cloudfunctions.googleapis.com \
  cloudbuild.googleapis.com \
  logging.googleapis.com \
  secretmanager.googleapis.com \
  --project="$PROJECT_ID"

# ── 2. BigQuery dataset e tabella ────────────────────────────────────────────
echo "==> Creazione dataset BigQuery: $BQ_DATASET"
bq --project_id="$PROJECT_ID" mk --dataset --location=EU "$BQ_DATASET" 2>/dev/null || echo "Dataset già esistente."

echo "==> Creazione tabella: $BQ_TABLE"
bq --project_id="$PROJECT_ID" query --nouse_legacy_sql "
CREATE TABLE IF NOT EXISTS \`$PROJECT_ID.$BQ_DATASET.$BQ_TABLE\` (
  id STRING NOT NULL,
  site_domain STRING NOT NULL,
  content STRING,
  page_url STRING,
  indexed_at TIMESTAMP
);"

# ── 3. Secret Manager — API key Anthropic ────────────────────────────────────
echo "==> Caricamento ANTHROPIC_API_KEY in Secret Manager..."
echo -n "$ANTHROPIC_API_KEY" | gcloud secrets create ANTHROPIC_API_KEY \
  --data-file=- \
  --project="$PROJECT_ID" 2>/dev/null || \
  echo -n "$ANTHROPIC_API_KEY" | gcloud secrets versions add ANTHROPIC_API_KEY \
    --data-file=- \
    --project="$PROJECT_ID"

# ── 4. Deploy Cloud Function ──────────────────────────────────────────────────
echo "==> Deploy Cloud Function: $FUNCTION_NAME"
gcloud functions deploy "$FUNCTION_NAME" \
  --gen2 \
  --runtime=python312 \
  --region="$REGION" \
  --source=. \
  --entry-point=chatbot \
  --trigger-http \
  --allow-unauthenticated \
  --memory=512MB \
  --timeout=60s \
  --set-env-vars="GCP_PROJECT_ID=$PROJECT_ID,BQ_DATASET=$BQ_DATASET,BQ_TABLE=$BQ_TABLE" \
  --set-secrets="ANTHROPIC_API_KEY=ANTHROPIC_API_KEY:latest" \
  --project="$PROJECT_ID"

# ── 5. Output URL ─────────────────────────────────────────────────────────────
FUNCTION_URL=$(gcloud functions describe "$FUNCTION_NAME" \
  --region="$REGION" \
  --project="$PROJECT_ID" \
  --format="value(serviceConfig.uri)" 2>/dev/null || \
  gcloud functions describe "$FUNCTION_NAME" \
  --region="$REGION" \
  --project="$PROJECT_ID" \
  --format="value(httpsTrigger.url)")

echo ""
echo "✅ Deploy completato!"
echo "   URL Cloud Function: $FUNCTION_URL"
echo ""
echo "   Aggiorna CLOUD_FUNCTION_URL in chatbot-widget.js con:"
echo "   $FUNCTION_URL"
echo ""
echo "   Test rapido:"
echo "   curl -X POST $FUNCTION_URL \\"
echo "     -H 'Content-Type: application/json' \\"
echo "     -d '{\"question\": \"Chi siete?\", \"site_domain\": \"edysma.net\"}'"

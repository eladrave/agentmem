#!/bin/bash
set -e

echo "========================================="
echo " AI Agentic Memory MCP Server Deployment "
echo "========================================="

# Set default project if not provided
DEFAULT_PROJECT="chkp-gcp-rnd-thunderdep-base"

# Ensure gcloud is installed
if ! command -v gcloud &> /dev/null; then
    echo "gcloud CLI could not be found. Please install it."
    exit 1
fi

# List available projects
echo "Available GCP Projects:"
gcloud projects list --format="value(projectId)" | sed 's/^/ - /'

echo ""
read -p "Enter the Project ID to deploy to [$DEFAULT_PROJECT]: " PROJECT_ID
PROJECT_ID=${PROJECT_ID:-$DEFAULT_PROJECT}

echo "Using project: $PROJECT_ID"
gcloud config set project "$PROJECT_ID"

# Enable Required APIs
echo "Enabling required APIs (Run, Storage, Artifact Registry)..."
gcloud services enable run.googleapis.com storage.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com

# Setup GCS Bucket
REGION="us-central1"
BUCKET_NAME="agentmem-data-${PROJECT_ID}"

if gcloud storage ls "gs://${BUCKET_NAME}" &> /dev/null; then
    echo "Bucket gs://${BUCKET_NAME} already exists."
else
    echo "Creating bucket gs://${BUCKET_NAME}..."
    gcloud storage buckets create "gs://${BUCKET_NAME}" --location="${REGION}" --uniform-bucket-level-access
fi

# Get or Generate Admin Password
if [ -z "$ADMIN_PASSWORD" ]; then
    ADMIN_PASSWORD=$(cat /dev/urandom | tr -dc 'a-zA-Z0-9' | fold -w 32 | head -n 1)
    echo ""
    echo "======================================================="
    echo " ⚠️ AUTO-GENERATED ADMIN_PASSWORD: $ADMIN_PASSWORD "
    echo " MAKE SURE TO SAVE THIS! IT WILL BE USED FOR PROVISIONING "
    echo "======================================================="
    echo ""
fi

# Ask for Gemini API Key if not present
if [ -z "$GEMINI_API_KEY" ]; then
    read -p "Enter your GEMINI_API_KEY: " GEMINI_API_KEY
fi

if [ -z "$GEMINI_API_KEY" ]; then
    echo "Error: GEMINI_API_KEY is required to deploy."
    exit 1
fi

echo "Building and Deploying to Cloud Run..."

# Determine the project number for the service account
PROJECT_NUM=$(gcloud projects describe $PROJECT_ID --format="value(projectNumber)")
COMPUTE_SA="${PROJECT_NUM}-compute@developer.gserviceaccount.com"

# Grant the compute SA access to the bucket so FUSE can mount it
echo "Granting Cloud Run Service Account access to GCS Bucket..."
gcloud storage buckets add-iam-policy-binding gs://${BUCKET_NAME} \
  --member="serviceAccount:${COMPUTE_SA}" \
  --role="roles/storage.objectAdmin" > /dev/null

gcloud run deploy agentmem-mcp \
  --source . \
  --region "${REGION}" \
  --allow-unauthenticated \
  --execution-environment gen2 \
  --add-volume name=gcs-data,type=cloud-storage,bucket=${BUCKET_NAME} \
  --add-volume-mount name=gcs-data,mount-path=/data \
  --set-env-vars="GEMINI_API_KEY=${GEMINI_API_KEY},ADMIN_PASSWORD=${ADMIN_PASSWORD}"

SERVICE_URL=$(gcloud run services describe agentmem-mcp --region="${REGION}" --format="value(status.url)")

echo ""
echo "======================================================="
echo " ✅ DEPLOYMENT SUCCESSFUL "
echo " Service URL: $SERVICE_URL"
echo " Admin Auth : X-Admin-Password: $ADMIN_PASSWORD"
echo " MCP Endpoint: $SERVICE_URL/mcp/sse"
echo "======================================================="
echo ""
echo "To provision your first user, run:"
echo "curl -X POST $SERVICE_URL/admin/users -H 'X-Admin-Password: $ADMIN_PASSWORD'"

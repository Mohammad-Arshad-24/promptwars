#!/usr/bin/env bash
# Run from the repository root in Google Cloud Shell with a billing-enabled project.
set -euo pipefail
project=${1:?Usage: bash scripts/deploy.sh PROJECT_ID AVAILABLE_GEMINI_MODEL [REGION]}
model=${2:?Provide a Gemini model enabled for this project}
region=${3:-asia-south1}
runtime="lablink-runtime@${project}.iam.gserviceaccount.com"
builder="lablink-build@${project}.iam.gserviceaccount.com"
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com firestore.googleapis.com aiplatform.googleapis.com secretmanager.googleapis.com iam.googleapis.com --project="$project"
for name in lablink-runtime lablink-build; do
  email="$name@$project.iam.gserviceaccount.com"
  if ! gcloud iam service-accounts describe "$email" --project="$project" >/dev/null 2>&1; then
    gcloud iam service-accounts create "$name" --project="$project"
  fi
done
for role in roles/datastore.user roles/aiplatform.user; do
  gcloud projects add-iam-policy-binding "$project" --member="serviceAccount:$runtime" --role="$role" --condition=None --quiet >/dev/null
done
gcloud projects add-iam-policy-binding "$project" --member="serviceAccount:$builder" --role=roles/run.builder --condition=None --quiet >/dev/null
if ! gcloud firestore databases describe --database='(default)' --project="$project" >/dev/null 2>&1; then
  gcloud firestore databases create --database='(default)' --location="$region" --type=firestore-native --project="$project"
fi
if ! gcloud secrets describe lablink-signing --project="$project" >/dev/null 2>&1; then
  python3 -c 'import secrets,sys; sys.stdout.write(secrets.token_urlsafe(48))' | gcloud secrets create lablink-signing --replication-policy=automatic --data-file=- --project="$project"
fi
gcloud secrets add-iam-policy-binding lablink-signing --member="serviceAccount:$runtime" --role=roles/secretmanager.secretAccessor --project="$project" --quiet >/dev/null
gcloud run deploy lablink --source=. --project="$project" --region="$region" \
  --service-account="$runtime" --build-service-account="projects/$project/serviceAccounts/$builder" \
  --set-secrets=LABLINK_SECRET=lablink-signing:latest \
  --set-env-vars="GOOGLE_CLOUD_PROJECT=$project,VERTEX_MODEL=$model,VERTEX_LOCATION=global" \
  --no-invoker-iam-check --min-instances=0 --max-instances=3 --memory=512Mi --port=8080 --quiet
url=$(gcloud run services describe lablink --project="$project" --region="$region" --format='value(status.url)')
python3 scripts/live_check.py "$url"
echo "Cloud Run URL: $url"


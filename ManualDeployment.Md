# Manual deployment to Google Cloud

This guide deploys Meridian AI manually for learning. You will use your own
Google account in Cloud Shell to create the resources, then deploy the app to
Cloud Run. GitHub Actions and downloadable service-account keys are not needed.

The app's cloud mode uses:

- **Cloud Run** to serve the frontend and API.
- **Vertex AI Vector Search** for document retrieval.
- **Cloud Storage** for uploaded documents and logs.
- **Secret Manager** for the Gemini API key.
- **Cloud Build** and **Artifact Registry** to build and store the container.

> **Cost warning:** A deployed Vertex AI Vector Search index can cost money by
> the hour even when the app has no visitors. A budget sends alerts; it does
> not stop charges. Check current prices, set a budget, and follow the cleanup
> section when you finish. Do not upload private documents to a learning
> deployment.

## 1. Prerequisites

You need:

- A Google account with permission to create resources and manage IAM in a
  Google Cloud project.
- Billing enabled on that project.
- The Google Cloud CLI (`gcloud`), or use **Cloud Shell** in the Google Cloud
  Console (recommended for this guide).
- A Gemini API key from [Google AI Studio](https://aistudio.google.com/apikey).
- This repository's source code. In Cloud Shell, clone your own trusted copy:

  ```bash
  git clone https://github.com/maganahalli-aiml/merian-ai-mrv.git
  cd merian-ai-mrv
  ```

If you are using Cloud Shell and already cloned the repository in a previous
session, `cd` to that checkout instead.

## 2. Select a project and region

In the Google Cloud Console, open **Cloud Shell**. Set the project ID and region
for this guide. Replace the example project ID with yours:

```bash
export PROJECT_ID="YOUR_PROJECT_ID"
export REGION="us-central1"
export SERVICE_NAME="meridian-ai-cloud-run"
export BUCKET_NAME="${PROJECT_ID}-vector-staging"
export RUNTIME_SA_NAME="meridian-runtime"
export RUNTIME_SA="${RUNTIME_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
export IMAGE_URI="${REGION}-docker.pkg.dev/${PROJECT_ID}/meridian/meridian-ai:manual"

gcloud auth list
gcloud config set project "$PROJECT_ID"
gcloud config set run/region "$REGION"
gcloud projects describe "$PROJECT_ID"
```

Confirm that the active account is yours and that the displayed project is the
intended learning project before proceeding.

## 3. Enable the required Google Cloud APIs

```bash
gcloud services enable \
  aiplatform.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  cloudresourcemanager.googleapis.com \
  generativelanguage.googleapis.com \
  iam.googleapis.com \
  logging.googleapis.com \
  run.googleapis.com \
  secretmanager.googleapis.com \
  storage.googleapis.com \
  --project="$PROJECT_ID"
```

API enablement can take a few minutes to propagate. If a later command reports
that an API is disabled, wait briefly and retry it.

## 4. Create a private Cloud Storage bucket

The bucket stores uploaded documents and application logs. Uniform bucket-level
access and public access prevention keep it private:

```bash
gcloud storage buckets create "gs://${BUCKET_NAME}" \
  --project="$PROJECT_ID" \
  --location="$REGION" \
  --uniform-bucket-level-access \
  --public-access-prevention
```

If the bucket already exists, confirm that it belongs to this project and has
the intended access controls instead of creating a second bucket.

## 5. Create a runtime service account with limited access

Cloud Run will use this service account to access Google Cloud. It is separate
from your personal account and from the Cloud Build identity. No service
account key file is created or downloaded.

Create the account:

```bash
gcloud iam service-accounts create "$RUNTIME_SA_NAME" \
  --project="$PROJECT_ID" \
  --display-name="Meridian Cloud Run runtime"
```

Allow it to call Vertex AI. This role is project-scoped because the app uses
Vertex AI models and Vector Search:

```bash
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${RUNTIME_SA}" \
  --role="roles/aiplatform.user"
```

Allow it to read and write objects in this bucket only:

```bash
gcloud storage buckets add-iam-policy-binding "gs://${BUCKET_NAME}" \
  --member="serviceAccount:${RUNTIME_SA}" \
  --role="roles/storage.objectAdmin"
```

The service account will receive access to the one API-key secret in the next
step, rather than access to every secret in the project.

## 6. Store the Gemini key in Secret Manager

Create a secret container:

```bash
gcloud secrets create GOOGLE_API_KEY \
  --project="$PROJECT_ID" \
  --replication-policy="automatic"
```

Add a secret version without putting the key in shell history or a command
argument. When prompted, paste the key; input will not be displayed:

```bash
read -r -s -p "Paste the Gemini API key: " GOOGLE_API_KEY
printf '\n'
printf '%s' "$GOOGLE_API_KEY" |
  gcloud secrets versions add GOOGLE_API_KEY \
    --project="$PROJECT_ID" \
    --data-file=-
unset GOOGLE_API_KEY
```

Grant the Cloud Run runtime identity access to this secret only:

```bash
gcloud secrets add-iam-policy-binding GOOGLE_API_KEY \
  --project="$PROJECT_ID" \
  --member="serviceAccount:${RUNTIME_SA}" \
  --role="roles/secretmanager.secretAccessor"
```

Do not print the key, put it in a `.env` file in the repository, or pass it as a
plain Cloud Run environment variable.

## 7. Create the Vector Search index and endpoint

The app expects a 768-dimensional Vector Search index. The repository includes
`generate_json.py`, which creates a single placeholder datapoint for bootstrapping
the index. Run these commands from the repository root in Cloud Shell:

```bash
python3 generate_json.py
gcloud storage cp init_embeddings.json "gs://${BUCKET_NAME}/index-data/"
```

Create the metadata file used by Vertex AI:

```bash
cat > index_metadata.json <<EOF
{
  "contentsDeltaUri": "gs://${BUCKET_NAME}/index-data",
  "config": {
    "dimensions": 768,
    "approximateNeighborsCount": 150,
    "distanceMeasureType": "DOT_PRODUCT_DISTANCE",
    "shardSize": "SHARD_SIZE_MEDIUM",
    "algorithm_config": {
      "treeAhConfig": {
        "leafNodeEmbeddingCount": 1000,
        "leafNodesToSearchPercent": 10
      }
    }
  }
}
EOF
```

Create the index. Initial creation may take 30 minutes or longer, and the index
can incur charges as it runs:

```bash
gcloud ai indexes create \
  --project="$PROJECT_ID" \
  --region="$REGION" \
  --display-name="financial-docs-production" \
  --metadata-file=index_metadata.json \
  --index-update-method=STREAM_UPDATE
```

Poll until the index appears, then save its full resource name:

```bash
gcloud ai indexes list \
  --project="$PROJECT_ID" \
  --region="$REGION" \
  --filter="displayName=financial-docs-production" \
  --format="table(name,displayName)"

export INDEX_ID="$(
  gcloud ai indexes list \
    --project="$PROJECT_ID" \
    --region="$REGION" \
    --filter="displayName=financial-docs-production" \
    --format="value(name)" \
    --limit=1
)"
printf 'INDEX_ID=%s\n' "$INDEX_ID"
```

Create the endpoint and save its resource name:

```bash
gcloud ai index-endpoints create \
  --project="$PROJECT_ID" \
  --region="$REGION" \
  --display-name="financial-docs-endpoint"

export ENDPOINT_ID="$(
  gcloud ai index-endpoints list \
    --project="$PROJECT_ID" \
    --region="$REGION" \
    --filter="displayName=financial-docs-endpoint" \
    --format="value(name)" \
    --limit=1
)"
printf 'ENDPOINT_ID=%s\n' "$ENDPOINT_ID"
```

Deploy the index to the endpoint:

```bash
gcloud ai index-endpoints deploy-index "$ENDPOINT_ID" \
  --project="$PROJECT_ID" \
  --region="$REGION" \
  --deployed-index-id=deployed_financial_docs \
  --display-name=financial-docs-deployed \
  --index="$INDEX_ID"
```

Wait until deployment has completed before deploying the app. Check its status
with:

```bash
gcloud ai index-endpoints describe "$ENDPOINT_ID" \
  --project="$PROJECT_ID" \
  --region="$REGION" \
  --format="yaml(deployedIndexes)"
```

The placeholder is not a real document embedding. The app will add actual
embeddings when you upload documents. You can optionally remove the placeholder
after the index is deployed:

```bash
gcloud ai indexes remove-datapoints "$INDEX_ID" \
  --project="$PROJECT_ID" \
  --region="$REGION" \
  --datapoint-ids=init_0001
```

Keep the `INDEX_ID` and `ENDPOINT_ID` values available for the Cloud Run
deployment below. If you start a new Cloud Shell session, list the resources
again to set those environment variables.

## 8. Build the container image

Create an Artifact Registry Docker repository:

```bash
gcloud artifacts repositories create meridian \
  --project="$PROJECT_ID" \
  --location="$REGION" \
  --repository-format=docker \
  --description="Meridian learning deployment images"
```

Submit the repository source to Cloud Build:

```bash
gcloud builds submit \
  --project="$PROJECT_ID" \
  --tag="$IMAGE_URI" \
  .
```

Cloud Build runs as a Google-managed build identity; it is not the Cloud Run
runtime identity created above. On a new project, the build may fail if that
identity lacks permission to build or push images. If so, inspect the build
details in **Cloud Build → History** and grant the build identity only the
permissions shown as missing (typically Cloud Build builder and Artifact
Registry writer permissions), then retry. Do not grant the runtime service
account project IAM Admin or Secret Manager Admin to make the build pass.

## 9. Deploy to Cloud Run

Deploy the built image with the dedicated runtime identity and the Secret
Manager reference. This command keeps the service private by default:

```bash
gcloud run deploy "$SERVICE_NAME" \
  --project="$PROJECT_ID" \
  --region="$REGION" \
  --platform=managed \
  --image="$IMAGE_URI" \
  --service-account="$RUNTIME_SA" \
  --port=8080 \
  --max-instances=3 \
  --no-allow-unauthenticated \
  --set-env-vars="APP_MODE=cloud,ENVIRONMENT=production,GCP_PROJECT_ID=${PROJECT_ID},GCP_REGION=${REGION},GCS_BUCKET_NAME=${BUCKET_NAME},GCS_PREFIX=uploads/,VERTEX_LLM_MODEL_NAME=gemini-3.8-flash,VERTEX_EMBEDDING_MODEL_NAME=text-embedding-005,VECTOR_SEARCH_INDEX_ID=${INDEX_ID},VECTOR_SEARCH_INDEX_ENDPOINT_ID=${ENDPOINT_ID}" \
  --set-secrets="GOOGLE_API_KEY=GOOGLE_API_KEY:latest"
```

Get the service URL:

```bash
gcloud run services describe "$SERVICE_NAME" \
  --project="$PROJECT_ID" \
  --region="$REGION" \
  --format="value(status.url)"
```

### Optional: make the app publicly reachable

The service is private unless you deliberately allow unauthenticated access.
For a short-lived learning demo, you can make it public with:

```bash
gcloud run services add-iam-policy-binding "$SERVICE_NAME" \
  --project="$PROJECT_ID" \
  --region="$REGION" \
  --member="allUsers" \
  --role="roles/run.invoker"
```

Anyone with the URL can then use the app and consume your Gemini/API quota.
Public access may be blocked by your organization's policy. If you only need
to test it yourself, keep it private and use authenticated access instead.

## 10. Test and inspect the deployment

1. Open the Cloud Run URL if you enabled public access. Otherwise use the
   Cloud Run Console's authenticated testing options.
2. Upload a non-sensitive sample PDF and try a question about it.
3. Check **Cloud Run → Logs** for startup, permission, or model errors.
4. Check **Vertex AI → Vector Search** to confirm the index is deployed.

The first request can be slow while Cloud Run starts. Document embedding uses
Vertex AI, and chat uses the Gemini API key from Secret Manager.

## 11. Clean up when finished

Deleting only the Cloud Run service does **not** stop charges from a deployed
Vector Search index. Undeploy and delete the index endpoint and index:

```bash
gcloud ai index-endpoints undeploy-index "$ENDPOINT_ID" \
  --project="$PROJECT_ID" \
  --region="$REGION" \
  --deployed-index-id=deployed_financial_docs

gcloud ai index-endpoints delete "$ENDPOINT_ID" \
  --project="$PROJECT_ID" \
  --region="$REGION"

gcloud ai indexes delete "$INDEX_ID" \
  --project="$PROJECT_ID" \
  --region="$REGION"
```

Then remove the Cloud Run service:

```bash
gcloud run services delete "$SERVICE_NAME" \
  --project="$PROJECT_ID" \
  --region="$REGION"
```

If you no longer need the stored documents, bucket, secret, or image repository,
delete them deliberately in the Google Cloud Console after confirming that
nothing else uses them. Deleting the bucket permanently deletes its objects.
Deleting the entire learning project is the most complete cleanup, but verify
the project ID carefully first.

## Troubleshooting

| Symptom | What to check |
|---|---|
| An API is disabled | Confirm you selected the right project, wait for API enablement to propagate, and retry. |
| `Permission denied` from Vertex AI | Confirm the Cloud Run service uses `$RUNTIME_SA` and that it has `roles/aiplatform.user`. |
| `Permission denied` from Cloud Storage | Confirm `$RUNTIME_SA` has `roles/storage.objectAdmin` on `gs://$BUCKET_NAME`. |
| Secret cannot be accessed | Confirm the secret is named `GOOGLE_API_KEY` and `$RUNTIME_SA` has `roles/secretmanager.secretAccessor` on that secret. |
| Cloud Build cannot push the image | Check the build's service identity and grant the narrowly scoped build/push roles it is missing. |
| App reports missing cloud configuration | Recheck the project, bucket, index, endpoint, and region values in the Cloud Run service configuration. |
| Vector index is still provisioning | Wait for it to finish; initial creation and deployment may take a long time. Check Vertex AI operation status in the Console. |

For ongoing deployments, rebuild the image and run the Cloud Run deploy command
again with the same configuration. Do not paste credentials into source files
or commit local `.env` files.

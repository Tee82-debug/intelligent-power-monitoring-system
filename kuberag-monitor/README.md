# KubeRAG MLOps Monitor

KubeRAG is an AI-assisted Kubernetes monitoring and MLOps component of the **Intelligent Power Monitoring & Distribution System**.

It combines **FastAPI, Kubernetes/k3s, machine learning, ChromaDB, Ollama, MLflow, Prometheus, Docker, GitHub Actions, and GitHub Container Registry (GHCR)** to provide cluster-health prediction, retrieval-augmented monitoring assistance, observability, and containerized deployment.

---

## Overview

KubeRAG provides two primary capabilities:

1. **Machine-learning-based cluster health prediction**
2. **Retrieval-Augmented Generation (RAG) for Kubernetes monitoring questions**

The system is exposed through a FastAPI service and deployed as a containerized workload in a k3s environment.

The current implementation includes:

- Random Forest cluster-health classification
- FastAPI prediction and RAG endpoints
- ChromaDB vector retrieval
- Ollama-based local LLM inference
- MLflow experiment tracking
- Prometheus API instrumentation
- Docker containerization
- Kubernetes/k3s orchestration
- Automated CI validation
- Container vulnerability scanning
- Kubernetes manifest validation
- Automated Docker image publishing to GHCR
- Kubernetes readiness and liveness probes
- Non-root container execution

---

## Architecture

```text
                  Kubernetes / k3s
                        |
        +---------------+---------------+
        |                               |
        v                               v
   KubeRAG API                      Prometheus
     FastAPI                         Metrics
        |
        +-------------------+
        |                   |
        v                   v
 Random Forest           ChromaDB
 Health Model               |
                             v
                     Retrieved Context
                             |
                             v
                           Ollama
                        Llama 3.2 1B
                             |
                             v
                    RAG-Based Response
```

---

## Core Capabilities

### Cluster Health Prediction

KubeRAG uses a **Random Forest classifier** to predict Kubernetes cluster health from infrastructure metrics.

The model uses four input features:

- CPU usage
- Memory usage
- Pod count
- Restart count

The classifier produces cluster-health states such as:

- `Healthy`
- `Warning`
- `Critical`

The model configuration is:

```text
Algorithm: RandomForestClassifier
Estimators: 100
Random State: 42
Train/Test Split: 70% / 30%
```

Training performance is evaluated using:

- Accuracy
- Weighted F1 Score
- Classification Report

The packaged model is located at:

```text
models/cluster_health_model.pkl
```

---

## Verified Health Predictions

The deployed model has been tested through the live `/predict-health` endpoint in the k3s environment.

| CPU Usage | Memory Usage | Pod Count | Restarts | Prediction |
| ---: | ---: | ---: | ---: | --- |
| 25% | 40% | 5 | 0 | Healthy |
| 65% | 70% | 10 | 2 | Warning |
| 90% | 92% | 18 | 6 | Critical |

These tests verify the complete inference path:

```text
Input Metrics
     |
     v
FastAPI /predict-health
     |
     v
Packaged Random Forest Model
     |
     v
Cluster Health Classification
     |
     +--> Healthy
     +--> Warning
     +--> Critical
```

---

## RAG-Based Kubernetes Assistant

The `/ask` endpoint implements the Retrieval-Augmented Generation workflow.

```text
User Question
     |
     v
FastAPI /ask
     |
     v
ChromaDB
Collection: kuberag_logs
     |
     v
Retrieve Relevant Monitoring Context
     |
     v
Construct Context-Constrained Prompt
     |
     v
Ollama
Model: llama3.2:1b
     |
     v
Natural-Language Response
```

The application retrieves relevant monitoring documents from ChromaDB and supplies them as context to the local Ollama model.

The prompt constrains the LLM to answer using the retrieved monitoring context.

---

# API Endpoints

## `GET /`

Returns application status, enabled features, and model availability.

Example:

```json
{
  "project": "KubeRAG MLOps Monitor",
  "status": "running",
  "features": [
    "FastAPI",
    "Kubernetes",
    "ChromaDB",
    "Ollama",
    "RAG"
  ],
  "health_model_loaded": true
}
```

The `health_model_loaded` value confirms whether the trained Random Forest artifact was successfully loaded by FastAPI.

---

## `POST /predict-health`

Predicts Kubernetes cluster health.

Example request:

```json
{
  "cpu_usage": 65,
  "memory_usage": 70,
  "pod_count": 10,
  "restart_count": 2
}
```

Example response:

```json
{
  "cpu_usage": 65.0,
  "memory_usage": 70.0,
  "pod_count": 10,
  "restart_count": 2,
  "predicted_cluster_status": "Warning"
}
```

Another example representing higher infrastructure pressure:

```json
{
  "cpu_usage": 90,
  "memory_usage": 92,
  "pod_count": 18,
  "restart_count": 6
}
```

Response:

```json
{
  "cpu_usage": 90.0,
  "memory_usage": 92.0,
  "pod_count": 18,
  "restart_count": 6,
  "predicted_cluster_status": "Critical"
}
```

---

## `POST /ask`

Accepts a natural-language Kubernetes monitoring question.

Example request:

```json
{
  "question": "Which node has high CPU usage?"
}
```

The endpoint:

1. Connects to ChromaDB.
2. Queries the `kuberag_logs` collection.
3. Retrieves relevant monitoring context.
4. Constructs a monitoring-specific prompt.
5. Sends the prompt to Ollama.
6. Returns the retrieved context and generated answer.

Example response structure:

```json
{
  "question": "Which node has high CPU usage?",
  "retrieved_context": "...",
  "answer": "..."
}
```

---

# Machine Learning Workflow

The health model is trained using:

```text
data/cluster_health.csv
```

The workflow is:

```text
cluster_health.csv
        |
        v
Feature Selection
        |
        +--> CPU Usage
        +--> Memory Usage
        +--> Pod Count
        +--> Restart Count
        |
        v
Train/Test Split
     70% / 30%
        |
        v
RandomForestClassifier
        |
        +--> Accuracy
        +--> Weighted F1 Score
        +--> Classification Report
        |
        v
Optional MLflow Tracking
        |
        v
cluster_health_model.pkl
        |
        v
Docker Image
        |
        v
FastAPI /predict-health
```

---

## MLflow Tracking

MLflow can record:

- Model type
- Number of estimators
- Accuracy
- F1 score
- Trained model artifact

The configured experiment is:

```text
kuberag-cluster-health
```

The tracking URI can be configured using:

```text
MLFLOW_TRACKING_URI
```

MLflow tracking can also be disabled:

```bash
ENABLE_MLFLOW=false python app/train_model.py
```

This is used during Docker image creation so the model can be generated without requiring an active MLflow tracking server during the image build.

---

# Model Training and Packaging

## Local Training

The model can be trained manually from the `kuberag-monitor` directory:

```bash
python app/train_model.py
```

The script reads:

```text
data/cluster_health.csv
```

and generates:

```text
models/cluster_health_model.pkl
```

Trained `.pkl` artifacts are excluded from Git.

---

## Automated Docker Model Packaging

The production Docker build automatically trains and packages the model.

```text
Version-Controlled Training Data
          |
          v
     train_model.py
          |
          v
Random Forest Training
          |
          v
cluster_health_model.pkl
          |
          v
      Docker Image
          |
          v
     KubeRAG API
```

During the Docker build, MLflow tracking is disabled while model training remains enabled.

This ensures the deployed image contains the model required by `/predict-health` without committing binary model artifacts to the repository.

---

# ChromaDB Data Ingestion

The RAG workflow uses the ChromaDB collection:

```text
kuberag_logs
```

Monitoring documents can represent scenarios such as:

- High CPU utilization
- Memory pressure
- Increased pod restarts
- Normal cluster operation

These documents provide retrieval context for the RAG workflow.

---

## ChromaDB Query Testing

The project includes scripts for testing retrieval against the `kuberag_logs` collection.

Example monitoring question:

```text
Which node has high CPU usage?
```

Relevant documents are retrieved and supplied as context to the RAG workflow.

---

# Prometheus Instrumentation

The FastAPI application is instrumented using:

```text
prometheus-fastapi-instrumentator
```

Application metrics are exposed for Prometheus collection.

A Kubernetes `ServiceMonitor` manifest is included for integration with the Prometheus Operator.

The monitoring interval is configured at:

```text
15s
```

---

# Technology Stack

| Category | Technology |
| --- | --- |
| API | FastAPI |
| Machine Learning | scikit-learn Random Forest |
| Model Tracking | MLflow |
| Model Persistence | joblib |
| Vector Database | ChromaDB |
| Local LLM Runtime | Ollama |
| Language Model | Llama 3.2 1B |
| Monitoring | Prometheus |
| Containerization | Docker |
| Container Registry | GitHub Container Registry |
| Orchestration | Kubernetes / k3s |
| Data Processing | pandas |
| Testing | pytest |
| Coverage | pytest-cov |
| Linting / Formatting | Ruff |
| Dependency Security | pip-audit |
| Container Security | Trivy |
| Kubernetes Validation | kubeconform |
| CI/CD | GitHub Actions |

---

# Repository Structure

```text
kuberag-monitor/
|
+-- app/
|   +-- chroma_client.py
|   +-- collect_cluster_info.py
|   +-- collect_k8s_logs.py
|   +-- ingest.py
|   +-- main.py
|   +-- query.py
|   +-- rag_test.py
|   +-- train_model.py
|
+-- data/
|   +-- cluster_health.csv
|
+-- k8s/
|   +-- chroma-deployment.yaml
|   +-- chroma-service.yaml
|   +-- deployment.yaml
|   +-- load-generator.yaml
|   +-- mlflow-deployment.yaml
|   +-- mlflow-service.yaml
|   +-- ollama-deployment.yaml
|   +-- ollama-service.yaml
|   +-- service.yaml
|   +-- servicemonitor.yaml
|
+-- models/
|   +-- README.md
|
+-- tests/
|
+-- workloads/
|   +-- Dockerfile
|   +-- generate_load.py
|
+-- .dockerignore
+-- Dockerfile
+-- README.md
+-- requirements.txt
+-- requirements-dev.txt
```

---

# Python Dependencies

Runtime dependencies are installed using:

```bash
pip install -r requirements.txt
```

Development and CI dependencies are installed using:

```bash
pip install -r requirements-dev.txt
```

Core technologies include:

```text
fastapi
uvicorn
chromadb
requests
pydantic
pandas
scikit-learn
joblib
mlflow
prometheus-fastapi-instrumentator
```

---

# Running Locally

## Install Dependencies

From `kuberag-monitor`:

```bash
pip install -r requirements.txt
```

## Train the Model

```bash
python app/train_model.py
```

To train without MLflow:

```bash
ENABLE_MLFLOW=false python app/train_model.py
```

## Start FastAPI

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

The API is then available at:

```text
http://localhost:8000
```

Interactive FastAPI documentation is available at:

```text
http://localhost:8000/docs
```

---

# Docker

Build the image:

```bash
docker build -t kuberag-api .
```

Run locally:

```bash
docker run --rm -p 8000:8000 kuberag-api
```

The Docker build automatically generates and packages the health model.

---

# Container Security

The KubeRAG API image runs as a dedicated non-root Linux user:

```text
User: appuser
UID: 10001
GID: 10001
```

The Docker image explicitly switches from root to:

```dockerfile
USER appuser
```

The Kubernetes security context further enforces:

```yaml
runAsNonRoot: true
runAsUser: 10001
runAsGroup: 10001
allowPrivilegeEscalation: false
```

All unnecessary Linux capabilities are dropped:

```yaml
capabilities:
  drop:
    - ALL
```

This reduces the privileges available to the application if the container is compromised.

---

# Kubernetes Deployment

The `k8s/` directory contains manifests for:

- KubeRAG API
- KubeRAG service
- ChromaDB
- Ollama
- MLflow
- Load generator
- Prometheus ServiceMonitor

The KubeRAG API uses the CI-published GHCR image:

```text
ghcr.io/tee82-debug/kuberag-api:latest
```

The service exposes:

```text
Container Port: 8000
Service Port: 80
NodePort: 30080
```

---

## Kubernetes Health Probes

The API deployment includes both readiness and liveness probes.

### Readiness Probe

```text
Path: /
Port: 8000
Initial Delay: 5 seconds
Period: 10 seconds
Timeout: 3 seconds
Failure Threshold: 3
```

The readiness probe prevents Kubernetes from routing traffic to the pod until FastAPI is ready.

### Liveness Probe

```text
Path: /
Port: 8000
Initial Delay: 15 seconds
Period: 20 seconds
Timeout: 3 seconds
Failure Threshold: 3
```

The liveness probe allows Kubernetes to detect an unresponsive API and restart the container when repeated health checks fail.

---

# GitHub Container Registry

Successful CI runs on `main` publish the KubeRAG image to:

```text
ghcr.io/tee82-debug/kuberag-api
```

Images are published with two tags:

```text
latest
<commit-sha>
```

Example:

```bash
docker pull ghcr.io/tee82-debug/kuberag-api:latest
```

The SHA-based tag provides an immutable reference to the image generated from a particular Git commit.

---

# CI/CD Pipeline

KubeRAG uses **GitHub Actions** to automatically validate application and deployment changes.

The workflow performs:

1. Source checkout
2. Python environment setup
3. Development dependency installation
4. Ruff lint validation
5. Ruff formatting validation
6. Python dependency security audit
7. FastAPI tests
8. Test coverage enforcement
9. Docker image build
10. Trivy container vulnerability scan
11. Kubernetes manifest validation
12. GHCR authentication
13. Docker image publishing after successful changes reach `main`

---

## Test Coverage

API tests are executed with pytest and pytest-cov.

The CI pipeline enforces a minimum coverage threshold of:

```text
80%
```

A pull request fails CI if coverage drops below the configured threshold.

---

## Dependency Security

Python dependencies are checked using:

```text
pip-audit
```

Known vulnerabilities are surfaced during CI.

Temporary vulnerability exceptions may be used when an upstream dependency does not yet provide a compatible patched release. These exceptions are documented directly in the workflow and should be removed when compatible fixes become available.

---

## Container Vulnerability Scanning

The built Docker image is scanned using:

```text
Trivy
```

CI checks for:

```text
HIGH
CRITICAL
```

severity vulnerabilities.

The workflow is configured to fail when applicable high-severity vulnerabilities are detected.

---

## Kubernetes Manifest Validation

Kubernetes manifests are validated using:

```text
kubeconform
```

Strict schema validation is enabled for standard Kubernetes resources.

The Prometheus Operator `ServiceMonitor` custom resource is excluded from standard Kubernetes schema validation because it depends on an external CRD.

---

## CI/CD Flow

```text
Developer Change
       |
       v
Feature Branch
       |
       v
Pull Request
       |
       +--> Ruff Lint
       |
       +--> Ruff Format Check
       |
       +--> Dependency Audit
       |
       +--> API Tests
       |
       +--> Coverage >= 80%
       |
       +--> Docker Build
       |
       +--> Trivy Scan
       |
       +--> Kubernetes Validation
       |
       v
Merge to main
       |
       v
Build Production Image
       |
       v
Publish to GHCR
       |
       v
k3s Deployment
```

Pull requests perform validation but do not publish Docker images.

Image publishing occurs after successful changes reach `main`.

Deployment from GHCR to the current k3s environment is currently initiated manually.

---

# Deployment Verification

The deployment has been verified in the project k3s environment.

Verified conditions include:

```text
KubeRAG Pod: Running
Container User: appuser
UID: 10001
GID: 10001
Privilege Escalation: Disabled
Linux Capabilities: Dropped
Health Model: Loaded
Readiness Probe: Enabled
Liveness Probe: Enabled
```

The live API successfully returned:

```json
{
  "health_model_loaded": true
}
```

and successfully produced `Healthy`, `Warning`, and `Critical` cluster-health predictions.

---

# Workload Generator

The `workloads/` directory contains a load-generation utility used to create infrastructure activity for monitoring and testing.

```text
workloads/
+-- Dockerfile
+-- generate_load.py
```

The corresponding Kubernetes deployment is:

```text
k8s/load-generator.yaml
```

---

# Configuration

The KubeRAG API supports environment-based configuration for key services.

Examples include:

```text
CHROMA_HOST
CHROMA_PORT
OLLAMA_URL
OLLAMA_MODEL
HEALTH_MODEL_PATH
MLFLOW_TRACKING_URI
ENABLE_MLFLOW
```

The Kubernetes deployment currently configures the main service endpoints required by FastAPI.

Some auxiliary scripts still use execution-context-specific ChromaDB connection settings and should be standardized in a future revision.

---

# Current Limitations

- The health classifier is trained using the project-specific `cluster_health.csv` dataset and has not been validated against a large production dataset.
- Some ChromaDB helper scripts still use different local connection settings.
- The RAG knowledge base currently contains a limited set of monitoring documents.
- Ollama configuration requires further standardization across all execution contexts.
- Deployment from GHCR to the current k3s environment is manually initiated.
- FastAPI endpoints currently do not implement production authentication or authorization.
- Additional resilience, scalability, and failure-handling controls would be required for production-scale deployment.

---

# Future Improvements

Potential improvements include:

- Automate deployment from GitHub Actions to the k3s environment when appropriate security and repository permissions are available.
- Centralize Kubernetes configuration using ConfigMaps and Secrets.
- Standardize ChromaDB connectivity across all application scripts.
- Automatically ingest live Kubernetes logs and cluster state into the RAG knowledge base.
- Expand the RAG knowledge base using real monitoring events.
- Add automated model retraining.
- Introduce model-version management.
- Add model drift and prediction-quality monitoring.
- Add authentication and authorization to FastAPI endpoints.
- Introduce automated rollback and release-version strategies.
- Evaluate additional Kubernetes security controls and policy enforcement.
- Expand integration and end-to-end testing.

---

# Project Context

KubeRAG is part of the broader **Intelligent Power Monitoring & Distribution System**.

The overall project focuses on improving visibility into compute infrastructure by combining:

- Power monitoring
- Kubernetes infrastructure metrics
- Anomaly detection
- Power forecasting
- Interactive dashboards
- Cluster-health prediction
- AI-assisted operational insights

The system is designed to support better monitoring, understanding, and optimization of compute infrastructure as electrical and computational demand grows.

---

# Status

The current KubeRAG implementation has verified:

- FastAPI deployment
- Random Forest model training
- Automated model packaging
- Healthy / Warning / Critical inference
- ChromaDB integration
- Ollama integration
- Prometheus instrumentation
- Docker containerization
- Non-root execution
- Kubernetes security controls
- Readiness and liveness probes
- GitHub Actions CI
- API testing and coverage enforcement
- Dependency vulnerability auditing
- Trivy container scanning
- Kubernetes manifest validation
- GHCR image publishing
- Deployment of the GHCR image to k3s

The remaining work is primarily focused on deployment automation, configuration standardization, expanded RAG ingestion, authentication, and production-scale operational controls.
\# KubeRAG MLOps Monitor



KubeRAG is an AI-assisted Kubernetes monitoring component within the \*\*Intelligent Power Monitoring \& Distribution System\*\*.



It combines \*\*FastAPI, Kubernetes, ChromaDB, Ollama, machine learning, MLflow, and Prometheus instrumentation\*\* to provide cluster-health prediction and natural-language querying of Kubernetes monitoring context.



\---



\## Overview



KubeRAG provides two complementary capabilities:



1\. \*\*Machine-learning-based cluster health prediction\*\*

2\. \*\*Retrieval-Augmented Generation (RAG) for Kubernetes monitoring questions\*\*



The application exposes these capabilities through a FastAPI service.



\---



\## Core Capabilities



\### Cluster Health Prediction



KubeRAG uses a trained \*\*Random Forest classifier\*\* to predict cluster health based on infrastructure metrics.



The prediction model uses the following features:



\* CPU usage

\* Memory usage

\* Pod count

\* Restart count



The target variable is:



```text

status

```



The model is trained using:



```text

RandomForestClassifier

n\_estimators = 100

random\_state = 42

test\_size = 0.30

```



Training performance is evaluated using:



\* Accuracy

\* Weighted F1 Score

\* Classification Report



The trained model is saved locally as:



```text

models/cluster\_health\_model.pkl

```



\---



\## RAG-Based Kubernetes Assistant



The `/ask` API endpoint implements the main RAG workflow.



```text

User Question

&#x20;    │

&#x20;    ▼

FastAPI /ask

&#x20;    │

&#x20;    ▼

ChromaDB

Collection: kuberag\_logs

&#x20;    │

&#x20;    ▼

Retrieve relevant monitoring context

&#x20;    │

&#x20;    ▼

Construct context-constrained prompt

&#x20;    │

&#x20;    ▼

Ollama

Model: llama3.2:1b

&#x20;    │

&#x20;    ▼

Natural-language response

```



The application retrieves the two most relevant documents from ChromaDB and supplies them as context to the local Ollama model.



The prompt explicitly instructs the model to answer using only the retrieved monitoring context.



\---



\## API Endpoints



\### `GET /`



Returns basic application status and feature information.



Example response:



```json

{

&#x20; "project": "KubeRAG MLOps Monitor",

&#x20; "status": "running",

&#x20; "features": \[

&#x20;   "FastAPI",

&#x20;   "Kubernetes",

&#x20;   "ChromaDB",

&#x20;   "Ollama",

&#x20;   "RAG"

&#x20; ]

}

```



\---



\### `POST /predict-health`



Predicts cluster health using the trained Random Forest model.



Example request:



```json

{

&#x20; "cpu\_usage": 72.5,

&#x20; "memory\_usage": 64.8,

&#x20; "pod\_count": 14,

&#x20; "restart\_count": 2

}

```



Example response structure:



```json

{

&#x20; "cpu\_usage": 72.5,

&#x20; "memory\_usage": 64.8,

&#x20; "pod\_count": 14,

&#x20; "restart\_count": 2,

&#x20; "predicted\_cluster\_status": "..."

}

```



The exact value of `predicted\_cluster\_status` depends on the labels contained in the training dataset.



\---



\### `POST /ask`



Accepts a natural-language Kubernetes monitoring question.



Example request:



```json

{

&#x20; "question": "Which node has high CPU usage?"

}

```



The endpoint:



1\. Connects to ChromaDB.

2\. Queries the `kuberag\_logs` collection.

3\. Retrieves the two most relevant documents.

4\. Builds a monitoring-specific prompt.

5\. Sends the prompt to Ollama.

6\. Returns the retrieved context and generated answer.



Example response structure:



```json

{

&#x20; "question": "Which node has high CPU usage?",

&#x20; "retrieved\_context": "...",

&#x20; "answer": "..."

}

```



\---



\## Machine Learning Workflow



The health model is trained using:



```text

data/cluster\_health.csv

```



The training workflow is:



```text

cluster\_health.csv

&#x20;       │

&#x20;       ▼

Feature Selection

&#x20;       │

&#x20;       ├── CPU Usage

&#x20;       ├── Memory Usage

&#x20;       ├── Pod Count

&#x20;       └── Restart Count

&#x20;       │

&#x20;       ▼

Train/Test Split

70% / 30%

&#x20;       │

&#x20;       ▼

RandomForestClassifier

&#x20;       │

&#x20;       ├── Accuracy

&#x20;       ├── Weighted F1 Score

&#x20;       └── Classification Report

&#x20;       │

&#x20;       ▼

MLflow Tracking

&#x20;       │

&#x20;       ▼

cluster\_health\_model.pkl

&#x20;       │

&#x20;       ▼

FastAPI /predict-health

```



MLflow is used to record:



\* Model type

\* Number of estimators

\* Accuracy

\* F1 score

\* Trained model artifact



The configured MLflow experiment is:



```text

kuberag-cluster-health

```



\---



\## ChromaDB Data Ingestion



The `app/ingest.py` script inserts monitoring documents into the ChromaDB collection:



```text

kuberag\_logs

```



The current sample documents include monitoring scenarios such as:



\* High CPU utilization

\* Memory pressure

\* Increased pod restarts

\* Normal cluster operation



These documents provide retrieval context for testing the RAG workflow.



\---



\## ChromaDB Query Testing



The `app/query.py` script provides a simple retrieval test against the `kuberag\_logs` collection.



Example query:



```text

Which node has high CPU usage?

```



The script retrieves the two most relevant documents from ChromaDB and prints the result.



\---



\## Prometheus Instrumentation



The FastAPI application is instrumented using:



```text

prometheus-fastapi-instrumentator

```



This exposes application metrics that can be collected by Prometheus.



\---



\## Technology Stack



| Category          | Technology                 |

| ----------------- | -------------------------- |

| API               | FastAPI                    |

| Machine Learning  | scikit-learn Random Forest |

| Model Tracking    | MLflow                     |

| Model Persistence | joblib                     |

| Vector Database   | ChromaDB                   |

| Local LLM Runtime | Ollama                     |

| Language Model    | Llama 3.2 1B               |

| Monitoring        | Prometheus                 |

| Containerization  | Docker                     |

| Orchestration     | Kubernetes / k3s           |

| Data Processing   | pandas                     |



\---



\## Repository Structure



```text

kuberag-monitor/

│

├── app/

│   ├── chroma\_client.py

│   ├── collect\_cluster\_info.py

│   ├── collect\_k8s\_logs.py

│   ├── ingest.py

│   ├── main.py

│   ├── query.py

│   ├── rag\_k8s.py

│   ├── rag\_test.py

│   └── train\_model.py

│

├── data/

│   └── cluster\_health.csv

│

├── k8s/

│   ├── chroma-deployment.yaml

│   ├── chroma-service.yaml

│   ├── deployment.yaml

│   ├── load-generator.yaml

│   ├── mlflow-deployment.yaml

│   ├── mlflow-service.yaml

│   ├── ollama-deployment.yaml

│   ├── ollama-service.yaml

│   ├── service.yaml

│   └── servicemonitor.yaml

│

├── workloads/

│   ├── Dockerfile

│   └── generate\_load.py

│

├── Dockerfile

├── README.md

└── requirements.txt

```



\---



\## Python Dependencies



Install dependencies using:



```bash

pip install -r requirements.txt

```



Current dependencies include:



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



\---



\## Training the Health Model



The FastAPI application expects the trained model at:



```text

models/cluster\_health\_model.pkl

```



Create the models directory if it does not already exist:



```bash

mkdir -p models

```



Train the model from the `kuberag-monitor` directory:



```bash

python app/train\_model.py

```



The training script reads:



```text

data/cluster\_health.csv

```



and writes the trained model to:



```text

models/cluster\_health\_model.pkl

```



Because trained `.pkl` artifacts are excluded from Git, the model should be generated locally before starting the FastAPI application.



\---



\## Running the API



After installing dependencies and training the model:



```bash

uvicorn app.main:app --host 0.0.0.0 --port 8000

```



FastAPI interactive documentation is then available at:



```text

/docs

```



when accessing the service locally.



\---



\## Kubernetes Deployment



The `k8s/` directory contains manifests for:



\* KubeRAG application deployment

\* Application service

\* ChromaDB

\* Ollama

\* MLflow

\* Load generator

\* Prometheus ServiceMonitor



These components are designed to run within the Kubernetes/k3s environment.



\---



\## Workload Generator



The `workloads/` directory contains a load-generation utility used to create infrastructure activity for monitoring and testing.



```text

workloads/

├── Dockerfile

└── generate\_load.py

```



The corresponding Kubernetes deployment is defined in:



```text

k8s/load-generator.yaml

```



\---



\## Current Implementation Notes



The current implementation uses different ChromaDB connection settings depending on execution context:



\* `main.py` connects to the Kubernetes service at `chromadb:8000`.

\* `chroma\_client.py` uses `localhost:8000`.

\* `ingest.py` and `query.py` currently use `localhost:8002`.



These values reflect different local and Kubernetes access paths and should be aligned or externalized through environment variables in a future revision.



The MLflow training script currently connects to:



```text

http://127.0.0.1:30500

```



This value should also be configurable for different environments.



\---



\## Current Limitations



\* The health model is trained on the project dataset in `cluster\_health.csv`.

\* The trained model artifact must be generated locally before the FastAPI service starts.

\* ChromaDB connection settings are currently hard-coded in several scripts.

\* Ollama model configuration is currently hard-coded to `llama3.2:1b`.

\* The current RAG ingestion script uses a small set of sample monitoring documents.

\* `rag\_k8s.py` currently contains only a sample Kubernetes question and is not the primary RAG implementation.

\* Additional error handling would be required for production deployment.



\---



\## Future Improvements



Potential improvements include:



\* Centralize configuration using environment variables.

\* Standardize ChromaDB connection settings.

\* Make the Ollama model configurable.

\* Automatically ingest live Kubernetes logs and cluster state.

\* Expand the RAG knowledge base using real monitoring events.

\* Improve exception handling and service-health checks.

\* Add automated model retraining.

\* Add model-version validation at application startup.

\* Add automated tests for API endpoints.

\* Add authentication and authorization for production deployments.




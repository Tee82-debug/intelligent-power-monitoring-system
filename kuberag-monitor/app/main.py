import os

import chromadb
import joblib
import pandas as pd
import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from prometheus_fastapi_instrumentator import Instrumentator
from pydantic import BaseModel, Field


load_dotenv(".env")

app = FastAPI(title="KubeRAG MLOps Monitor")

Instrumentator().instrument(app).expose(app)

CHROMA_HOST = os.getenv("CHROMA_HOST", "chromadb")
CHROMA_PORT = int(os.getenv("CHROMA_PORT", "8000"))

OLLAMA_URL = os.getenv(
    "OLLAMA_URL",
    "http://ollama:11434/api/generate"
)

MODEL_NAME = os.getenv("OLLAMA_MODEL", "llama3.2:1b")

HEALTH_MODEL_PATH = os.getenv(
    "HEALTH_MODEL_PATH",
    "models/cluster_health_model.pkl"
)


def load_health_model():
    try:
        return joblib.load(HEALTH_MODEL_PATH)
    except FileNotFoundError:
        return None
    except Exception:
        return None


health_model = load_health_model()


class HealthPredictRequest(BaseModel):
    cpu_usage: float = Field(ge=0, le=100)
    memory_usage: float = Field(ge=0, le=100)
    pod_count: int = Field(ge=0)
    restart_count: int = Field(ge=0)


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)


@app.get("/")
def home():
    return {
        "project": "KubeRAG MLOps Monitor",
        "status": "running",
        "features": [
            "FastAPI",
            "Kubernetes",
            "ChromaDB",
            "Ollama",
            "RAG"
        ],
        "health_model_loaded": health_model is not None
    }


@app.post("/predict-health")
def predict_health(request: HealthPredictRequest):
    if health_model is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "Cluster health model is unavailable. "
                "Train the model before using this endpoint."
            )
        )

    try:
        data = pd.DataFrame([{
            "cpu_usage": request.cpu_usage,
            "memory_usage": request.memory_usage,
            "pod_count": request.pod_count,
            "restart_count": request.restart_count
        }])

        prediction = health_model.predict(data)[0]

        return {
            "cpu_usage": request.cpu_usage,
            "memory_usage": request.memory_usage,
            "pod_count": request.pod_count,
            "restart_count": request.restart_count,
            "predicted_cluster_status": prediction
        }

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Cluster health prediction failed: {exc}"
        ) from exc


@app.post("/ask")
def ask_question(request: AskRequest):
    try:
        client = chromadb.HttpClient(
            host=CHROMA_HOST,
            port=CHROMA_PORT
        )

        collection = client.get_collection(
            name="kuberag_logs"
        )

        results = collection.query(
            query_texts=[request.question],
            n_results=2
        )

    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"ChromaDB query failed: {exc}"
        ) from exc

    documents = results.get("documents")

    if not documents or not documents[0]:
        raise HTTPException(
            status_code=404,
            detail="No relevant monitoring context was found."
        )

    context = "\n".join(documents[0])

    prompt = f"""
You are a Kubernetes monitoring assistant.

Use only the context below to answer the question.

Context:
{context}

Question:
{request.question}

Answer:
"""

    try:
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": MODEL_NAME,
                "prompt": prompt,
                "stream": False
            },
            timeout=120
        )

        response.raise_for_status()

        payload = response.json()
        answer = payload.get("response")

        if not answer:
            raise ValueError(
                "Ollama response did not contain an answer."
            )

    except requests.Timeout as exc:
        raise HTTPException(
            status_code=504,
            detail="Ollama request timed out."
        ) from exc

    except requests.RequestException as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Ollama service request failed: {exc}"
        ) from exc

    except (ValueError, KeyError) as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Invalid response received from Ollama: {exc}"
        ) from exc

    return {
        "question": request.question,
        "retrieved_context": context,
        "answer": answer
    }
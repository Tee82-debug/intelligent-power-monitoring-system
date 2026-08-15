from fastapi import FastAPI
from pydantic import BaseModel
from prometheus_fastapi_instrumentator import Instrumentator
import chromadb
import requests
import joblib
import pandas as pd


app = FastAPI(title="KubeRAG MLOps Monitor")

Instrumentator().instrument(app).expose(app)

CHROMA_HOST = "chromadb"
CHROMA_PORT = 8000
OLLAMA_URL = "http://ollama:11434/api/generate"
MODEL_NAME = "llama3.2:1b"
health_model = joblib.load("models/cluster_health_model.pkl")

class HealthPredictRequest(BaseModel):
    cpu_usage: float
    memory_usage: float
    pod_count: int
    restart_count: int

class AskRequest(BaseModel):
    question: str

@app.get("/")
def home():
    return {
        "project": "KubeRAG MLOps Monitor",
        "status": "running",
        "features": ["FastAPI", "Kubernetes", "ChromaDB", "Ollama", "RAG"]
    }


@app.post("/predict-health")
def predict_health(request: HealthPredictRequest):
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

@app.post("/ask")
def ask_question(request: AskRequest):
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

    context = "\n".join(results["documents"][0])

    prompt = f"""
You are a Kubernetes monitoring assistant.

Use only the context below to answer the question.

Context:
{context}

Question:
{request.question}

Answer:
"""

    response = requests.post(
        OLLAMA_URL,
        json={
            "model": MODEL_NAME,
            "prompt": prompt,
            "stream": False
        },
        timeout=120
    )

    answer = response.json()["response"]

    return {
        "question": request.question,
        "retrieved_context": context,
        "answer": answer
    }

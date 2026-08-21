import os

import chromadb
import requests
from dotenv import load_dotenv

load_dotenv(".env")

CHROMA_HOST = os.getenv("CHROMA_HOST", "localhost")
CHROMA_PORT = int(os.getenv("CHROMA_PORT", "8000"))
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:1b")

client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)

collection = client.get_collection(name="kuberag_logs")

question = "Why is the node under pressure?"

results = collection.query(query_texts=[question], n_results=2)

context = "\n".join(results["documents"][0])

prompt = f"""
You are a Kubernetes monitoring assistant.

Use only the context below to answer the question.

Context:
{context}

Question:
{question}

Answer:
"""

response = requests.post(
    OLLAMA_URL,
    json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
    timeout=120,
)

response.raise_for_status()

print(response.json()["response"])

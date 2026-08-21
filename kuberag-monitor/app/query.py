import os

import chromadb
from dotenv import load_dotenv

load_dotenv(".env")

CHROMA_HOST = os.getenv("CHROMA_HOST", "localhost")
CHROMA_PORT = int(os.getenv("CHROMA_PORT", "8000"))

client = chromadb.HttpClient(
    host=CHROMA_HOST,
    port=CHROMA_PORT
)

collection = client.get_collection(
    name="kuberag_logs"
)

results = collection.query(
    query_texts=[
        "Which node has high CPU usage?"
    ],
    n_results=2
)

print(results)
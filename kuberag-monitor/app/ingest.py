import os

import chromadb
from dotenv import load_dotenv

load_dotenv(".env")

CHROMA_HOST = os.getenv("CHROMA_HOST", "localhost")
CHROMA_PORT = int(os.getenv("CHROMA_PORT", "8000"))

client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)

collection = client.get_or_create_collection(name="kuberag_logs")

documents = [
    "Node CPU utilization reached 95 percent.",
    "Memory pressure detected on node.",
    "Pod restart count increased rapidly.",
    "Cluster operating normally.",
]

for i, doc in enumerate(documents):
    collection.add(ids=[str(i)], documents=[doc])

print("Documents inserted.")

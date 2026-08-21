import os
import subprocess

import chromadb
from dotenv import load_dotenv

load_dotenv(".env")

CHROMA_HOST = os.getenv("CHROMA_HOST", "localhost")
CHROMA_PORT = int(os.getenv("CHROMA_PORT", "8000"))

client = chromadb.HttpClient(
    host=CHROMA_HOST,
    port=CHROMA_PORT
)

collection = client.get_or_create_collection(
    name="cluster_info"
)

node_info = subprocess.check_output(
    ["kubectl", "describe", "node"]
).decode()

collection.add(
    ids=["node-1"],
    documents=[node_info]
)

print("Node information stored.")
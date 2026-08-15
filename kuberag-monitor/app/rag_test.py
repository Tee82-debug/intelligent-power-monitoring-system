import chromadb
import requests

client = chromadb.HttpClient(
    host="localhost",
    port=8002
)

collection = client.get_collection(
    name="kuberag_logs"
)

question = "Why is the node under pressure?"

results = collection.query(
    query_texts=[question],
    n_results=2
)

context = "\n".join(results["documents"][0])

prompt = f"""
Use the context below to answer the question.

Context:
{context}

Question:
{question}

Answer:
"""

response = requests.post(
    "http://localhost:11434/api/generate",
    json={
        "model": "llama3.2:1b",
        "prompt": prompt,
        "stream": False
    }
)

print(response.json()["response"])

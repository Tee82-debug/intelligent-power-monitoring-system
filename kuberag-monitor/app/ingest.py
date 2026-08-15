import chromadb

client = chromadb.HttpClient(
    host="localhost",
    port=8002
)

collection = client.get_or_create_collection(
    name="kuberag_logs"
)

documents = [
    "Node CPU utilization reached 95 percent.",
    "Memory pressure detected on node.",
    "Pod restart count increased rapidly.",
    "Cluster operating normally."
]

for i, doc in enumerate(documents):
    collection.add(
        ids=[str(i)],
        documents=[doc]
    )

print("Documents inserted.")

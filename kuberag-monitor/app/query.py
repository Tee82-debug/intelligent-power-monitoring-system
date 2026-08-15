import chromadb

client = chromadb.HttpClient(
    host="localhost",
    port=8002
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

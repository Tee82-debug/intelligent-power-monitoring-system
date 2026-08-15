import chromadb

client = chromadb.HttpClient(
    host="localhost",
    port=8000
)

collection = client.get_or_create_collection(
    name="kuberag_logs"
)

import subprocess
import chromadb

client = chromadb.HttpClient(
    host="localhost",
    port=8002
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

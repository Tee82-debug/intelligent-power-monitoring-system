import subprocess
import chromadb

client = chromadb.HttpClient(
    host="localhost",
    port=8002
)

collection = client.get_or_create_collection(
    name="k8s_logs"
)

pods = subprocess.check_output(
    ["kubectl", "get", "pods", "-A", "-o", "name"]
).decode().splitlines()

counter = 0

for pod in pods:
    try:
        logs = subprocess.check_output(
            ["kubectl", "logs", pod.replace("pod/", ""), "-n", "kube-system", "--tail=20"],
            stderr=subprocess.DEVNULL
        ).decode()

        collection.add(
            ids=[str(counter)],
            documents=[logs]
        )

        counter += 1

    except Exception:
        pass

print(f"Ingested {counter} log documents")

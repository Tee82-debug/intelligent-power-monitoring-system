import os
import subprocess

import chromadb
from dotenv import load_dotenv

load_dotenv(".env")

CHROMA_HOST = os.getenv("CHROMA_HOST", "localhost")
CHROMA_PORT = int(os.getenv("CHROMA_PORT", "8000"))

client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)

collection = client.get_or_create_collection(name="k8s_logs")

pods_output = (
    subprocess.check_output(
        [
            "kubectl",
            "get",
            "pods",
            "-A",
            "-o",
            "custom-columns=NAMESPACE:.metadata.namespace,NAME:.metadata.name",
            "--no-headers",
        ]
    )
    .decode()
    .splitlines()
)

counter = 0

for pod_entry in pods_output:
    try:
        namespace, pod_name = pod_entry.split(maxsplit=1)

        logs = subprocess.check_output(
            ["kubectl", "logs", pod_name, "-n", namespace, "--tail=20"],
            stderr=subprocess.DEVNULL,
        ).decode()

        if not logs.strip():
            continue

        collection.add(
            ids=[str(counter)],
            documents=[logs],
            metadatas=[{"namespace": namespace, "pod": pod_name}],
        )

        counter += 1

    except (subprocess.CalledProcessError, ValueError) as exc:
        print(f"Skipping pod entry '{pod_entry}': {exc}")

print(f"Ingested {counter} log documents")

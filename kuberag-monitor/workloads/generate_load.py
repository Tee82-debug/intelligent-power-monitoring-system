import random
import time

import requests

API_URL = "http://kuberag-service.kuberag.svc.cluster.local"

questions = [
    "Why is CPU usage high?",
    "Why did the pod restart?",
    "Explain cluster health.",
    "Why is memory utilization increasing?",
    "What is causing high resource usage?",
]

print("Load generator started.", flush=True)

while True:
    try:
        print("Sending prediction request...", flush=True)

        r1 = requests.post(
            f"{API_URL}/predict-health",
            json={
                "cpu_usage": random.randint(20, 95),
                "memory_usage": random.randint(20, 95),
                "pod_count": random.randint(5, 40),
                "restart_count": random.randint(0, 5),
            },
            timeout=30,
        )

        print(f"Prediction status: {r1.status_code}", flush=True)

        print("Sending RAG request...", flush=True)

        r2 = requests.post(
            f"{API_URL}/ask", json={"question": random.choice(questions)}, timeout=180
        )

        print(f"RAG status: {r2.status_code}", flush=True)
        print("Cycle completed.", flush=True)

    except requests.RequestException as exc:
        print(f"Request error: {exc}", flush=True)

    time.sleep(360)

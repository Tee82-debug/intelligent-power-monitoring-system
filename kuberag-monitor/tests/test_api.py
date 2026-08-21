from app import main
from app.main import app
from fastapi.testclient import TestClient

client = TestClient(app)


def test_home_endpoint():
    response = client.get("/")

    assert response.status_code == 200

    data = response.json()

    assert data["project"] == "KubeRAG MLOps Monitor"
    assert data["status"] == "running"
    assert "health_model_loaded" in data


def test_predict_health_rejects_cpu_above_100():
    response = client.post(
        "/predict-health",
        json={"cpu_usage": 101, "memory_usage": 50, "pod_count": 5, "restart_count": 0},
    )

    assert response.status_code == 422


def test_predict_health_rejects_negative_values():
    response = client.post(
        "/predict-health",
        json={
            "cpu_usage": 50,
            "memory_usage": 50,
            "pod_count": -1,
            "restart_count": -1,
        },
    )

    assert response.status_code == 422


def test_ask_rejects_empty_question():
    response = client.post("/ask", json={"question": ""})

    assert response.status_code == 422


def test_ask_rejects_question_over_500_characters():
    response = client.post("/ask", json={"question": "a" * 501})

    assert response.status_code == 422


def test_predict_health_model_unavailable(monkeypatch):
    monkeypatch.setattr(main, "health_model", None)

    response = client.post(
        "/predict-health",
        json={"cpu_usage": 50, "memory_usage": 60, "pod_count": 10, "restart_count": 0},
    )

    assert response.status_code == 503
    assert "model is unavailable" in response.json()["detail"]


def test_predict_health_success(monkeypatch):
    class FakeHealthModel:
        def predict(self, data):
            return ["healthy"]

    monkeypatch.setattr(main, "health_model", FakeHealthModel())

    response = client.post(
        "/predict-health",
        json={"cpu_usage": 45, "memory_usage": 60, "pod_count": 8, "restart_count": 0},
    )

    assert response.status_code == 200

    body = response.json()

    assert body["cpu_usage"] == 45
    assert body["memory_usage"] == 60
    assert body["pod_count"] == 8
    assert body["restart_count"] == 0
    assert body["predicted_cluster_status"] == "healthy"


def test_ask_success(monkeypatch):
    class FakeCollection:
        def query(self, query_texts, n_results):
            return {
                "documents": [["Node CPU usage is 45%.", "Node memory usage is 60%."]]
            }

    class FakeChromaClient:
        def get_collection(self, name):
            return FakeCollection()

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"response": "The Kubernetes node is operating normally."}

    monkeypatch.setattr(
        main.chromadb, "HttpClient", lambda host, port: FakeChromaClient()
    )

    monkeypatch.setattr(main.requests, "post", lambda *args, **kwargs: FakeResponse())

    response = client.post(
        "/ask", json={"question": "What is the current node status?"}
    )

    assert response.status_code == 200

    body = response.json()

    assert body["question"] == "What is the current node status?"
    assert "Node CPU usage is 45%." in body["retrieved_context"]
    assert body["answer"] == ("The Kubernetes node is operating normally.")


def test_ask_chromadb_failure(monkeypatch):
    def fake_http_client(*args, **kwargs):
        raise RuntimeError("ChromaDB unavailable")

    monkeypatch.setattr(main.chromadb, "HttpClient", fake_http_client)

    response = client.post(
        "/ask", json={"question": "What is the current node status?"}
    )

    assert response.status_code == 503
    assert "ChromaDB query failed" in response.json()["detail"]


def test_ask_ollama_timeout(monkeypatch):
    class FakeCollection:
        def query(self, query_texts, n_results):
            return {"documents": [["Node CPU usage is 45%."]]}

    class FakeChromaClient:
        def get_collection(self, name):
            return FakeCollection()

    monkeypatch.setattr(
        main.chromadb, "HttpClient", lambda host, port: FakeChromaClient()
    )

    def fake_post(*args, **kwargs):
        raise main.requests.Timeout("Ollama timed out")

    monkeypatch.setattr(main.requests, "post", fake_post)

    response = client.post(
        "/ask", json={"question": "What is the current node status?"}
    )

    assert response.status_code == 504
    assert response.json()["detail"] == "Ollama request timed out."


def test_ask_ollama_service_failure(monkeypatch):
    class FakeCollection:
        def query(self, query_texts, n_results):
            return {"documents": [["Node CPU usage is 45%."]]}

    class FakeChromaClient:
        def get_collection(self, name):
            return FakeCollection()

    monkeypatch.setattr(
        main.chromadb, "HttpClient", lambda host, port: FakeChromaClient()
    )

    def fake_post(*args, **kwargs):
        raise main.requests.RequestException("Ollama unavailable")

    monkeypatch.setattr(main.requests, "post", fake_post)

    response = client.post(
        "/ask", json={"question": "What is the current node status?"}
    )

    assert response.status_code == 503
    assert "Ollama service request failed" in (response.json()["detail"])

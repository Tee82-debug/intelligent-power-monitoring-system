from fastapi.testclient import TestClient

from app.main import app


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
        json={
            "cpu_usage": 101,
            "memory_usage": 50,
            "pod_count": 5,
            "restart_count": 0
        }
    )

    assert response.status_code == 422


def test_predict_health_rejects_negative_values():
    response = client.post(
        "/predict-health",
        json={
            "cpu_usage": 50,
            "memory_usage": 50,
            "pod_count": -1,
            "restart_count": -1
        }
    )

    assert response.status_code == 422


def test_ask_rejects_empty_question():
    response = client.post(
        "/ask",
        json={"question": ""}
    )

    assert response.status_code == 422


def test_ask_rejects_question_over_500_characters():
    response = client.post(
        "/ask",
        json={"question": "a" * 501}
    )

    assert response.status_code == 422
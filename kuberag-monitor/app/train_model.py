import pandas as pd
import joblib
import mlflow
import mlflow.sklearn

mlflow.set_tracking_uri("http://127.0.0.1:30500")

from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, f1_score, classification_report

df = pd.read_csv("data/cluster_health.csv")

X = df[["cpu_usage", "memory_usage", "pod_count", "restart_count"]]
y = df["status"]

X_train, X_test, y_train, y_test = train_test_split(
    X,
    y,
    test_size=0.3,
    random_state=42,
    stratify=y
)

model = RandomForestClassifier(
    n_estimators=100,
    random_state=42
)

model.fit(X_train, y_train)

predictions = model.predict(X_test)

accuracy = accuracy_score(y_test, predictions)
f1 = f1_score(y_test, predictions, average="weighted")

print("Tracking URI:", mlflow.get_tracking_uri())
mlflow.set_experiment("kuberag-cluster-health")

with mlflow.start_run():
    mlflow.log_param("model_type", "RandomForestClassifier")
    mlflow.log_param("n_estimators", 100)
    mlflow.log_metric("accuracy", accuracy)
    mlflow.log_metric("f1_score", f1)

    mlflow.sklearn.log_model(model, "cluster_health_model")

joblib.dump(model, "models/cluster_health_model.pkl")

print("Model trained successfully")
print("Accuracy:", accuracy)
print("F1 Score:", f1)
print(classification_report(y_test, predictions))

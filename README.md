# Intelligent Power Monitoring & Distribution System

**Infrastructure Monitoring | Power Analytics | Anomaly Detection | Forecasting | AI-Assisted Operations**

Developed in collaboration with **TARTIGRADE Limited** and the **Foundation of Energy Collective (FEC)**  
**August 2026**

---

## Project Overview

The **Intelligent Power Monitoring & Distribution System (IPMDS)** is a real-time infrastructure monitoring and analytics prototype designed to improve visibility into electrical consumption and compute-system performance.

The system combines **power monitoring, Kubernetes observability, anomaly detection, power forecasting, interactive dashboards, alert management, and AI-assisted infrastructure analysis** within a centralized monitoring architecture.

The implemented prototype was validated on a **single-node k3s environment running on Ubuntu Server**. A **Smart Plug connected to the prototype node** provided real-time electrical measurements, while Prometheus and Kubernetes monitoring components collected node- and pod-level infrastructure metrics.

The architecture was designed to support future expansion to larger multi-node compute environments.

Monitoring and analytical processes operate at approximately **15-second intervals**, enabling near-real-time visibility into infrastructure and power behavior.

---

## Problem Statement

Modern compute environments can produce highly variable electrical loads as workloads, CPU utilization, memory demand, containers, and other infrastructure activity change over time.

Limited visibility into these patterns can create several challenges:

- Unexpected power spikes
- Infrastructure capacity constraints
- Uneven or inefficient power utilization
- Difficulty correlating compute activity with electrical demand
- Limited ability to detect abnormal operating conditions
- Uncertainty when planning future compute expansion

This project investigates how real-time monitoring, data analytics, machine learning, and infrastructure observability can improve the understanding and management of compute-related electrical demand.

---

## Project Objectives

The project was developed to:

1. Collect and analyze real-time electrical power consumption.
2. Monitor Kubernetes node and pod performance.
3. Centralize infrastructure and power data in Elasticsearch.
4. Detect abnormal power behavior using machine learning.
5. Forecast short-term electrical demand.
6. Develop interactive operational dashboards.
7. Support alert and incident lifecycle management.
8. Provide AI-assisted infrastructure insights through KubeRAG.
9. Establish a monitoring architecture that can scale to larger compute environments.

---

## System Architecture

The solution combines two primary monitoring streams: physical electrical monitoring and Kubernetes infrastructure monitoring.

### Power Monitoring Pipeline

```text
Single-Node k3s Prototype
          │
          ▼
      Smart Plug
          │
          ▼
  Python Power Collector
          │
          ▼
     Elasticsearch
          │
    ┌─────┴──────────────┐
    │                    │
    ▼                    ▼
Isolation Forest       Prophet
Anomaly Detection    Forecasting
    │                    │
    ▼                    ▼
Power Anomalies      Power Forecast
    │                    │
    └─────────┬──────────┘
              ▼
            Kibana
```

### Kubernetes Monitoring Pipeline

```text
Single-Node k3s Prototype
          │
          ▼
     k3s / Kubernetes
          │
          ▼
      Prometheus
          │
          ▼
  Node & Pod Metrics
          │
          ▼
   Python Collectors
          │
          ▼
     Elasticsearch
          │
     ┌────┴───────────────┐
     │                    │
     ▼                    ▼
Kibana / Grafana    KubeRAG / FastAPI
```

Together, these pipelines provide centralized visibility into electrical consumption, infrastructure performance, anomalies, forecasts, and system health.

---

## Core Capabilities

### Real-Time Power Monitoring

Electrical measurements for the single-node prototype are collected using a **Smart Plug connected to the compute node**.

Measurements include:

- Power (W)
- Voltage (V)
- Current (A)
- Timestamped electrical measurements

The Smart Plug provides **aggregate electrical measurements for the single-node prototype**.

The collected data is ingested into Elasticsearch for visualization, historical analysis, anomaly detection, and forecasting.

### Kubernetes Monitoring

Prometheus and Kubernetes monitoring components provide visibility into node and pod activity within the k3s environment.

Monitored infrastructure metrics include:

- CPU utilization
- Memory utilization
- Pod count
- Restart count
- Node status
- Network activity

These metrics provide the compute-side context required to understand infrastructure activity alongside electrical consumption.

### Anomaly Detection

The system uses an **Isolation Forest** machine learning model to identify unusual power-consumption patterns.

Current model configuration:

| Parameter | Value |
|---|---:|
| Algorithm | Isolation Forest |
| Estimators | 150 |
| Contamination | 0.03 |
| Random State | 42 |

Detected anomalies are stored separately for visualization and operational investigation.

### Power Forecasting

**Prophet** is used to generate short-term power-consumption forecasts from historical electrical measurements.

Forecast performance is evaluated using:

- Mean Absolute Error (MAE)
- Root Mean Squared Error (RMSE)
- Mean Absolute Percentage Error (MAPE)

This provides a foundation for proactive infrastructure monitoring and future capacity planning.

### Alert & Incident Management

The monitoring system includes functionality supporting the lifecycle of infrastructure alerts.

Capabilities include:

- Alert enrichment
- Alert acknowledgment
- Incident tracking
- Alert age monitoring
- Alert resolution

These components provide a structured workflow for investigating and responding to abnormal infrastructure conditions.

### KubeRAG Monitor

KubeRAG extends the monitoring platform with an AI-assisted interface for infrastructure analysis.

The application integrates:

- FastAPI
- ChromaDB
- Ollama
- Llama 3.2

Key API capabilities include:

- `/predict-health` for infrastructure health assessment
- `/ask` for natural-language infrastructure queries

The health prediction capability evaluates infrastructure indicators such as CPU usage, memory usage, pod count, and restart count.

---

## Elasticsearch Data Model

The implementation separates raw infrastructure measurements from analytical outputs.

| Index | Purpose |
|---|---|
| `shelly-power-monitoring` | Real-time electrical measurements from the Smart Plug |
| `node-metrics` | Kubernetes node performance and health metrics |
| `pod-metrics` | Kubernetes pod-level operational metrics |
| `power-anomalies` | Isolation Forest anomaly detection results |
| `power-forecast` | Prophet power-demand forecasts |

This separation supports independent analysis, visualization, and lifecycle management of raw and derived data.

---

## Monitoring Dashboards

The project includes dashboards designed to provide different views of infrastructure and power behavior.

### Intelligent Operations Dashboard

Provides a consolidated view of infrastructure health, power consumption, anomalies, and operational indicators.

### Node Metrics Dashboard

Displays node-level CPU, memory, workload, and infrastructure health metrics.

### Pod Metrics Dashboard

Provides visibility into Kubernetes pod resource utilization and operational behavior.

### Power Forecast Dashboard

Visualizes historical power consumption, short-term forecasts, forecast errors, and forecasting performance.

---

## Conceptual Framework

The prototype combines physical electrical measurements and compute infrastructure metrics from the same single-node environment.

```text
                       SINGLE-NODE PROTOTYPE
                               │
                 ┌─────────────┴─────────────┐
                 │                           │
                 ▼                           ▼
             Smart Plug               k3s / Prometheus
                 │                           │
                 ▼                           ▼
        Electrical Metrics             Compute Metrics
       Power / Voltage /              CPU / Memory /
            Current                   Pods / Restarts
                 │                           │
                 └─────────────┬─────────────┘
                               ▼
                         Elasticsearch
                               │
                 ┌─────────────┼─────────────┐
                 │             │             │
                 ▼             ▼             ▼
              Kibana       Isolation      Prophet
                          Forest Anomaly  Forecasting
                            Detection
                               │             │
                               ▼             ▼
                         power-anomalies  power-forecast
```

This framework enables electrical behavior and compute activity to be analyzed within a common monitoring environment.

---

## Technology Stack

| Category | Technologies |
|---|---|
| Infrastructure | Ubuntu Server, k3s, Docker |
| Monitoring | Prometheus, node_exporter, kube-state-metrics, Grafana |
| Data Platform | Elasticsearch, Kibana |
| Programming | Python, Bash |
| Machine Learning | Isolation Forest, Prophet |
| API | FastAPI |
| AI / RAG | ChromaDB, Ollama, Llama 3.2 |
| Version Control | Git, GitHub |

---

## Repository Structure

```text
intelligent-power-monitoring-system/
│
├── power-monitoring/
│   ├── forecasting/
|   |   ├── model_comparison/
│   |   ├── __init__.py
│   |   ├── compare_prophet_models.py
│   |   ├── config.py
│   |   ├── elastic_loader.py
│   |   ├── evaluate_forecasts.py
│   |   ├── forecast_alert_engine.py
│   |   ├── forecast_data_generator.py
│   |   ├── model_utils.py
│   |   ├── predict_prophet.py
│   |   ├── run_forecast_pipeline.sh
│   |   └── train_prophet.py
│   ├── acknowledge_alert.py
│   ├── anomaly_detector.py
│   ├── collector.env.example
│   ├── enrich_alerts.py
│   ├── incident_manager.py
│   ├── pod_metrics_collector.py
│   ├── real_node_collector.py
│   ├── requirements.txt
│   ├── resolve_alert.py
│   └── update_alert_ages.py
│
├── kuberag-monitor/
│   ├── app/                    # Application/RAG code
│   ├── data/                   # cluster_health_csv                    
│   ├── k8s/                    # Kubernetes manifests
│   ├── workloads/              # Load-generation workload
│   ├── Dockerfile
│   ├── requirements.txt
│   └── README.md
│
├── .gitignore
└── README.md
```

### Main Components

`power-monitoring/` contains the primary monitoring, anomaly detection, forecasting, and alert/incident-management components.

`kuberag-monitor/` contains the FastAPI-based AI-assisted Kubernetes monitoring application and its deployment resources.

---

## Configuration

Sensitive configuration values must not be committed to Git.

The repository provides:

```text
power-monitoring/collector.env.example
```

as a template for local configuration.

From the repository root, create the local configuration file:

```bash
cp power-monitoring/collector.env.example power-monitoring/collector.env
```

Update `collector.env` with the appropriate local configuration.

Example:

```env
ES_ENDPOINT=https://your-elasticsearch-endpoint
ES_API_KEY=your-api-key-here

ES_INDEX=capstone-cx002-node-metrics
POD_ES_INDEX=capstone-cx002-pod-metrics

PROMETHEUS_URL=http://localhost:30900
NODE_NAME=cx-002

POD_INTERVAL_SECONDS=15
ANOMALY_INTERVAL_SECONDS=30
```

> **Security:** Never commit `collector.env`, Elasticsearch API keys, passwords, authentication tokens, or other credentials.

---

## Getting Started

### 1. Clone the Repository

```bash
git clone https://github.com/Tee82-debug/intelligent-power-monitoring-system.git
cd intelligent-power-monitoring-system
```

### 2. Create a Python Virtual Environment

```bash
python3 -m venv .venv
```

Activate the environment on Linux/macOS:

```bash
source .venv/bin/activate
```

On Windows:

```powershell
.venv\Scripts\activate
```

### 3. Configure Environment Variables

From the repository root:

```bash
cp power-monitoring/collector.env.example power-monitoring/collector.env
```

Edit the newly created `collector.env` and provide the appropriate Elasticsearch and monitoring configuration.

### 4. Install Dependencies


Install the power monitoring and analytics dependencies:

```bash
pip install -r power-monitoring/requirements.txt

Install the KubeRAG dependencies:.

```bash
pip install -r kuberag-monitor/requirements.txt
```

> The monitoring and analytics components may require additional Python dependencies. A dedicated requirements file should be maintained for these components to provide a fully reproducible environment.

### 5. Start a Collector

From the repository root:

```bash
python3 power-monitoring/real_node_collector.py
```

For background execution on Linux:

```bash
nohup python3 power-monitoring/real_node_collector.py > collector.log 2>&1 &
```

Additional monitoring and analytical services should be started according to their individual configuration requirements.

---

## System Requirements

The prototype environment includes:

- Python 3.12+
- Ubuntu Server
- k3s / Kubernetes
- Docker
- Elasticsearch 8.x
- Kibana 8.x
- Prometheus
- node_exporter
- kube-state-metrics
- Grafana
- Smart Plug for electrical measurements

Some monitoring components may additionally use hardware-level power telemetry where supported by the host system.

---

## Security Considerations

The repository should not contain:

- Elasticsearch API keys
- Passwords
- Authentication tokens
- `.env` files
- Private infrastructure credentials
- Sensitive monitoring datasets
- Generated secrets

Environment-specific configuration should be maintained locally using files excluded through `.gitignore`.

If a credential is accidentally committed to Git, removing it from the current file alone is not sufficient. The exposed credential should be revoked or rotated.

---

## Current Limitations

The current prototype has several important limitations:

- The implemented environment was validated on a **single k3s node**.
- Smart Plug measurements represent **aggregate electrical consumption of the single-node prototype** and do not provide component-level power attribution.
- Forecast quality depends on the amount and quality of historical power data available.
- The prototype focuses primarily on monitoring, analytics, forecasting, and operational intelligence rather than automated electrical switching.
- Additional validation would be required before deploying the architecture in a production-scale multi-node compute environment.

---

## Future Development

Potential extensions include:

- Multi-node Kubernetes monitoring
- Circuit-level electrical monitoring
- Automated load-balancing recommendations
- Predictive capacity planning
- Longer-horizon power forecasting
- Expanded anomaly classification
- Automated alert routing
- Additional hardware telemetry
- Energy-efficiency optimization
- Automated workload-to-power correlation
- Enhanced AI-assisted infrastructure diagnostics

---

## Contributors

- Ifeanyi Njoku
- Toheeb Ayuba

## Project Supervisor

**Tanzi Chowdhury**  
TARTIGRADE Limited

---

## Acknowledgements

This project was developed as a collaborative capstone initiative with support from **TARTIGRADE Limited** and the **Foundation of Energy Collective (FEC)**.

The project provided practical experience across infrastructure monitoring, Kubernetes observability, data engineering, machine learning, power analytics, dashboard development, and AI-assisted operations.

# Intelligent Power Monitoring and Distribution System
## FEC Canada | Tartigrade Limited | August 2026

### Project Overview
Real-time power monitoring and anomaly detection system for an 
80-node HPC cluster using Elasticsearch, Kibana, Intel RAPL, 
and Shelly smart plugs.

### Repository Structure

cx002-power-poc/
  real_node_collector.py     — Main data collection service
  pod_metrics_collector.py   — Kubernetes pod metrics collector
  anomaly_detector.py        — Isolation Forest anomaly detection
  incident_manager.py        — Alert lifecycle management
  acknowledge_alert.py       — Alert acknowledgment
  resolve_alert.py           — Alert resolution
  enrich_alerts.py           — Alert enrichment
  update_alert_ages.py       — Alert age tracking
  forecasting/               — Prophet forecasting module
  collector.env.example      — Environment variable template

kuberag-monitor/
  app/                       — FastAPI RAG application
  k8s/                       — Kubernetes deployment manifests
  data/                      — Training datasets
  models/                    — Trained ML models
  Dockerfile                 — Container build file
  requirements.txt           — Python dependencies

### Setup Instructions
1. Copy collector.env.example to collector.env
2. Fill in your Elasticsearch endpoint and API key
3. Install dependencies: pip install -r requirements.txt
4. Run collector: nohup python3 real_node_collector.py > collector.log 2>&1 &

### Requirements
- Python 3.12+
- Elasticsearch 8.x
- Kibana 8.x
- Prometheus Node Exporter on port 9100
- Intel RAPL available via /sys/class/powercap/intel-rapl/

### Team
- Ifeanyi Njoku
- Toheeb Ayuba

### Supervisor
Tanzi Chowdhury — Tartigrade Limited

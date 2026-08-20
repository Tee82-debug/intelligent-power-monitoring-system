import os
import time
from datetime import datetime, timezone

import requests
from elasticsearch import Elasticsearch
from dotenv import load_dotenv


load_dotenv(os.path.join(os.path.dirname(__file__), "collector.env"))

PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://localhost:30900")
NODE_NAME = os.getenv("NODE_NAME", "cx-002")
INTERVAL_SECONDS = int(os.getenv("POD_INTERVAL_SECONDS", "15"))

ES_ENDPOINT = os.getenv("ES_ENDPOINT")
ES_API_KEY = os.getenv("ES_API_KEY")
ES_INDEX = os.getenv("POD_ES_INDEX", "capstone-cx002-pod-metrics")
POD_STATUS_SUMMARY_INDEX = os.getenv("POD_STATUS_SUMMARY_INDEX", "capstone-cx002-pod-status-summary")

if not ES_ENDPOINT:
    raise ValueError("Missing ES_ENDPOINT environment variable")

if not ES_API_KEY:
    raise ValueError("Missing ES_API_KEY environment variable")


es = Elasticsearch(
    ES_ENDPOINT,
    api_key=ES_API_KEY
)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def prometheus_query(query):
    response = requests.get(
        f"{PROMETHEUS_URL}/api/v1/query",
        params={"query": query},
        timeout=10
    )
    response.raise_for_status()

    data = response.json()

    if data.get("status") != "success":
        return []

    return data.get("data", {}).get("result", [])


def value_to_float(result):
    try:
        return float(result["value"][1])
    except Exception:
        return 0.0


def get_pod_info():
    query = f'kube_pod_info{{node="{NODE_NAME}"}}'
    results = prometheus_query(query)

    pods = {}

    for item in results:
        metric = item.get("metric", {})

        namespace = metric.get("namespace", "")
        pod_name = metric.get("pod", "")

        if not namespace or not pod_name:
            continue

        key = (namespace, pod_name)

        pods[key] = {
            "@timestamp": utc_now(),
            "node_name": NODE_NAME,
            "namespace": namespace,
            "pod_name": pod_name,
            "pod_ip": metric.get("pod_ip") or None,
            "host_ip": metric.get("host_ip") or None,
            "created_by_kind": metric.get("created_by_kind", ""),
            "created_by_name": metric.get("created_by_name", ""),
            "priority_class": metric.get("priority_class", ""),
            "source": "ttg_pod_exporter"
        }

    return pods


def add_pod_phase(pods):
    results = prometheus_query("kube_pod_status_phase")

    for item in results:
        metric = item.get("metric", {})

        namespace = metric.get("namespace", "")
        pod_name = metric.get("pod", "")
        phase = metric.get("phase", "")
        value = value_to_float(item)

        key = (namespace, pod_name)

        if key in pods and value == 1:
            pods[key]["pod_status"] = phase


def add_restart_counts(pods):
    query = "sum(kube_pod_container_status_restarts_total) by (namespace, pod)"
    results = prometheus_query(query)

    for item in results:
        metric = item.get("metric", {})
        key = (metric.get("namespace", ""), metric.get("pod", ""))

        if key in pods:
            pods[key]["restart_count"] = value_to_float(item)


def add_cpu_usage(pods):
    query = (
        'sum(rate(container_cpu_usage_seconds_total{image!="", container!=""}[1m])) '
        "by (namespace, pod)"
    )
    results = prometheus_query(query)

    for item in results:
        metric = item.get("metric", {})
        key = (metric.get("namespace", ""), metric.get("pod", ""))

        if key in pods:
            pods[key]["cpu_usage_cores"] = round(value_to_float(item), 6)


def add_memory_usage(pods):
    query = (
        'sum(container_memory_working_set_bytes{image!="", container!=""}) '
        "by (namespace, pod)"
    )
    results = prometheus_query(query)

    for item in results:
        metric = item.get("metric", {})
        key = (metric.get("namespace", ""), metric.get("pod", ""))

        if key in pods:
            memory_bytes = value_to_float(item)
            pods[key]["memory_usage_bytes"] = round(memory_bytes, 2)
            pods[key]["memory_usage_mb"] = round(memory_bytes / (1024 * 1024), 2)


def add_network_bytes(pods):
    queries = {
        "network_rx_bytes_per_sec": (
            "sum(rate(container_network_receive_bytes_total[1m])) "
            "by (namespace, pod)"
        ),
        "network_tx_bytes_per_sec": (
            "sum(rate(container_network_transmit_bytes_total[1m])) "
            "by (namespace, pod)"
        )
    }

    for field, query in queries.items():
        results = prometheus_query(query)

        for item in results:
            metric = item.get("metric", {})
            key = (metric.get("namespace", ""), metric.get("pod", ""))

            if key in pods:
                pods[key][field] = round(value_to_float(item), 2)

    for pod in pods.values():
        pod["network_rx_kb_per_sec"] = round(
            pod.get("network_rx_bytes_per_sec", 0) / 1024,
            2
        )
        pod["network_tx_kb_per_sec"] = round(
            pod.get("network_tx_bytes_per_sec", 0) / 1024,
            2
        )


def add_network_packets(pods):
    queries = {
        "network_rx_packets_per_sec": (
            "sum(rate(container_network_receive_packets_total[1m])) "
            "by (namespace, pod)"
        ),
        "network_tx_packets_per_sec": (
            "sum(rate(container_network_transmit_packets_total[1m])) "
            "by (namespace, pod)"
        )
    }

    for field, query in queries.items():
        results = prometheus_query(query)

        for item in results:
            metric = item.get("metric", {})
            key = (metric.get("namespace", ""), metric.get("pod", ""))

            if key in pods:
                pods[key][field] = round(value_to_float(item), 4)


def add_disk_io(pods):
    queries = {
        "disk_read_bytes_per_sec": (
            'sum(rate(container_fs_reads_bytes_total{container!="", pod!=""}[5m])) '
            "by (namespace, pod)"
        ),
        "disk_write_bytes_per_sec": (
            'sum(rate(container_fs_writes_bytes_total{container!="", pod!=""}[5m])) '
            "by (namespace, pod)"
        )
    }

    for field, query in queries.items():
        results = prometheus_query(query)

        for item in results:
            metric = item.get("metric", {})
            key = (metric.get("namespace", ""), metric.get("pod", ""))

            if key in pods:
                pods[key][field] = round(value_to_float(item), 2)

    for pod in pods.values():
        pod["disk_read_mb_per_sec"] = round(
            pod.get("disk_read_bytes_per_sec", 0) / (1024 * 1024),
            4
        )
        pod["disk_write_mb_per_sec"] = round(
            pod.get("disk_write_bytes_per_sec", 0) / (1024 * 1024),
            4
        )
        pod["disk_read_kb_per_sec"] = round(
            pod.get("disk_read_bytes_per_sec", 0) / 1024,
            2
        )
        pod["disk_write_kb_per_sec"] = round(
            pod.get("disk_write_bytes_per_sec", 0) /1024,
            2
        )

def add_cpu_throttling(pods):
    query = (
        'sum(rate(container_cpu_cfs_throttled_seconds_total{container!="", image!=""}[1m])) '
        "by (namespace, pod)"
    )
    results = prometheus_query(query)

    for item in results:
        metric = item.get("metric", {})
        key = (metric.get("namespace", ""), metric.get("pod", ""))

        if key in pods:
            pods[key]["cpu_throttled_seconds_per_sec"] = round(
                value_to_float(item),
                6
            )


def add_oom_events(pods):
    query = (
        'sum(increase(container_oom_events_total{container!=""}[5m])) '
        "by (namespace, pod)"
    )
    results = prometheus_query(query)

    for item in results:
        metric = item.get("metric", {})
        key = (metric.get("namespace", ""), metric.get("pod", ""))

        if key in pods:
            pods[key]["oom_events_5m"] = int(value_to_float(item))


def add_resource_requests_limits(pods):
    queries = {
        "cpu_request_cores": (
            'sum(kube_pod_container_resource_requests{resource="cpu"}) '
            "by (namespace, pod)"
        ),
        "cpu_limit_cores": (
            'sum(kube_pod_container_resource_limits{resource="cpu"}) '
            "by (namespace, pod)"
        ),
        "memory_request_bytes": (
            'sum(kube_pod_container_resource_requests{resource="memory"}) '
            "by (namespace, pod)"
        ),
        "memory_limit_bytes": (
            'sum(kube_pod_container_resource_limits{resource="memory"}) '
            "by (namespace, pod)"
        )
    }

    for field, query in queries.items():
        results = prometheus_query(query)

        for item in results:
            metric = item.get("metric", {})
            key = (metric.get("namespace", ""), metric.get("pod", ""))

            if key in pods:
                pods[key][field] = value_to_float(item)

    for pod in pods.values():
        memory_request = pod.get("memory_request_bytes", 0)
        memory_limit = pod.get("memory_limit_bytes", 0)

        pod["memory_request_mb"] = (
            round(memory_request / (1024 * 1024), 2)
            if memory_request else 0
        )
        pod["memory_limit_mb"] = (
            round(memory_limit / (1024 * 1024), 2)
            if memory_limit else 0
        )


def add_qos_class(pods):
    results = prometheus_query("kube_pod_status_qos_class > 0")

    for item in results:
        metric = item.get("metric", {})
        key = (metric.get("namespace", ""), metric.get("pod", ""))

        if key in pods:
            pods[key]["qos_class"] = metric.get("qos_class", "")


def add_utilization_percentages(pods):
    for pod in pods.values():
        cpu_used = pod.get("cpu_usage_cores", 0)
        cpu_request = pod.get("cpu_request_cores", 0)
        cpu_limit = pod.get("cpu_limit_cores", 0)

        memory_used = pod.get("memory_usage_bytes", 0)
        memory_request = pod.get("memory_request_bytes", 0)
        memory_limit = pod.get("memory_limit_bytes", 0)

        pod["cpu_request_usage_percent"] = (
            round((cpu_used / cpu_request) * 100, 2)
            if cpu_request else 0
        )
        pod["cpu_limit_usage_percent"] = (
            round((cpu_used / cpu_limit) * 100, 2)
            if cpu_limit else 0
        )
        pod["memory_request_usage_percent"] = (
            round((memory_used / memory_request) * 100, 2)
            if memory_request else 0
        )
        pod["memory_limit_usage_percent"] = (
            round((memory_used / memory_limit) * 100, 2)
            if memory_limit else 0
        )


def add_default_values(pods):
    for pod in pods.values():
        pod["pod_status"] = pod.get("pod_status", "Unknown")
        pod["restart_count"] = pod.get("restart_count", 0)

        pod["cpu_usage_cores"] = pod.get("cpu_usage_cores", 0)
        pod["memory_usage_bytes"] = pod.get("memory_usage_bytes", 0)
        pod["memory_usage_mb"] = pod.get("memory_usage_mb", 0)

        pod["cpu_request_cores"] = pod.get("cpu_request_cores", 0)
        pod["cpu_limit_cores"] = pod.get("cpu_limit_cores", 0)

        pod["memory_request_bytes"] = pod.get("memory_request_bytes", 0)
        pod["memory_limit_bytes"] = pod.get("memory_limit_bytes", 0)
        pod["memory_request_mb"] = pod.get("memory_request_mb", 0)
        pod["memory_limit_mb"] = pod.get("memory_limit_mb", 0)

        pod["cpu_request_usage_percent"] = pod.get("cpu_request_usage_percent", 0)
        pod["cpu_limit_usage_percent"] = pod.get("cpu_limit_usage_percent", 0)
        pod["memory_request_usage_percent"] = pod.get("memory_request_usage_percent", 0)
        pod["memory_limit_usage_percent"] = pod.get("memory_limit_usage_percent", 0)

        pod["network_rx_bytes_per_sec"] = pod.get("network_rx_bytes_per_sec", 0)
        pod["network_tx_bytes_per_sec"] = pod.get("network_tx_bytes_per_sec", 0)
        pod["network_rx_kb_per_sec"] = pod.get("network_rx_kb_per_sec", 0)
        pod["network_tx_kb_per_sec"] = pod.get("network_tx_kb_per_sec", 0)
        pod["network_rx_packets_per_sec"] = pod.get("network_rx_packets_per_sec", 0)
        pod["network_tx_packets_per_sec"] = pod.get("network_tx_packets_per_sec", 0)

        pod["disk_read_bytes_per_sec"] = pod.get("disk_read_bytes_per_sec", 0)
        pod["disk_write_bytes_per_sec"] = pod.get("disk_write_bytes_per_sec", 0)
        pod["disk_read_mb_per_sec"] = pod.get("disk_read_mb_per_sec", 0)
        pod["disk_write_mb_per_sec"] = pod.get("disk_write_mb_per_sec", 0)
        pod["disk_read_kb_per_sec"] = pod.get("disk_read_kb_per_sec", 0)
        pod["disk_write_kb_per_sec"] = pod.get("disk_write_kb_per_sec", 0)

        pod["cpu_throttled_seconds_per_sec"] = pod.get(
            "cpu_throttled_seconds_per_sec",
            0
        )
        pod["oom_events_5m"] = pod.get("oom_events_5m", 0)

        pod["qos_class"] = pod.get("qos_class", "")
        pod["priority_class"] = pod.get("priority_class", "")

VALID_POD_STATUSES = {
    "Running",
    "Pending",
    "Succeeded",
    "Failed",
    "Unknown"
}


def normalize_pod_status(status):
    """
    Return a supported Kubernetes pod status.
    Any missing or unexpected value becomes Unknown.
    """
    if not status:
        return "Unknown"

    normalized_status = str(status).strip().capitalize()

    if normalized_status in VALID_POD_STATUSES:
        return normalized_status

    return "Unknown"


def count_pods_by_status(records):
    """
    Count pods in every supported status category.
    All five categories are always returned, including zeros.
    """
    status_counts = {
        "Running": 0,
        "Pending": 0,
        "Succeeded": 0,
        "Failed": 0,
        "Unknown": 0
    }

    for record in records:
        status = normalize_pod_status(
            record.get("pod_status")
        )
        status_counts[status] += 1

    return status_counts


def send_pod_status_summary(records):
    """
    Write one summary document for each pod status.
    All five documents use the same collection timestamp.
    """
    status_counts = count_pods_by_status(records)
    collection_timestamp = utc_now()

    for status, count in status_counts.items():
        summary_record = {
            "@timestamp": collection_timestamp,
            "node_name": NODE_NAME,
            "pod_status": status,
            "pod_count": count,
            "record_type": "pod_status_summary",
            "source": "ttg_pod_collector"
        }

        es.index(
            index=POD_STATUS_SUMMARY_INDEX,
            document=summary_record
        )

    return status_counts

def collect_pod_records():
    pods = get_pod_info()

    add_pod_phase(pods)
    add_restart_counts(pods)
    add_cpu_usage(pods)
    add_memory_usage(pods)
    add_network_bytes(pods)
    add_network_packets(pods)
    add_disk_io(pods)
    add_cpu_throttling(pods)
    add_oom_events(pods)
    add_resource_requests_limits(pods)
    add_qos_class(pods)
    add_utilization_percentages(pods)
    add_default_values(pods)

    return list(pods.values())


def send_records(records):
    for record in records:
        es.index(index=ES_INDEX, document=record)


def main():
    print(
        f"Starting pod metrics collector for node: "
        f"{NODE_NAME}"
    )
    print(f"Prometheus URL: {PROMETHEUS_URL}")
    print(f"Sending pod metrics to index: {ES_INDEX}")
    print(
        "Sending pod status summaries to index: "
        f"{POD_STATUS_SUMMARY_INDEX}"
    )

    while True:
        try:
            records = collect_pod_records()

            # Existing detailed per-pod documents.
            send_records(records)

            # New five-category status summary.
            status_counts = send_pod_status_summary(
                records
            )

            print(f"Sent {len(records)} pod records")

            print(
                "Pod status summary: "
                f"Running={status_counts['Running']}, "
                f"Pending={status_counts['Pending']}, "
                f"Succeeded={status_counts['Succeeded']}, "
                f"Failed={status_counts['Failed']}, "
                f"Unknown={status_counts['Unknown']}"
            )

        except Exception as error:
            print(f"Pod collector error: {error}")

        time.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    main()

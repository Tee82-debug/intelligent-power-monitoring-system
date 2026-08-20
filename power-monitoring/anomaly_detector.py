import os
import time
from datetime import datetime, timezone, timedelta

import requests
from elasticsearch import Elasticsearch
from dotenv import load_dotenv


load_dotenv(os.path.join(os.path.dirname(__file__), "collector.env"))

ES_ENDPOINT = os.getenv("ES_ENDPOINT")
ES_API_KEY = os.getenv("ES_API_KEY")

NODE_INDEX = os.getenv("ES_INDEX", "capstone-cx002-node-metrics")
POD_INDEX = os.getenv("POD_ES_INDEX", "capstone-cx002-pod-metrics")
ANOMALY_INDEX = os.getenv("ANOMALY_ES_INDEX", "capstone-cx002-anomalies")
HEALTH_INDEX = os.getenv("HEALTH_INDEX", "capstone-cx002-health-status")


PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://localhost:30900")
NODE_NAME = os.getenv("NODE_NAME", "cx-002")

INTERVAL_SECONDS = int(os.getenv("ANOMALY_INTERVAL_SECONDS", "30"))
SUPPRESSION_MINUTES = int(os.getenv("ANOMALY_SUPPRESSION_MINUTES", "30"))

HEALTH_LOOKBACK_MINUTES = int(os.getenv("HEALTH_LOOKBACK_MINUTES", "35"))

if not ES_ENDPOINT:
    raise ValueError("Missing ES_ENDPOINT environment variable")

if not ES_API_KEY:
    raise ValueError("Missing ES_API_KEY environment variable")

es = Elasticsearch(ES_ENDPOINT, api_key=ES_API_KEY)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def suppression_cutoff():
    return (datetime.now(timezone.utc) - timedelta(minutes=SUPPRESSION_MINUTES)).isoformat()


def safe_float(value, default=0.0):
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def latest_doc(index_name):
    result = es.search(
        index=index_name,
        size=1,
        sort=[{"@timestamp": {"order": "desc"}}]
    )
    hits = result.get("hits", {}).get("hits", [])
    return hits[0]["_source"] if hits else None


def latest_pod_docs(size=300):
    result = es.search(
        index=POD_INDEX,
        size=size,
        sort=[{"@timestamp": {"order": "desc"}}]
    )

    docs = []
    seen = set()

    for hit in result.get("hits", {}).get("hits", []):
        source = hit["_source"]
        key = (source.get("namespace"), source.get("pod_name"))

        if key in seen:
            continue

        seen.add(key)
        docs.append(source)

    return docs


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


def pod_restart_increase_last_15m():
    query = (
        "sum(increase(kube_pod_container_status_restarts_total[15m])) "
        "by (namespace, pod)"
    )

    results = prometheus_query(query)
    restart_map = {}

    for item in results:
        metric = item.get("metric", {})
        namespace = metric.get("namespace", "")
        pod = metric.get("pod", "")
        value = safe_float(item.get("value", [None, 0])[1])

        if namespace and pod:
            restart_map[(namespace, pod)] = value

    return restart_map


def recent_anomaly_exists(alert_key):
    result = es.search(
        index=ANOMALY_INDEX,
        size=1,
        query={
            "bool": {
                "filter": [
                    {"term": {"alert_key": alert_key}},
                    {"range": {"@timestamp": {"gte": suppression_cutoff()}}}
                ]
            }
        }
    )

    return result.get("hits", {}).get("total", {}).get("value", 0) > 0


def build_anomaly(
    alert_key,
    category,
    metric,
    value,
    threshold,
    severity,
    message,
    recommendation,
    entity_type="node",
    node_name=NODE_NAME,
    namespace=None,
    pod_name=None,
    source_doc=None
):
    value_num = safe_float(value)
    threshold_num = safe_float(threshold)

    if threshold_num > 0:
        anomaly_score = round(max(0, ((value_num - threshold_num) / threshold_num) * 100), 1)
    else:
        anomaly_score = 0

    # -----------------------------
    # Determine operational risk
    # -----------------------------

    if severity == "CRITICAL":
        risk_level = "CRITICAL"

    elif severity == "WARNING":

        if anomaly_score >= 15:
            risk_level = "HIGH"

        elif anomaly_score >= 5:
            risk_level = "MODERATE"

        else:
            risk_level = "WARNING"

    else:
        risk_level = "LOW"

    return {
        "@timestamp": utc_now(),
        "source_timestamp": source_doc.get("@timestamp") if source_doc else None,
        "alert_key": alert_key,
        "alert_status": "ACTIVE",
        "severity": severity,
        "risk_level": risk_level,
        "category": category,
        "metric": metric,
        "entity_type": entity_type,
        "node_name": node_name,
        "namespace": namespace,
        "pod_name": pod_name,
        "value": str(value),
        "threshold": str(threshold),
        "value_numeric": value_num,
        "cpu_percent": value_num if metric == "cpu_usage_percent" else None,
        "memory_percent": value_num if metric == "memory_usage_percent" else None,
        "disk_percent": value_num if metric == "disk_usage_percent" else None,
        "temperature_c": value_num if metric == "temperature_c" else None,
        "threshold_numeric": threshold_num,
        "anomaly_score": anomaly_score,
        "status": "OPEN",
        "detector_version": "v2.0",
        "message": message,
        "recommendation": recommendation,
        "source": "ttg_anomaly_detector"
    }


# ===========================================================
# Cluster Health Helper
# ===========================================================

def get_latest_node_metrics():
    result = es.search(
        index=NODE_INDEX,
        size=1,
        sort="@timestamp:desc"
    )

    hits = result.get("hits", {}).get("hits", [])

    if not hits:
        return None

    return hits[0]["_source"]


def get_recent_open_anomalies():
    try:
        result = es.search(
            index=ANOMALY_INDEX,
            size=500,
            sort=[{"@timestamp": {"order": "desc"}}],
            query={
                "bool": {
                    "filter": [
                        {
                            "term": {
                                "status": "OPEN"
                            }
                        },
                        {
                            "range": {
                                "@timestamp": {
                                    "gte": (
                                        f"now-{HEALTH_LOOKBACK_MINUTES}m"
                                    )
                                }
                            }
                        }
                    ]
                }
            }
        )

        hits = result.get("hits", {}).get("hits", [])

        return [
            hit.get("_source", {})
            for hit in hits
            if hit.get("_source")
        ]

    except Exception as exc:
        print(f"Unable to retrieve recent open anomalies: {exc}")
        return []


def build_health_status(anomalies):

    node = get_latest_node_metrics()
    recent_open_anomalies = get_recent_open_anomalies()

    print(
        f"Health check: recent_open={len(recent_open_anomalies)}, "
        f"new_this_cycle={len(anomalies)}"
    )

    # Combine anomalies from this cycle with recent open alerts.
    combined_anomalies = recent_open_anomalies + anomalies

    # Remove duplicate documents using alert_key.
    active_by_key = {}

    for anomaly in combined_anomalies:
        alert_key = anomaly.get("alert_key")

        if alert_key:
            active_by_key[alert_key] = anomaly

    active_anomalies = list(active_by_key.values())

    cpu = safe_float(node.get("cpu_usage_percent")) if node else 0
    memory = safe_float(node.get("memory_usage_percent")) if node else 0
    disk = safe_float(node.get("disk_usage_percent")) if node else 0
    temperature = safe_float(node.get("temperature_c")) if node else 0
    voltage = safe_float(node.get("electrical_voltage")) if node else 0

    critical_count = sum(
        1 for a in active_anomalies
        if a.get("severity") == "CRITICAL"
    )

    warning_count = sum(
        1 for a in active_anomalies
        if a.get("risk_level") == "WARNING"
    )
    
    warning_severity_count =  sum(
        1 for a in active_anomalies
        if a.get("severity") == "WARNING"
    )

    high_count = sum(
        1 for a in active_anomalies
        if a.get("risk_level") == "HIGH"
    )

    moderate_count = sum(
        1 for a in active_anomalies
        if a.get("risk_level") == "MODERATE"
    )

    # ---------- CRITICAL ----------

    if (
        critical_count > 0
        or high_count >= 2
        or cpu >= 90
        or memory >= 90
        or disk >= 90
        or temperature >= 80
    ):

        cluster_health = "CRITICAL"
        health_icon = "🔴 CRITICAL"

        if critical_count > 0:
            reason = (
                f"{critical_count} active critical alert(s) detected."
            )
        elif high_count >= 2:
            reason = (
                f"{high_count} active high-risk alerts detected."
            )
        else:
            reason = (
                "A live system metric exceeded its critical threshold."
            )

    # ---------- WARNING ----------

    elif (
        warning_severity_count > 0
        or high_count > 0
        or moderate_count >= 2
        or warning_count > 0
        or cpu >= 80
        or memory >= 80
        or disk >= 80
        or temperature >= 74
        or (voltage > 0 and voltage < 110)
        or voltage > 125
    ):

        cluster_health = "WARNING"
        health_icon = "🟡 WARNING"

        reason = (
            "One or more active alerts or system metrics "
            "are outside normal operating limits."
        )

    # ---------- HEALTHY ----------

    else:

        cluster_health = "HEALTHY"
        health_icon = "🟢 HEALTHY"

        reason = (
            "No active anomalies. System operating normally."
        )

    return {
        "@timestamp": utc_now(),
        "node_name": NODE_NAME,
        "cluster_health": cluster_health,
        "health_icon": health_icon,
        "critical_count": critical_count,
        "high_count": high_count,
        "moderate_count": moderate_count,
        "warning_count": warning_count,
        "warning_severity_count": warning_severity_count,
        "active_anomaly_count": len(active_anomalies),
        "cpu_percent": cpu,
        "memory_percent": memory,
        "disk_percent": disk,
        "temperature_c": temperature,
        "voltage": voltage,
        "health_lookback_minutes": HEALTH_LOOKBACK_MINUTES,
        "reason": reason,
        "source": "ttg_anomaly_detector"
    }


def add_if_new(anomalies, anomaly):
    """
    Always keep the anomaly for the current health assessment.

    The internal _should_index flag determines whether a new
    Elasticsearch anomaly document should be created.
    """
    anomaly["_should_index"] = not recent_anomaly_exists(
        anomaly["alert_key"]
    )

    anomalies.append(anomaly)

# ===========================================================
# Detect Node Anomalies
# ===========================================================

def detect_node_anomalies(node):
    anomalies = []

    cpu = safe_float(node.get("cpu_usage_percent"))
    memory = safe_float(node.get("memory_usage_percent"))
    disk = safe_float(node.get("disk_usage_percent"))
    temperature = safe_float(node.get("temperature_c"))
    blocked = safe_float(node.get("processes_blocked"))
    load_1min = safe_float(node.get("load_1min"))
    cpu_cores = safe_float(node.get("cpu_cores"), 4)

    voltage = safe_float(node.get("electrical_voltage"))
    current = safe_float(node.get("electrical_current_amps"))
    actual_power = safe_float(node.get("actual_power_watts"))
    estimated_power = safe_float(node.get("estimated_node_power_watts"))
    power_error = safe_float(node.get("power_error_watts"))
    accuracy = safe_float(node.get("power_estimation_accuracy_percent"), 100)

    if cpu >= 90:
        add_if_new(anomalies, build_anomaly(
            "node:cpu_usage_percent:critical",
            "NODE_RESOURCE",
            "cpu_usage_percent",
            cpu,
            90,
            "CRITICAL",
            "Node CPU utilization is critically high.",
            "Reduce workload pressure, inspect high-CPU pods, or consider scaling compute capacity.",
            source_doc=node
        ))
    elif cpu >= 80:
        add_if_new(anomalies, build_anomaly(
            "node:cpu_usage_percent:warning",
            "NODE_RESOURCE",
            "cpu_usage_percent",
            cpu,
            80,
            "WARNING",
            "Node CPU utilization is elevated.",
            "Monitor CPU trend and identify pods contributing to increased usage.",
            source_doc=node
        ))

    if memory >= 90:
        add_if_new(anomalies, build_anomaly(
            "node:memory_usage_percent:critical",
            "NODE_RESOURCE",
            "memory_usage_percent",
            memory,
            90,
            "CRITICAL",
            "Node memory utilization is critically high.",
            "Inspect memory-heavy pods and consider increasing memory capacity or reducing workload density.",
            source_doc=node
        ))
    elif memory >= 80:
        add_if_new(anomalies, build_anomaly(
            "node:memory_usage_percent:warning",
            "NODE_RESOURCE",
            "memory_usage_percent",
            memory,
            80,
            "WARNING",
            "Node memory utilization is elevated.",
            "Monitor memory trend and review pod memory requests and limits.",
            source_doc=node
        ))

    if disk >= 90:
        add_if_new(anomalies, build_anomaly(
            "node:disk_usage_percent:critical",
            "NODE_RESOURCE",
            "disk_usage_percent",
            disk,
            90,
            "CRITICAL",
            "Node disk utilization is critically high.",
            "Free disk space, rotate logs, or expand storage capacity.",
            source_doc=node
        ))
    elif disk >= 80:
        add_if_new(anomalies, build_anomaly(
            "node:disk_usage_percent:warning",
            "NODE_RESOURCE",
            "disk_usage_percent",
            disk,
            80,
            "WARNING",
            "Node disk utilization is elevated.",
            "Monitor disk growth and review log or container storage usage.",
            source_doc=node
        ))

    if temperature >= 80:
        add_if_new(anomalies, build_anomaly(
            f"node:temperature_c:critical:{NODE_NAME}",
            "SYSTEM_TEMPERATURE",
            "temperature_c",
            temperature,
            80,
            "CRITICAL",
            "CPU temperature exceeds critical operating limit.",
            "Reduce workload and inspect cooling system.",
            source_doc=node
        ))

    elif temperature >= 74:
        add_if_new(anomalies, build_anomaly(
            f"node:temperature_c:warning:{NODE_NAME}",
            "SYSTEM_TEMPERATURE",
            "temperature_c",
            temperature,
            74,
            "WARNING",
            "CPU temperature is approaching the upper operating limit.",
            "Monitor temperature and system load.",
            source_doc=node
        ))

    if cpu_cores > 0 and load_1min >= cpu_cores * 1.5:
        add_if_new(anomalies, build_anomaly(
            "node:load_1min:high",
            "SYSTEM_LOAD",
            "load_1min",
            load_1min,
            cpu_cores * 1.5,
            "WARNING",
            "System load is high relative to available CPU cores.",
            "Check running workloads and inspect CPU contention.",
            source_doc=node
        ))

    if blocked > 0:
        add_if_new(anomalies, build_anomaly(
            "node:processes_blocked:warning",
            "SYSTEM_PROCESS",
            "processes_blocked",
            blocked,
            0,
            "WARNING",
            "Blocked processes detected.",
            "Investigate disk I/O, memory pressure, or stuck system processes.",
            source_doc=node
        ))

    if 0 < voltage < 110:
        add_if_new(anomalies, build_anomaly(
            "power:voltage:critical_low",
            "POWER_QUALITY",
            "electrical_voltage",
            voltage,
            110,
            "CRITICAL",
            "Voltage is below Hydro One normal operating lower limit for 120 V service.",
            "Check power source stability and confirm with facilities or TTG infrastructure team.",
            source_doc=node
        ))
    elif 0 < voltage < 114:
        add_if_new(anomalies, build_anomaly(
            "power:voltage:warning_low",
            "POWER_QUALITY",
            "electrical_voltage",
            voltage,
            114,
            "WARNING",
            "Voltage is below the preferred operating range around nominal 120 V.",
            "Monitor for sustained undervoltage and validate against Shelly readings.",
            source_doc=node
        ))

    if voltage > 126:
        add_if_new(anomalies, build_anomaly(
            "power:voltage:critical_high",
            "POWER_QUALITY",
            "electrical_voltage",
            voltage,
            126,
            "CRITICAL",
            "Voltage is above Hydro One normal operating upper limit for 120 V service.",
            "Check power quality and confirm whether the reading is sustained.",
            source_doc=node
        ))
    elif voltage > 125:
        add_if_new(anomalies, build_anomaly(
            "power:voltage:warning_high",
            "POWER_QUALITY",
            "electrical_voltage",
            voltage,
            125,
            "WARNING",
            "Voltage is near the upper normal operating boundary.",
            "Monitor for sustained overvoltage.",
            source_doc=node
        ))

    if accuracy < 70:
        add_if_new(anomalies, build_anomaly(
            "power:model_accuracy:low",
            "POWER_MODEL",
            "power_estimation_accuracy_percent",
            accuracy,
            70,
            "WARNING",
            "Power estimation accuracy is low.",
            "Review estimation formula and compare estimated node power against Shelly actual power.",
            source_doc=node
        ))

    if actual_power > 0 and estimated_power > 0 and power_error >= 5:
        add_if_new(anomalies, build_anomaly(
            "power:model_error:high",
            "POWER_MODEL",
            "power_error_watts",
            power_error,
            5,
            "WARNING",
            "Power estimation error is above the prototype tolerance.",
            "Calibrate the node power model using observed CPU, memory, and actual Shelly power readings.",
            source_doc=node
        ))

    if current >= 10:
        add_if_new(anomalies, build_anomaly(
            "power:current:high",
            "POWER_SAFETY",
            "electrical_current_amps",
            current,
            10,
            "CRITICAL",
            "Electrical current is unusually high for this monitored node.",
            "Confirm connected load and review circuit capacity before adding workload.",
            source_doc=node
        ))

    return anomalies


# ===========================================================
# Detect Pod Anomalies
# ===========================================================


def detect_pod_anomalies(pods):
    anomalies = []
    restart_increase = pod_restart_increase_last_15m()

    for pod in pods:
        namespace = pod.get("namespace", "")
        pod_name = pod.get("pod_name", "")
        pod_label = f"{namespace}/{pod_name}"

        status = pod.get("pod_status", "Unknown")

        restarts_15m = safe_float(restart_increase.get((namespace, pod_name), 0))
        oom = safe_float(pod.get("oom_events_5m"))
        cpu_request = safe_float(pod.get("cpu_request_usage_percent"))
        cpu_limit = safe_float(pod.get("cpu_limit_usage_percent"))
        mem_request = safe_float(pod.get("memory_request_usage_percent"))
        mem_limit = safe_float(pod.get("memory_limit_usage_percent"))
        throttled = safe_float(pod.get("cpu_throttled_seconds_per_sec"))

        if status not in ["Running", "Succeeded"]:
            add_if_new(anomalies, build_anomaly(
                f"pod:{namespace}:{pod_name}:status",
                "POD_HEALTH",
                "pod_status",
                status,
                "Running",
                "WARNING",
                f"Pod {pod_label} is not running.",
                "Inspect pod events and logs.",
                entity_type="pod",
                namespace=namespace,
                pod_name=pod_name,
                source_doc=pod
            ))

        if restarts_15m >= 3:
            add_if_new(anomalies, build_anomaly(
                f"pod:{namespace}:{pod_name}:restarts_15m:critical",
                "POD_HEALTH",
                "restart_count_15m",
                restarts_15m,
                3,
                "CRITICAL",
                f"Pod {pod_label} restarted at least 3 times in the last 15 minutes.",
                "Investigate CrashLoopBackOff, container logs, readiness probes, and resource limits.",
                entity_type="pod",
                namespace=namespace,
                pod_name=pod_name,
                source_doc=pod
            ))
        elif restarts_15m >= 1:
            add_if_new(anomalies, build_anomaly(
                f"pod:{namespace}:{pod_name}:restarts_15m:warning",
                "POD_HEALTH",
                "restart_count_15m",
                restarts_15m,
                1,
                "WARNING",
                f"Pod {pod_label} restarted in the last 15 minutes.",
                "Review recent pod events and container logs.",
                entity_type="pod",
                namespace=namespace,
                pod_name=pod_name,
                source_doc=pod
            ))

        if oom > 0:
            add_if_new(anomalies, build_anomaly(
                f"pod:{namespace}:{pod_name}:oom",
                "POD_HEALTH",
                "oom_events_5m",
                oom,
                0,
                "CRITICAL",
                f"Pod {pod_label} had an OOM event in the last 5 minutes.",
                "Increase memory limit or reduce memory usage.",
                entity_type="pod",
                namespace=namespace,
                pod_name=pod_name,
                source_doc=pod
            ))

        if cpu_limit >= 90:
            add_if_new(anomalies, build_anomaly(
                f"pod:{namespace}:{pod_name}:cpu_limit:critical",
                "POD_RESOURCE",
                "cpu_limit_usage_percent",
                cpu_limit,
                90,
                "CRITICAL",
                f"Pod {pod_label} is close to its CPU limit.",
                "Increase CPU limit or reduce CPU-intensive workload.",
                entity_type="pod",
                namespace=namespace,
                pod_name=pod_name,
                source_doc=pod
            ))

        if cpu_request >= 120:
            add_if_new(anomalies, build_anomaly(
                f"pod:{namespace}:{pod_name}:cpu_request:critical",
                "POD_RESOURCE",
                "cpu_request_usage_percent",
                cpu_request,
                120,
                "CRITICAL",
                f"Pod {pod_label} is consuming substantially more CPU than requested.",
                "Increase the CPU request, inspect workload demand, and verify that the CPU limit is appropriate.",
                entity_type="pod",
                namespace=namespace,
                pod_name=pod_name,
                source_doc=pod
        ))

        elif cpu_request >= 90:
            add_if_new(anomalies, build_anomaly(
                f"pod:{namespace}:{pod_name}:cpu_request:warning",
                "POD_RESOURCE",
                "cpu_request_usage_percent",
                cpu_request,
                90,
                "WARNING",
                f"Pod {pod_label} is approaching or exceeding its requested CPU allocation.",
                "Review CPU request sizing and workload demand.",
                entity_type="pod",
                namespace=namespace,
                pod_name=pod_name,
                source_doc=pod
            ))

        if mem_limit >= 90:
            add_if_new(anomalies, build_anomaly(
                f"pod:{namespace}:{pod_name}:memory_limit",
                "POD_RESOURCE",
                "memory_limit_usage_percent",
                mem_limit,
                90,
                "CRITICAL",
                f"Pod {pod_label} is close to its memory limit.",
                "Increase memory limit or reduce memory usage.",
                entity_type="pod",
                namespace=namespace,
                pod_name=pod_name,
                source_doc=pod
            ))
        
        # Memory request utilization is independent of memory limit utilization.
        if mem_request >= 120:
            add_if_new(anomalies, build_anomaly(
                f"pod:{namespace}:{pod_name}:memory_request:critical",
                "POD_RESOURCE",
                "memory_request_usage_percent",
                mem_request,
                120,
                "CRITICAL",
                f"Pod {pod_label} is consuming substantially more memory than requested.",
                (
                    "Review the pod memory request and limit immediately. "
                    "Investigate memory growth or a possible memory leak."
                ),
                entity_type="pod",
                namespace=namespace,
                pod_name=pod_name,
                source_doc=pod
            ))

        
        elif mem_request >= 90:
            add_if_new(anomalies, build_anomaly(
                f"pod:{namespace}:{pod_name}:memory_request:warning",
                "POD_RESOURCE",
                "memory_request_usage_percent",
                mem_request,
                90,
                "WARNING",
                f"Pod {pod_label} is approaching or exceeding its requested memory allocation.",
                "Review memory request sizing and monitor memory consumption.",
                entity_type="pod",
                namespace=namespace,
                pod_name=pod_name,
                source_doc=pod
            ))

        if throttled > 0.01:
            add_if_new(anomalies, build_anomaly(
                f"pod:{namespace}:{pod_name}:cpu_throttling",
                "POD_RESOURCE",
                "cpu_throttled_seconds_per_sec",
                throttled,
                0.01,
                "WARNING",
                f"Pod {pod_label} is experiencing CPU throttling.",
                "Review CPU limits and workload demand.",
                entity_type="pod",
                namespace=namespace,
                pod_name=pod_name,
                source_doc=pod
            ))

    return anomalies


def index_anomalies(anomalies):
    indexed_count = 0

    for anomaly in anomalies:
        should_index = anomaly.pop("_should_index", False)

        if should_index:
            es.index(
                index=ANOMALY_INDEX,
                document=anomaly
            )
            indexed_count += 1

    return indexed_count

def index_health_status(health_doc):
    es.index(index=HEALTH_INDEX, document=health_doc)


def main():
    print("Starting TTG anomaly detector")
    print(f"Node index: {NODE_INDEX}")
    print(f"Pod index: {POD_INDEX}")
    print(f"Anomaly index: {ANOMALY_INDEX}")
    print(f"Suppression window: {SUPPRESSION_MINUTES} minutes")

    while True:
        try:
            all_anomalies = []

            node = latest_doc(NODE_INDEX)
            if node:
                all_anomalies.extend(detect_node_anomalies(node))

            pods = latest_pod_docs(size=300)
            all_anomalies.extend(detect_pod_anomalies(pods))

            index_count = index_anomalies(all_anomalies)

            health_doc = build_health_status(all_anomalies)
            index_health_status(health_doc)

            if all_anomalies:
                print(
                    f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} "
                    f"Current anomalies: {len(all_anomalies)}, "
                    f"newly indexed: {indexed_count}, "
                    f"health: {health_doc['cluster_health']}"
                )

        except Exception as error:
            print(f"Anomaly detector error: {error}")

        time.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    main()

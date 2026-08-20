import os
import time
import socket
import psutil
import subprocess
import re
from datetime import datetime, timezone

import requests
from elasticsearch import Elasticsearch
from dotenv import load_dotenv

#This is to load the environment variables from .env file

load_dotenv(os.path.join(os.path.dirname(__file__), 'collector.env'))

NODE_EXPORTER_URL = "http://localhost:9100/metrics"
NODE_NAME = "cx-002"
NETWORK_INTERFACE = "eno1"
INTERVAL_SECONDS = 15


ES_ENDPOINT = os.getenv("ES_ENDPOINT")
ES_API_KEY = os.getenv("ES_API_KEY")
ES_INDEX = os.getenv("ES_INDEX", "capstone-cx002-node-metrics")


if not ES_ENDPOINT:
    raise ValueError("Missing ES_ENDPOINT environment variable")

if not ES_API_KEY:
    raise ValueError("Missing ES_API_KEY environment variable")


es = Elasticsearch(
    ES_ENDPOINT,
    api_key=ES_API_KEY
)


previous_cpu = None
previous_network = None

def get_logged_in_users():
    try:
        return len(psutil.users())
    except Exception:
        return 0


def get_process_count():
    try:
        return len(psutil.pids())
    except Exception:
        return 0


def get_network_info():
    try:
        for interface, addresses in psutil.net_if_addrs().items():
            for addr in addresses:
                if addr.family == socket.AF_INET and not addr.address.startswith("127."):
                    return {
                        "interface": interface,
                        "ip": addr.address
                    }
    except Exception:
        pass

    return {"interface": "Unknown", "ip": "Unknown"}


def get_swap_usage_percent():
    try:
        return psutil.swap_memory().percent
    except Exception:
        return 0


def get_temperature_c():
    try:
        output = subprocess.check_output("sensors", shell=True).decode()
        match = re.search(r"Package id 0:\s+\+?([0-9.]+)°C", output)
        if match:
            return round(float(match.group(1)), 1)
    except Exception:
        return None


def get_latest_shelly_power():
    try:
        response = es.search(
            index="shelly-power-monitoring",
            size=1,
            sort=[{"@timestamp": {"order": "desc"}}]
        )

        hits = response["hits"]["hits"]

        if len(hits) == 0:
            return {}

        source = hits[0]["_source"]

        return {
            "actual_power_watts": float(source.get("power", {}).get("watts", 0)),
            "electrical_voltage": float(source.get("electrical", {}).get("voltage", 0)),
            "electrical_current": float(source.get("electrical", {}).get("current", 0)),
            "energy_total_wh": float(source.get("energy", {}).get("total_wh", 0))
        }

    except Exception as e:
        print(f"Shelly fetch error: {e}")
        return {}


def fetch_metrics():
    response = requests.get(NODE_EXPORTER_URL, timeout=10)
    response.raise_for_status()
    return response.text.splitlines()


def parse_metric(lines, metric_name):
    for line in lines:
        if line.startswith(metric_name + " "):
            return float(line.split()[-1])
    return None


def parse_cpu_totals(lines):
    cpu_modes = {}

    for line in lines:
        if not line.startswith("node_cpu_seconds_total"):
            continue

        if 'cpu="' not in line or 'mode="' not in line:
            continue

        try:
            cpu = line.split('cpu="')[1].split('"')[0]
            mode = line.split('mode="')[1].split('"')[0]
            value = float(line.split()[-1])
        except Exception:
            continue

        cpu_modes.setdefault(cpu, {})
        cpu_modes[cpu][mode] = value

    return cpu_modes


def calculate_cpu_usage(current_cpu, previous_cpu):
    if previous_cpu is None:
        return 0.0

    busy_modes = {"user", "system", "nice", "softirq", "irq"}


    total_delta = 0.0
    busy_delta = 0.0

    for cpu, modes in current_cpu.items():
        previous_modes = previous_cpu.get(cpu, {})

        current_total = sum(modes.values())
        previous_total = sum(previous_modes.values())
        total_delta += current_total - previous_total

        current_busy = sum(
            modes.get(mode, 0.0) for mode in busy_modes
        )
        previous_busy = sum(
            previous_modes.get(mode, 0.0) for mode in busy_modes
        )
        busy_delta += current_busy - previous_busy

    if total_delta <= 0:
        return 0.0

    usage = (busy_delta / total_delta) * 100
    return round(max(0.0, min(100.0, usage)), 2)


def parse_filesystem_usage(lines):
    root_size = None
    root_avail = None

    for line in lines:
        if 'mountpoint="/"' not in line:
            continue

        if line.startswith("node_filesystem_size_bytes"):
            root_size = float(line.split()[-1])

        if line.startswith("node_filesystem_free_bytes"):
            root_avail = float(line.split()[-1])

    if root_size is None or root_avail is None or root_size == 0:
        return 0.0, 0.0, 0.0, 0.0

    disk_total_gb = round(root_size / (1024 ** 3), 2)
    disk_free_gb = round(root_avail / (1024 ** 3), 2)
    disk_used_gb = round((root_size - root_avail) / (1024 ** 3), 2)
    disk_usage_percent = round(((root_size - root_avail) / root_size) * 100, 2)

    return disk_usage_percent, disk_total_gb, disk_used_gb, disk_free_gb


def parse_network_totals(lines):
    rx_total = 0.0
    tx_total = 0.0

    ignored_devices = ["lo", "docker0"]

    for line in lines:
        if "device=" not in line:
            continue

        if line.startswith("node_network_receive_bytes_total"):
            device = line.split('device="')[1].split('"')[0]
            if device not in ignored_devices:
                rx_total += float(line.split()[-1])

        if line.startswith("node_network_transmit_bytes_total"):
            device = line.split('device="')[1].split('"')[0]
            if device not in ignored_devices:
                tx_total += float(line.split()[-1])

    return rx_total, tx_total


def parse_network_packets_errors_drops(lines):
    """
    Aggregate packet counts, errors, and drops across all real network
    interfaces (excluding loopback and docker0), mirroring the same
    device-filtering approach used in parse_network_totals.

    These are cumulative counters straight from Node Exporter (same as
    node_network_receive_bytes_total), not per-interval deltas.
    """
    rx_packets = 0.0
    tx_packets = 0.0
    rx_errors = 0.0
    tx_errors = 0.0
    rx_drops = 0.0
    tx_drops = 0.0

    ignored_devices = ["lo", "docker0"]

    metric_map = {
        "node_network_receive_packets_total": "rx_packets",
        "node_network_transmit_packets_total": "tx_packets",
        "node_network_receive_errs_total": "rx_errors",
        "node_network_transmit_errs_total": "tx_errors",
        "node_network_receive_drop_total": "rx_drops",
        "node_network_transmit_drop_total": "tx_drops",
    }

    for line in lines:
        if "device=" not in line:
            continue

        matched_field = None
        for metric_name, field in metric_map.items():
            if line.startswith(metric_name):
                matched_field = field
                break

        if matched_field is None:
            continue

        try:
            device = line.split('device="')[1].split('"')[0]
        except IndexError:
            continue

        if device in ignored_devices:
            continue

        try:
            value = float(line.split()[-1])
        except (IndexError, ValueError):
            continue

        if matched_field == "rx_packets":
            rx_packets += value
        elif matched_field == "tx_packets":
            tx_packets += value
        elif matched_field == "rx_errors":
            rx_errors += value
        elif matched_field == "tx_errors":
            tx_errors += value
        elif matched_field == "rx_drops":
            rx_drops += value
        elif matched_field == "tx_drops":
            tx_drops += value

    return rx_packets, tx_packets, rx_errors, tx_errors, rx_drops, tx_drops


def calculate_packet_loss_rate(rx_packets, tx_packets, total_drops):
    """
    Percentage of dropped packets relative to total network traffic
    (successful packets + drops). Returns 0.0 if there's no traffic yet
    to avoid a divide-by-zero on a freshly booted node.
    """
    total_traffic = rx_packets + tx_packets + total_drops

    if total_traffic <= 0:
        return 0.0

    return round((total_drops / total_traffic) * 100, 4)


def calculate_network_rate(current_network, previous_network):
    if previous_network is None:
        return 0.0, 0.0

    current_rx, current_tx = current_network
    previous_rx, previous_tx = previous_network

    rx_mb = max(0.0, (current_rx - previous_rx) / (1024 * 1024))
    tx_mb = max(0.0, (current_tx - previous_tx) / (1024 * 1024))

    return round(rx_mb, 4), round(tx_mb, 4)


def calculate_memory_usage(lines):
    total = parse_metric(lines, "node_memory_MemTotal_bytes")
    available = parse_metric(lines, "node_memory_MemAvailable_bytes")
    free = parse_metric(lines, "node_memory_MemFree_bytes")
    buffers = parse_metric(lines, "node_memory_Buffers_bytes")
    cached = parse_metric(lines, "node_memory_Cached_bytes")

    if total is None or available is None or total == 0:
        return 0.0, 0, 0, 0

    
    grafana_used = total - (free or 0) - (buffers or 0) - (cached or 0)
    grafana_used_percent = round((grafana_used / total) * 100, 2)

    available_used = total - available
    available_used_percent = round((available_used / total) * 100, 2)

    return grafana_used_percent, grafana_used, total, available_used_percent


def calculate_uptime_hours(lines):
    boot_time = parse_metric(lines, "node_boot_time_seconds")

    if boot_time is None:
        return 0.0

    now = datetime.now(timezone.utc).timestamp()
    uptime_hours = (now - boot_time) / 3600
    return round(uptime_hours, 2)


def estimate_power(cpu_percent, memory_percent, load_1min):
    idle_power = 6.0
    dynamic_power = 26.0

    estimated = idle_power + (cpu_percent / 100.0) * dynamic_power

    return round(estimated, 2)


def collect_record():
    global previous_cpu, previous_network

    lines = fetch_metrics()

    current_cpu = parse_cpu_totals(lines)
    cpu_usage_percent = calculate_cpu_usage(current_cpu, previous_cpu)
    previous_cpu = current_cpu

    memory_usage_percent, memory_used_bytes, memory_total_bytes, memory_available_percent = calculate_memory_usage(lines)
    disk_usage_percent, disk_total_gb, disk_used_gb, disk_free_gb = parse_filesystem_usage(lines)

    load_1min = parse_metric(lines, "node_load1") or 0.0
    load_5min = parse_metric(lines, "node_load5") or 0.0
    load_15min = parse_metric(lines, "node_load15") or 0.0
    processes_running = parse_metric(lines, "node_procs_running") or 0.0
    processes_blocked = parse_metric(lines, "node_procs_blocked") or 0.0

    current_network = parse_network_totals(lines)
    network_rx_mb, network_tx_mb = calculate_network_rate(current_network, previous_network)
    previous_network = current_network

    (
        network_rx_packets,
        network_tx_packets,
        network_rx_errors,
        network_tx_errors,
        network_rx_drops,
        network_tx_drops,
    ) = parse_network_packets_errors_drops(lines)

    network_total_drops = network_rx_drops + network_tx_drops
    network_packet_loss_rate = calculate_packet_loss_rate(
        network_rx_packets,
        network_tx_packets,
        network_total_drops,
    )

    uptime_hours = calculate_uptime_hours(lines)

    estimated_power_watts = estimate_power(
        cpu_usage_percent,
        memory_usage_percent,
        load_1min
    )


    shelly = get_latest_shelly_power()

    actual_power_watts = shelly.get("actual_power_watts", 0)
    electrical_voltage = shelly.get("electrical_voltage", 0)
    electrical_current = round(shelly.get("electrical_current", 0), 3)
    electrical_current_ma = round(electrical_current * 1000, 2)
    energy_total_wh = shelly.get("energy_total_wh", 0)

    power_error_watts = round(
        abs(actual_power_watts - estimated_power_watts),
        2
    )

    if actual_power_watts > 0:
        power_estimation_accuracy_percent = round(
            max(
                0,
                100 - (power_error_watts / actual_power_watts * 100)
            ),
            2
        )
    else:
        power_estimation_accuracy_percent = 0

    network_info = get_network_info()

    return {
        "@timestamp": datetime.now(timezone.utc).isoformat(),
        "node_name": NODE_NAME,
        "network_interface": NETWORK_INTERFACE,
        "node_status": "Ready",
        "cpu_usage_percent": cpu_usage_percent,
	"cpu_cores": 4,
	"memory_usage_percent": memory_usage_percent,
	"memory_used_bytes": memory_used_bytes,
	"memory_total_bytes": memory_total_bytes,
	"memory_total_gb": round(memory_total_bytes/1073741824, 2),
	"memory_available_percent": memory_available_percent,
        "disk_usage_percent": disk_usage_percent,
        "disk_total_gb": disk_total_gb,
        "disk_used_gb": disk_used_gb,
        "disk_free_gb": disk_free_gb,
	#"disk_used_bytes": disk_used_bytes,
	#"disk_total_bytes": disk_total_bytes,
	#"disk_total_gb": round(disk_total_bytes/1073741824, 2),
	#"disk_free_bytes": disk_free_bytes,
        "load_1min": load_1min,
        "load_5min": load_5min,
        "load_15min": load_15min,
        "processes_running": processes_running,
        "processes_blocked": processes_blocked,
        "network_rx_mb": network_rx_mb,
        "network_tx_mb": network_tx_mb,
        "network_rx_packets": network_rx_packets,
        "network_tx_packets": network_tx_packets,
        "network_rx_errors": network_rx_errors,
        "network_tx_errors": network_tx_errors,
        "network_rx_drops": network_rx_drops,
        "network_tx_drops": network_tx_drops,
        "network_total_drops": network_total_drops,
        "network_packet_loss_rate": network_packet_loss_rate,
        "uptime_hours": uptime_hours,
        "estimated_node_power_watts": estimated_power_watts,
        "actual_power_watts": actual_power_watts,
        "electrical_voltage": electrical_voltage,
        "electrical_current": electrical_current,
        "electrical_current_amps": round(electrical_current,4),
        "electrical_current_ma": electrical_current_ma,
        "energy_total_wh": energy_total_wh,
        "power_error_watts": power_error_watts,
        "power_estimation_accuracy_percent": power_estimation_accuracy_percent,
        "temperature_c": get_temperature_c(),
        "process_count": get_process_count(),
        "logged_in_users": get_logged_in_users(),
        "ipv4_address": network_info["ip"],
        "detected_network_interface": network_info["interface"],
        "swap_usage_percent": get_swap_usage_percent(),
        "source": "ttg_node_exporter"
        
    }


def send_to_elasticsearch(record):
    response = es.index(index=ES_INDEX, document=record)
    return response


def main():
    print(f"Starting real-node collector for {NODE_NAME}")
    print(f"Sending data to index: {ES_INDEX}")

    while True:
        try:
            record = collect_record()
            send_to_elasticsearch(record)
            print(record)
        except Exception as error:
            print(f"Collector error: {error}")

        time.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    main()

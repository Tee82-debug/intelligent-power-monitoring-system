import argparse
import os
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv
from elasticsearch import Elasticsearch
from elasticsearch.exceptions import NotFoundError


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, "collector.env"))

ES_ENDPOINT = os.getenv("ES_ENDPOINT")
ES_API_KEY = os.getenv("ES_API_KEY")
INCIDENT_INDEX = os.getenv(
    "INCIDENT_INDEX",
    "capstone-cx002-incidents",
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None

    try:
        return datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )
    except (TypeError, ValueError):
        return None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Resolve one CX-002 incident."
    )

    parser.add_argument(
        "incident_id",
        help="Incident ID or Elasticsearch incident document ID.",
    )

    parser.add_argument(
        "--user",
        required=True,
        help="Operator resolving the incident.",
    )

    parser.add_argument(
        "--reason",
        required=True,
        help="Corrective action or recovery explanation.",
    )

    args = parser.parse_args()

    try:
        es = Elasticsearch(
            ES_ENDPOINT,
            api_key=ES_API_KEY,
        )

        try:
            response = es.get(
                index=INCIDENT_INDEX,
                id=args.incident_id,
            )
        except NotFoundError as error:
            raise ValueError(
                f"Incident {args.incident_id} was not found."
            ) from error

        source = response.get("_source", {})

        if source.get("lifecycle_status") == "RESOLVED":
            print("Incident is already resolved.")
            return

        resolved_at = utc_now()
        opened_at = parse_timestamp(source.get("opened_at"))
        acknowledged_at = parse_timestamp(
            source.get("acknowledged_at")
        )

        update_doc = {
            "lifecycle_status": "RESOLVED",
            "resolved_at": resolved_at.isoformat(),
            "resolved_by": args.user,
            "resolution_reason": args.reason,
            "last_updated_at": resolved_at.isoformat(),
        }

        if opened_at:
            resolution_minutes = (
                resolved_at - opened_at
            ).total_seconds() / 60

            update_doc["resolution_minutes"] = round(
                resolution_minutes,
                2,
            )

        if acknowledged_at:
            investigation_minutes = (
                resolved_at - acknowledged_at
            ).total_seconds() / 60

            update_doc["investigation_minutes"] = round(
                investigation_minutes,
                2,
            )

        es.update(
            index=INCIDENT_INDEX,
            id=args.incident_id,
            doc=update_doc,
        )

        print(f"Incident: {args.incident_id}")
        print("Status: RESOLVED")
        print(f"Resolved by: {args.user}")

    except Exception as error:
        print(f"Resolution failed: {error}")
        sys.exit(1)


if __name__ == "__main__":
    main()

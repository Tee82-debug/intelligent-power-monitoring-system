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
        description="Acknowledge one CX-002 incident."
    )

    parser.add_argument(
        "incident_id",
        help="Incident ID or Elasticsearch incident document ID.",
    )

    parser.add_argument(
        "--user",
        required=True,
        help="Operator acknowledging the incident.",
    )

    parser.add_argument(
        "--note",
        default="",
        help="Optional acknowledgement note.",
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
        status = source.get("lifecycle_status")

        if status == "RESOLVED":
            raise ValueError(
                "A resolved incident cannot be acknowledged."
            )

        if status == "ACKNOWLEDGED":
            print("Incident is already acknowledged.")
            return

        acknowledged_at = utc_now()
        opened_at = parse_timestamp(source.get("opened_at"))

        update_doc = {
            "lifecycle_status": "ACKNOWLEDGED",
            "acknowledged_at": acknowledged_at.isoformat(),
            "acknowledged_by": args.user,
            "acknowledgement_note": args.note,
            "last_updated_at": acknowledged_at.isoformat(),
        }

        if opened_at:
            elapsed = (
                acknowledged_at - opened_at
            ).total_seconds() / 60

            update_doc["time_to_acknowledge_minutes"] = round(
                elapsed,
                2,
            )

        es.update(
            index=INCIDENT_INDEX,
            id=args.incident_id,
            doc=update_doc,
        )

        print(f"Incident: {args.incident_id}")
        print("Status: ACKNOWLEDGED")
        print(f"Acknowledged by: {args.user}")

    except Exception as error:
        print(f"Acknowledgement failed: {error}")
        sys.exit(1)


if __name__ == "__main__":
    main()

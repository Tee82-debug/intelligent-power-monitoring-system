import os
from datetime import datetime, timezone

from dotenv import load_dotenv
from elasticsearch import Elasticsearch


load_dotenv("collector.env")

ES_ENDPOINT = os.getenv("ES_ENDPOINT")
ES_API_KEY = os.getenv("ES_API_KEY")
ALERT_INDEX = "capstone-cx002-alert-logs-v2"


es = Elasticsearch(
    ES_ENDPOINT,
    api_key=ES_API_KEY
)


def main():
    response = es.search(
        index=ALERT_INDEX,
        size=1000,
        query={
            "terms": {
                "lifecycle_status": [
                    "OPEN",
                    "ACKNOWLEDGED"
                ]
            }
        }
    )

    now = datetime.now(timezone.utc)
    updated = 0

    for hit in response.get("hits", {}).get("hits", []):
        document_id = hit.get("_id")
        source = hit.get("_source", {})
        opened_at = source.get("opened_at")

        if not document_id or not opened_at:
            continue

        opened_datetime = datetime.fromisoformat(
            opened_at.replace("Z", "+00:00")
        )

        alert_age_minutes = (
            now - opened_datetime
        ).total_seconds() / 60

        es.update(
            index=ALERT_INDEX,
            id=document_id,
            doc={
                "alert_age_minutes": round(
                    alert_age_minutes,
                    2
                )
            }
        )

        updated += 1

    print(f"Updated age for {updated} active alerts.")


if __name__ == "__main__":
    main()

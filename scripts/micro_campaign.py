from __future__ import annotations

import argparse
import time
from typing import Any

import requests


def dispatch_message(
    *,
    base_url: str,
    school_id: str,
    campaign_id: str,
    student_id: str,
    dry_run: bool,
) -> dict[str, Any]:
    response = requests.post(
        f"{base_url.rstrip('/')}/dispatch/messages",
        json={
            "school_id": school_id,
            "student_id": student_id,
            "campaign_id": campaign_id,
            "dry_run": dry_run,
        },
        timeout=60,
    )
    try:
        body = response.json()
    except ValueError:
        body = {"raw": response.text}
    return {"status_code": response.status_code, "body": body}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a small manual campaign")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--school-id", required=True)
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--student-id", action="append", required=True)
    parser.add_argument("--delay-seconds", type=float, default=2.0)
    parser.add_argument("--real-send", action="store_true")
    args = parser.parse_args()

    dry_run = not args.real_send
    print(f"dry_run={dry_run}")

    for student_id in args.student_id:
        result = dispatch_message(
            base_url=args.base_url,
            school_id=args.school_id,
            campaign_id=args.campaign_id,
            student_id=student_id,
            dry_run=dry_run,
        )
        body = result["body"]
        print(
            "student_id={student_id} status_code={status_code} status={status} "
            "message_id={message_id} tracking_ref={tracking_ref}".format(
                student_id=student_id,
                status_code=result["status_code"],
                status=body.get("status"),
                message_id=body.get("message_id"),
                tracking_ref=body.get("tracking_ref"),
            )
        )
        time.sleep(args.delay_seconds)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

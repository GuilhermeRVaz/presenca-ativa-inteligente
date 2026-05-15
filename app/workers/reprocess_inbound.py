from __future__ import annotations

import argparse

from app.application.inbound_service import InboundService
from app.core.logging import logger
from app.infrastructure.supabase.repositories import SupabaseRepository


def reprocess_pending_inbound(*, limit: int = 100) -> dict[str, int]:
    repository = SupabaseRepository()
    service = InboundService(repository=repository)
    rows = repository.list_unprocessed_raw_inbound(limit=limit)

    summary = {"seen": len(rows), "processed": 0, "failed": 0}
    for row in rows:
        payload = row.get("payload") or {}
        message_id = str(row.get("message_id") or "")
        school_id = str(row.get("school_id") or "") or None
        try:
            result = service.process_recorded(payload=payload, school_id=school_id)
        except Exception as exc:
            summary["failed"] += 1
            error = repr(exc)
            logger.error("inbound_reprocess_failed", message_id=message_id, error=error)
            print(f"FAILED message_id={message_id} error={error}")
            continue

        if result.status == "processed":
            summary["processed"] += 1
        else:
            summary["failed"] += 1
            logger.warning(
                "inbound_reprocess_not_processed",
                message_id=message_id,
                status=result.status,
            )

    logger.info("inbound_reprocess_summary", **summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Reprocess pending raw inbound rows")
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    summary = reprocess_pending_inbound(limit=args.limit)
    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

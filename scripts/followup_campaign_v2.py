from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
import time
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

# Ensure the project root is in PYTHONPATH so "from app..." works
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(PROJECT_ROOT / ".env")

from app.core.config import settings
from app.infrastructure.followup_message_catalog import FollowupMessageCatalog
from app.infrastructure.supabase.repositories import SupabaseRepository


def _retry_supabase(operation, max_attempts: int = 5, base_delay: float = 2.0):
    """Retry wrapper for transient Supabase/PostgREST connection errors."""
    last_exc = None
    for attempt in range(1, max_attempts + 1):
        try:
            return operation()
        except Exception as exc:
            last_exc = exc
            if attempt == max_attempts:
                break
            delay = base_delay * (2 ** (attempt - 1))
            print(f"[retry {attempt}/{max_attempts}] Supabase falhou ({type(exc).__name__}), aguardando {delay:.1f}s...")
            time.sleep(delay)
    raise last_exc  # type: ignore[misc]


DEFAULT_SOURCE = (
    r"C:\Users\user\busca-ativa-inteligente\data\storage\campaigns"
    r"\followup_27_nao_respondentes.json"
)


def load_rows(path: Path) -> list[dict[str, Any]]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise ValueError("Follow-up source must be a JSON list")
    return rows


def short_protocol(tracking_ref: str) -> str:
    return hashlib.sha256(tracking_ref.encode("utf-8")).hexdigest()[:6].upper()


def dispatch_message(
    *,
    base_url: str,
    school_id: str,
    campaign_id: str,
    student_id: str,
) -> dict[str, Any]:
    response = requests.post(
        f"{base_url.rstrip('/')}/dispatch/messages",
        json={
            "school_id": school_id,
            "student_id": student_id,
            "campaign_id": campaign_id,
            "dry_run": False,
        },
        timeout=90,
    )
    try:
        body = response.json()
    except ValueError:
        body = {"raw": response.text}
    return {"status_code": response.status_code, "body": body}


def find_student_id(client: Any, *, school_id: str, ra: str) -> str | None:
    rows = (
        client.table("students")
        .select("id")
        .eq("school_id", school_id)
        .eq("ra", ra)
        .limit(1)
        .execute()
        .data
        or []
    )
    return str(rows[0]["id"]) if rows else None


def message_already_exists(client: Any, *, campaign_id: str, student_id: str) -> bool:
    rows = (
        client.table("messages")
        .select("id,status,evolution_msg_id")
        .eq("campaign_id", campaign_id)
        .eq("student_id", student_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    return bool(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Preview or run V2 follow-up campaign")
    parser.add_argument("--source", default=DEFAULT_SOURCE)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--school-id", required=True)
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--max-items", type=int)
    parser.add_argument("--delay-min-seconds", type=float, default=8.0)
    parser.add_argument("--delay-max-seconds", type=float, default=25.0)
    parser.add_argument("--real-send", action="store_true")
    parser.add_argument("--confirm-campaign-id")
    parser.add_argument("--allow-duplicate-phones", action="store_true")
    args = parser.parse_args()

    repository = SupabaseRepository()
    client = repository.client.schema("busca_ativa_v2")
    catalog = FollowupMessageCatalog(school_name=settings.school_name)

    rows = load_rows(Path(args.source))
    if args.max_items:
        rows = rows[: args.max_items]

    prepared: list[dict[str, Any]] = []
    phones: dict[str, list[str]] = {}
    for row in rows:
        ra = str(row.get("ra") or "").strip()
        phone = "".join(ch for ch in str(row.get("phone1_e164") or "") if ch.isdigit())
        if not ra or not phone:
            print(f"SKIP invalid row ra={ra!r} phone={phone!r}")
            continue
        student_id = _retry_supabase(
            lambda: find_student_id(client, school_id=args.school_id, ra=ra)
        )
        if not student_id:
            print(f"SKIP student not found ra={ra}")
            continue
        phones.setdefault(phone, []).append(ra)
        prepared.append({"ra": ra, "phone": phone, "student_id": student_id})

    duplicates = {phone: ras for phone, ras in phones.items() if len(ras) > 1}
    if duplicates:
        print("ATENCAO: telefones duplicados encontrados:")
        for phone, ras in duplicates.items():
            print(f"  phone={phone} ras={','.join(ras)}")
        if args.real_send and not args.allow_duplicate_phones:
            print("Envio real bloqueado. Use --allow-duplicate-phones se quiser enviar mesmo assim.")
            return 2

    if args.real_send and args.confirm_campaign_id != args.campaign_id:
        print("Envio real bloqueado. Informe --confirm-campaign-id igual ao --campaign-id.")
        return 2

    print(f"mode={'REAL_SEND' if args.real_send else 'PREVIEW_ONLY'}")
    print(f"campaign_id={args.campaign_id}")
    print(f"items={len(prepared)}")

    for index, item in enumerate(prepared, start=1):
        context = _retry_supabase(
            lambda: repository.get_outbound_context(
                school_id=args.school_id,
                student_id=item["student_id"],
                campaign_id=args.campaign_id,
            )
        )
        tracking_ref = f"CMP{args.campaign_id}-STU{item['student_id']}"
        template_id, body = catalog.build_message(
            parent_name=context.guardian.name,
            student_name=context.student.name,
            class_name=context.student.class_name,
            absence_days=context.campaign.absence_days,
            campaign_id=args.campaign_id,
            unique_key=f"{item['student_id']}|{context.guardian.id}",
            campaign_name=context.campaign.name,
        )
        body = f"{body}\n\nProtocolo: {short_protocol(tracking_ref)}"

        print("")
        print(f"[{index}/{len(prepared)}] ra={item['ra']} student_id={item['student_id']}")
        print(f"to={context.guardian.wa_jid} template={template_id}")
        print(body)

        if not args.real_send:
            continue

        if _retry_supabase(
            lambda: message_already_exists(client, campaign_id=args.campaign_id, student_id=item["student_id"])
        ):
            print("SKIP already has message for this campaign/student")
            continue

        result = dispatch_message(
            base_url=args.base_url,
            school_id=args.school_id,
            campaign_id=args.campaign_id,
            student_id=item["student_id"],
        )
        response_body = result["body"]
        print(
            "RESULT status_code={status_code} status={status} ok={ok} "
            "message_id={message_id} evolution_msg_id={evolution_msg_id}".format(
                status_code=result["status_code"],
                status=response_body.get("status"),
                ok=response_body.get("ok"),
                message_id=response_body.get("message_id"),
                evolution_msg_id=response_body.get("evolution_msg_id"),
            )
        )
        delay = random.uniform(args.delay_min_seconds, args.delay_max_seconds)
        print(f"sleep={delay:.1f}s")
        time.sleep(delay)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

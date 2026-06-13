import sys
import io
from pathlib import Path
from datetime import datetime, timezone
import argparse
import hashlib

# Force UTF-8 stdout/stderr for Windows console
if sys.platform.startswith("win"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True)

# Bootstrap project paths
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from app.core.config import settings
from app.core.logging import logger
from app.infrastructure.supabase.repositories import SupabaseRepository
from app.infrastructure.obmep_message_catalog import ObmepMessageCatalog


def main():
    parser = argparse.ArgumentParser(description="Create OBMEP notification campaign.")
    parser.add_argument("--dry-run", action="store_true", help="Simulate campaign creation without writing to database.")
    args = parser.parse_args()

    print("Initializing Database Connection...")
    repo = SupabaseRepository()
    client = repo.client.schema("busca_ativa_v2")
    school_id = settings.default_school_id

    if not school_id:
        print("Error: DEFAULT_SCHOOL_ID not configured in .env")
        sys.exit(1)

    campaign_name = "Campanha Informativa — OBMEP 09/06/2026"

    # Define target classes in priority order
    priority_classes = [
        # Priority 1: 8th grade
        "8 ANO 8A INTEGRAL 9H ANUAL",
        "8 ANO 8B INTEGRAL 9H ANUAL",
        # Priority 2: 7th grade
        "7 ANO 7A INTEGRAL 9H ANUAL",
        "7 ANO 7B INTEGRAL 9H ANUAL",
        "7º ano A"
    ]

    print("Fetching students for targeted classes...")
    students_by_class = {}
    total_students_found = 0

    # Query students for each target class
    for cls in priority_classes:
        res = client.table("students").select("id, name, class_name, ra").eq("class_name", cls).execute()
        students = res.data or []
        students_by_class[cls] = students
        total_students_found += len(students)
        print(f"  - {cls}: found {len(students)} students")

    if total_students_found == 0:
        print("No students found in targeted classes. Exiting.")
        sys.exit(0)

    print(f"\nTotal students to process: {total_students_found}")

    # 1. Create or resolve Campaign
    if args.dry_run:
        campaign_id = "dry-run-campaign-id"
        print(f"\n[DRY RUN] Would create or reuse campaign: '{campaign_name}'")
    else:
        # Check if already exists
        existing = client.table("campaigns").select("id").eq("school_id", school_id).eq("name", campaign_name).limit(1).execute().data
        if existing:
            campaign_id = existing[0]["id"]
            print(f"\nCampaign already exists: '{campaign_name}' ({campaign_id})")
        else:
            campaign_data = {
                "school_id": school_id,
                "name": campaign_name,
                "type": "absence",
                "campaign_type": "manual",
                "status": "draft",
                "absence_days": "09/06/2026",
                "total_sent": 0,
                "total_replied": 0
            }
            res = client.table("campaigns").insert(campaign_data).execute()
            if not res.data:
                raise RuntimeError("Failed to create campaign in database.")
            campaign_id = res.data[0]["id"]
            print(f"\nCampaign created successfully: '{campaign_name}' ({campaign_id})")

    # Initialize message catalog
    catalog = ObmepMessageCatalog(school_name=settings.school_name)
    enqueued_count = 0
    skipped_count = 0

    print(f"\nProcessing and enqueuing messages in priority order...")
    # Loop over priority classes in order
    for cls in priority_classes:
        students = students_by_class[cls]
        if not students:
            continue
        print(f"\n--- Processing class: {cls} ---")

        for idx, s in enumerate(students, 1):
            student_id = s["id"]
            student_name = s["name"]
            ra = s["ra"]

            # Resolve primary guardian
            guardian_res = (
                client.table("student_guardians")
                .select("guardian_id, guardians(id, name, phone_e164, wa_jid)")
                .eq("student_id", student_id)
                .eq("is_primary", True)
                .limit(1)
                .execute()
            )

            if not guardian_res.data or not guardian_res.data[0].get("guardians"):
                print(f"  [{idx}/{len(students)}] ⚠️ Primary guardian not found for: {student_name} (RA: {ra}) - Skipping")
                skipped_count += 1
                continue

            guardian = guardian_res.data[0]["guardians"]
            guardian_id = guardian["id"]
            guardian_name = guardian.get("name", "Responsável")
            wa_jid = guardian.get("wa_jid")

            if not wa_jid and guardian.get("phone_e164"):
                # fallback JID format if wa_jid is missing but phone is present
                phone = str(guardian["phone_e164"]).replace("+", "")
                wa_jid = f"{phone}@s.whatsapp.net"

            # Build randomized message text using hash of student and guardian IDs
            unique_key = f"{student_id}|{guardian_id}"
            template_id, custom_message = catalog.build_message(
                parent_name=guardian_name,
                student_name=student_name,
                class_name=cls,
                campaign_id=campaign_id,
                unique_key=unique_key
            )

            tracking_ref = f"OBM{campaign_id[:8]}-STU{student_id[:8]}"

            metadata = {
                "turma": cls,
                "data_falta": "09/06/2026",
                "ra": ra,
                "nome_excel": student_name,
                "guardian_name": guardian_name,
                "guardian_phone": guardian.get("phone_e164", ""),
                "custom_message": custom_message,
                "skip_justification_suffix": True
            }

            if args.dry_run:
                print(f"  [{idx}/{len(students)}] [DRY RUN] Would enqueue message for: {student_name}")
                print(f"    Recipient JID: {wa_jid}")
                print(f"    Template: {template_id}")
                print(f"    Message: {custom_message}\n")
                enqueued_count += 1
            else:
                # Check idempotency
                msg_exist = client.table("messages").select("id").eq("campaign_id", campaign_id).eq("student_id", student_id).limit(1).execute().data
                if msg_exist:
                    print(f"  [{idx}/{len(students)}] - Already enqueued: {student_name}")
                    continue

                row = {
                    "school_id": school_id,
                    "campaign_id": campaign_id,
                    "student_id": student_id,
                    "guardian_id": guardian_id,
                    "tracking_ref": tracking_ref,
                    "wa_jid": wa_jid,
                    "template_id": template_id,
                    "status": "pending",
                    "metadata": metadata
                }
                msg_res = client.table("messages").insert(row).execute()
                if not msg_res.data:
                    print(f"  [{idx}/{len(students)}] ❌ Failed to enqueue message for {student_name}")
                    sys.exit(1)
                print(f"  [{idx}/{len(students)}] ✅ Enqueued message for: {student_name} | Responsável: {guardian_name}")
                enqueued_count += 1

    print(f"\n{'='*60}")
    print(f"  Campaign loading summary")
    print(f"{'='*60}")
    print(f"  Campaign ID    : {campaign_id}")
    print(f"  Enqueued       : {enqueued_count}")
    print(f"  Skipped (no RG): {skipped_count}")
    if args.dry_run:
        print("\n  🧪 DRY RUN: No data was written to Supabase.")
    else:
        print(f"\n  ✅ Queue populated successfully! To send messages run:")
        print(f"     .venv\\Scripts\\python.exe scripts/campaign_orchestrator.py --campaign-id {campaign_id}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()

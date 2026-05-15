from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.infrastructure.supabase.repositories import SupabaseRepository


def main() -> int:
    parser = argparse.ArgumentParser(description="Get campaign report for April 28")
    parser.add_argument("--school-id", required=True)
    parser.add_argument("--campaign-id", help="Specific campaign ID (optional)")
    parser.add_argument("--date", default="2026-04-28", help="Date in YYYY-MM-DD format")
    args = parser.parse_args()

    load_dotenv(".env")
    repository = SupabaseRepository()
    client = repository.client.schema("busca_ativa_v2")

    # Parse target date
    target_date = datetime.strptime(args.date, "%Y-%m-%d").date()
    
    # Build date range for the entire day in UTC
    start_datetime = datetime.combine(target_date, datetime.min.time()).replace(tzinfo=timezone.utc)
    end_datetime = start_datetime + timedelta(days=1)
    
    print(f"Generating report for school {args.school_id} on {args.date}")
    print(f"UTC time range: {start_datetime.isoformat()} to {end_datetime.isoformat()}")
    print("=" * 80)

    # Get campaigns for the date
    campaigns_query = client.table("campaigns").select("id,name,status,created_at")
    if args.campaign_id:
        campaigns_query = campaigns_query.eq("id", args.campaign_id)
    
    campaigns_response = campaigns_query.gte("created_at", start_datetime.isoformat()) \
                                       .lt("created_at", end_datetime.isoformat()) \
                                       .execute()
    
    campaigns = campaigns_response.data or []
    
    if not campaigns:
        print(f"No campaigns found for {args.date}")
        return 0
    
    for campaign in campaigns:
        campaign_id = campaign["id"]
        print(f"\nCAMPAIGN: {campaign['name']} (ID: {campaign_id})")
        print(f"Status: {campaign['status']} | Created: {campaign['created_at']}")
        print("-" * 80)
        
        # Get messages for this campaign
        messages_response = client.table("messages").select(
            "id,status,template_id,sent_at,delivered_at,read_at,replied_at,"
            "evolution_msg_id,tracking_ref,created_at,"
            "students(id,ra,name,class_name),"
            "guardians(id,name,phone_e164,wa_jid)"
        ).eq("campaign_id", campaign_id) \
         .eq("school_id", args.school_id) \
         .execute()
         
        messages = messages_response.data or []
        
        if not messages:
            print("  No messages found for this campaign")
            continue
            
        # Statistics
        total = len(messages)
        sent = len([m for m in messages if m.get("status") == "sent"])
        delivered = len([m for m in messages if m.get("status") == "delivered"])
        read = len([m for m in messages if m.get("status") == "read"])
        replied = len([m for m in messages if m.get("status") == "replied"])
        failed = len([m for m in messages if m.get("status") == "failed"])
        pending = len([m for m in messages if m.get("status") == "pending"])
        no_phone = len([m for m in messages if not m.get("guardians") or 
                       not m["guardians"].get("phone_e164")])
        
        print(f"ESTATÍSTICAS:")
        print(f"  Total destinatários: {total}")
        print(f"  Enviados com sucesso: {sent}")
        print(f"  Entregues: {delivered}")
        print(f"  Lidos: {read}")
        print(f"  Responderam: {replied}")
        print(f"  Falhas no envio: {failed}")
        print(f"  Pendentes: {pending}")
        print(f"  Sem telefone cadastrado: {no_phone}")
        print()
        
        # Detailed list
        print("DETALHAMENTO POR ALUNO:")
        print(f"  {'RA':<12} {'Nome do Aluno':<25} {'Status':<12} {'Telefone':<18} {'Responsável'}")
        print(f"  {'-'*12} {'-'*25} {'-'*12} {'-'*18} {'-'*25}")
        
        for msg in messages:
            student = msg.get("students", {})
            guardian = msg.get("guardians", {})
            
            ra = student.get("ra", "N/A")
            student_name = student.get("name", "N/A")[:24]
            status = msg.get("status", "unknown")
            phone = guardian.get("phone_e164", "SEM TELEFONE") if guardian else "SEM TELEFONE"
            guardian_name = guardian.get("name", "N/A")[:24] if guardian else "N/A"
            
            # Truncate long names for display
            if len(student.get("name", "")) > 24:
                student_name = student.get("name", "")[:21] + "..."
            if guardian and len(guardian.get("name", "")) > 24:
                guardian_name = guardian.get("name", "")[:21] + "..."
                
            print(f"  {ra:<12} {student_name:<25} {status:<12} {phone:<18} {guardian_name}")
        
        print("\n" + "=" * 80)
    
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
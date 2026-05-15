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
    parser = argparse.ArgumentParser(description="Get detailed report for specific campaign")
    parser.add_argument("--school-id", required=True)
    parser.add_argument("--campaign-id", required=True)
    args = parser.parse_args()

    load_dotenv(".env")
    repository = SupabaseRepository()
    client = repository.client.schema("busca_ativa_v2")

    # Get campaign info
    campaign_response = client.table("campaigns").select(
        "id,name,status,absence_days,created_at,updated_at"
    ).eq("id", args.campaign_id).eq("school_id", args.school_id).execute()
    
    if not campaign_response.data:
        print(f"Campaign {args.campaign_id} not found for school {args.school_id}")
        return 1
        
    campaign = campaign_response.data[0]
    print(f"RELATÓRIO DA CAMPANHA: {campaign['name']}")
    print(f"ID: {campaign['id']}")
    print(f"Status: {campaign['status']}")
    print(f"Dias de falta: {campaign['absence_days']}")
    print(f"Criada em: {campaign['created_at']}")
    print(f"Atualizada em: {campaign['updated_at']}")
    print("=" * 80)

    # Get messages for this campaign with student and guardian details
    messages_response = client.table("messages").select(
        "id,status,template_id,sent_at,delivered_at,read_at,replied_at,"
        "evolution_msg_id,tracking_ref,created_at,body_preview,"
        "students(id,ra,name,class_name),"
        "guardians(id,name,phone_e164,wa_jid)"
    ).eq("campaign_id", args.campaign_id) \
     .eq("school_id", args.school_id) \
     .order("created_at") \
     .execute()
     
    messages = messages_response.data or []
    
    if not messages:
        print("No messages found for this campaign")
        return 0
    
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
    
    print(f"ESTATÍSTICAS DE ENVIO:")
    print(f"  Total de destinatários: {total}")
    print(f"  Enviados com sucesso: {sent} ({sent/total*100:.1f}%)" if total > 0 else "  Enviados com sucesso: 0")
    print(f"  Entregues: {delivered} ({delivered/total*100:.1f}%)" if total > 0 else "  Entregues: 0")
    print(f"  Lidos: {read} ({read/total*100:.1f}%)" if total > 0 else "  Lidos: 0")
    print(f"  Responderam: {replied} ({replied/total*100:.1f}%)" if total > 0 else "  Responderam: 0")
    print(f"  Falhas no envio: {failed} ({failed/total*100:.1f}%)" if total > 0 else "  Falhas no envio: 0")
    print(f"  Pendentes: {pending} ({pending/total*100:.1f}%)" if total > 0 else "  Pendentes: 0")
    print(f"  Sem telefone cadastrado: {no_phone}")
    print()
    
    # Failed messages details
    failed_messages = [m for m in messages if m.get("status") == "failed"]
    if failed_messages:
        print("MENSAGENS COM FALHA NO ENVIO:")
        print(f"  {'RA':<12} {'Nome do Aluno':<25} {'Template':<12} {'Telefone'}")
        print(f"  {'-'*12} {'-'*25} {'-'*12} {'-'*20}")
        for msg in failed_messages:
            student = msg.get("students", {})
            ra = student.get("ra", "N/A")
            student_name = student.get("name", "N/A")[:24]
            template = msg.get("template_id", "N/A")[:11]
            guardian = msg.get("guardians", {})
            phone = guardian.get("phone_e164", "SEM TELEFONE") if guardian else "SEM TELEFONE"
            print(f"  {ra:<12} {student_name:<25} {template:<12} {phone}")
        print()
    
    # Students without phone (from source data that might have been filtered out)
    # We need to check the original source or look for students that should be in campaign but aren't
    print("=" * 80)
    print("RELATÓRIO COMPLETO POR ALUNO:")
    print(f"  {'RA':<12} {'Nome do Aluno':<25} {'Status':<12} {'Template':<12} {'Telefone':<18} {'Responsável'}")
    print(f"  {'-'*12} {'-'*25} {'-'*12} {'-'*12} {'-'*18} {'-'*25}")
    
    for msg in messages:
        student = msg.get("students", {})
        guardian = msg.get("guardians", {})
        
        ra = student.get("ra", "N/A")
        student_name = student.get("name", "N/A")[:24]
        status = msg.get("status", "unknown")
        template = msg.get("template_id", "N/A")[:11]
        phone = guardian.get("phone_e164", "SEM TELEFONE") if guardian else "SEM TELEFONE"
        guardian_name = guardian.get("name", "N/A")[:24] if guardian else "N/A"
        
        # Truncate long names for display
        if len(student.get("name", "")) > 24:
            student_name = student.get("name", "")[:21] + "..."
        if guardian and len(guardian.get("name", "")) > 24:
            guardian_name = guardian.get("name", "")[:21] + "..."
            
        print(f"  {ra:<12} {student_name:<25} {status:<12} {template:<12} {phone:<18} {guardian_name}")
    
    print()
    print("=" * 80)
    print(f"Resumo final: {total} destinatários processados")
    print(f"  ✓ {sent} enviados com sucesso")
    print(f"  ✗ {failed} com falha no envio") 
    print(f"  ⚠ {no_phone} sem telefone cadastrado")
    print(f"  📧 {replied} receberam resposta")
    
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
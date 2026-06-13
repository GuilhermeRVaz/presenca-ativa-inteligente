import sys
from pathlib import Path
import re
from collections import defaultdict

# Bootstrap project paths
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from app.core.config import settings
from app.infrastructure.supabase.repositories import SupabaseRepository

def main():
    print("Initializing Database Connection for Follow-up Campaign...")
    repo = SupabaseRepository()
    client = repo.client.schema("busca_ativa_v2")
    school_id = settings.default_school_id
    
    parent_campaign_name = "Campanha Bolsa Família — Justificativas Maio/2026"
    followup_campaign_name = "Campanha Bolsa Família — Follow-up Contatos Secundários Maio/2026"
    
    # 1. Resolve parent campaign
    parent_res = client.table("campaigns").select("id").eq("school_id", school_id).eq("name", parent_campaign_name).limit(1).execute().data
    if not parent_res:
        print("Error: Parent campaign not found!")
        return
    parent_campaign_id = parent_res[0]["id"]
    
    # 2. Get students in the parent campaign
    parent_msgs = client.table("messages").select("student_id, metadata").eq("campaign_id", parent_campaign_id).execute().data or []
    if not parent_msgs:
        print("No students found in the parent campaign.")
        return
        
    student_meta_map = {msg["student_id"]: msg["metadata"] for msg in parent_msgs}
    student_ids = list(student_meta_map.keys())
    
    # 3. Create or resolve follow-up campaign
    existing = client.table("campaigns").select("id").eq("school_id", school_id).eq("name", followup_campaign_name).limit(1).execute().data
    if existing:
        campaign_id = existing[0]["id"]
        print(f"Follow-up Campaign already exists: {followup_campaign_name} ({campaign_id})")
    else:
        campaign_data = {
            "school_id": school_id,
            "name": followup_campaign_name,
            "type": "absence",
            "campaign_type": "manual",
            "status": "draft",
            "parent_campaign_id": parent_campaign_id,
            "absence_days": "Abril/Maio 2026",
            "total_sent": 0,
            "total_failed": 0
        }
        res = client.table("campaigns").insert(campaign_data).execute()
        if not res.data:
            raise RuntimeError("Failed to create follow-up campaign in database.")
        campaign_id = res.data[0]["id"]
        print(f"Follow-up Campaign created successfully: {followup_campaign_name} ({campaign_id})")
        
    # 4. Find secondary guardians for these students
    guardians_res = (
        client.table("student_guardians")
        .select("student_id, guardian_id, is_primary, guardians(id, name, phone_e164, wa_jid)")
        .in_("student_id", student_ids)
        .eq("is_primary", False)
        .execute()
    )
    
    if not guardians_res.data:
        print("No secondary guardians found for these students.")
        return
        
    print(f"Found {len(guardians_res.data)} secondary guardians. Enqueuing messages...")
    enqueued_count = 0
    
    for row in guardians_res.data:
        student_id = row["student_id"]
        guardian = row["guardians"]
        if not guardian or not guardian.get("phone_e164"):
            continue
            
        guardian_id = guardian["id"]
        guardian_name = guardian["name"]
        phone = guardian["phone_e164"]
        
        # Build proper WhatsApp JID
        wa_jid = guardian.get("wa_jid")
        if not wa_jid:
            clean_digits = re.sub(r"[^0-9]", "", phone)
            wa_jid = f"{clean_digits}@s.whatsapp.net"
            
        parent_meta = student_meta_map[student_id]
        student_name = parent_meta.get("nome_excel", "Aluno(a)")
        turma = parent_meta.get("turma", "")
        absences_text = parent_meta.get("data_falta", "")
        
        # Format custom follow-up message text
        custom_message = (
            f"Olá {guardian_name}, entramos em contato anteriormente com o responsável primário do(a) "
            f"aluno(a) *{student_name}* (turma *{turma}*), mas como se trata de um assunto URGENTE do Bolsa Família "
            f"sobre baixa frequência, enviamos esta notificação também para o seu número como contato alternativo.\n\n"
            f"Notamos que o(a) aluno(a) esteve abaixo do limite de 75% de presença.\n"
            f"• Dias com faltas: {absences_text}\n\n"
            f"É necessário que a justificativa e as provas dessas justificativas (como atestados médicos ou "
            f"outras comprovações) sejam apresentadas com *URGÊNCIA* na secretaria da escola."
        )
        
        tracking_ref = f"BFF{campaign_id[:8]}-ST{student_id[:8]}-G{guardian_id[:8]}"
        
        metadata = {
            "turma": turma,
            "data_falta": absences_text,
            "ra": parent_meta.get("ra", ""),
            "nome_excel": student_name,
            "guardian_name": guardian_name,
            "guardian_phone": phone,
            "custom_message": custom_message
        }
        
        # Check idempotency
        msg_exist = client.table("messages").select("id").eq("campaign_id", campaign_id).eq("student_id", student_id).eq("guardian_id", guardian_id).limit(1).execute().data
        if msg_exist:
            print(f"  - Already enqueued for: {student_name} -> {guardian_name}")
            continue
            
        msg_row = {
            "school_id": school_id,
            "campaign_id": campaign_id,
            "student_id": student_id,
            "guardian_id": guardian_id,
            "tracking_ref": tracking_ref,
            "wa_jid": wa_jid,
            "template_id": "bolsa_familia_custom",
            "status": "pending",
            "metadata": metadata
        }
        
        msg_res = client.table("messages").insert(msg_row).execute()
        if not msg_res.data:
            raise RuntimeError(f"Failed to enqueue follow-up message for {student_name}")
        print(f"  [OK] Enqueued follow-up message for: {student_name} -> {guardian_name} ({row['is_primary'] and 'Primário' or 'Secundário'})")
        enqueued_count += 1
        
    print(f"\n============================================================")
    print(f"  Summary: {enqueued_count} follow-up messages prepared for campaign ID {campaign_id}")
    if enqueued_count > 0:
        print(f"  To execute and send this follow-up campaign to secondary contacts via WhatsApp, run:")
        print(f"  .venv\\Scripts\\python.exe scripts/campaign_orchestrator.py --campaign-id {campaign_id}")
    print(f"============================================================\n")

if __name__ == "__main__":
    main()

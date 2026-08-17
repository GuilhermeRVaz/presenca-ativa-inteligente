"""
scripts/enqueue_followup_fast.py

Enfileiramento rápido da campanha de Follow-up (177 alunos não confirmados nos segundos contatos).
"""

import sys
import json
import uuid
import random
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if sys.platform.startswith("win"):
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True)

from app.infrastructure.supabase.repositories import SupabaseRepository
from app.services.campaign_ai_service import CampaignAIService

SCHOOL_ID = "aac99735-32cb-4615-b2cb-0be315f18374"

BASE_FOLLOWUP_MSG = (
    "Olá {{nome_responsavel}}, aqui é da {{escola}}. Lembramos que a Reunião de Pais do aluno "
    "{{nome_aluno}} (Turma: {{turma}}) será nesta Quarta-feira, dia 5 de Agosto, às 18:30. "
    "Como ainda não registramos sua confirmação, reforçamos que sua presença é fundamental! "
    "Por favor, responda com '1' para CONFIRMAR PRESENÇA ou '2' caso vá JUSTIFICAR AUSÊNCIA."
)

print("=" * 80)
print("🚀 ENFILEIRANDO CAMPANHA DE FOLLOW-UP (SEGUNDO CONTATO)")
print("=" * 80)

json_path = ROOT / "scripts" / "unconfirmed_report.json"
with open(json_path, "r", encoding="utf-8") as f:
    unconfirmed_records = json.load(f)

target_list = [r for r in unconfirmed_records if r.get("intent") != "JUSTIFICADO_AUSENTE"]
print(f"📌 Alvos de Follow-Up (Sem Confirmação / Sem Justificativa): {len(target_list)}")

repo = SupabaseRepository(timeout=15.0, attempts=2)
client = repo.client.schema("busca_ativa_v2")
ai_service = CampaignAIService()

variants = ai_service._generate_fallback_variants(base_message=BASE_FOLLOWUP_MSG, num_variants=20)

campaign_id = str(uuid.uuid4())
campaign_name = "Follow-up Reunião de Pais - 5 de Agosto (Segundo Contato)"
now_iso = datetime.now(timezone.utc).isoformat()

campaign_payload = {
    "id": campaign_id,
    "school_id": SCHOOL_ID,
    "name": campaign_name,
    "type": "extraordinary",
    "campaign_type": "extraordinary",
    "category": "followup",
    "status": "active",
    "target_filter": {"classes": ["TODAS_TURMAS"], "strategy": "secondary_guardian_followup"},
    "class_filter": ["TODAS_TURMAS"],
    "base_message": BASE_FOLLOWUP_MSG,
    "absence_days": "0",
    "total_sent": 0,
    "total_replied": 0,
    "total_failed": 0,
    "created_at": now_iso,
    "updated_at": now_iso
}

client.table("campaigns").insert(campaign_payload).execute()
print(f"✅ Campanha Criada! ID: {campaign_id}")

# Buscar mapeamento de guardian_id por student_id e telefone
res_sg = client.table("student_guardians").select("student_id, guardian_id, guardians(phone_e164, wa_jid)").execute()
guardian_lookup = {}
for sg in (res_sg.data or []):
    st_id = sg.get("student_id")
    g_id = sg.get("guardian_id")
    g = sg.get("guardians") or {}
    p = g.get("phone_e164") or g.get("wa_jid") or ""
    digits = "".join(ch for ch in p if ch.isdigit())
    if st_id and g_id:
        guardian_lookup[(st_id, digits)] = g_id
        guardian_lookup[st_id] = g_id  # fallback pelo student_id

messages_to_insert = []
sec_count = 0
pri_count = 0

for idx, r in enumerate(target_list):
    st_id = r.get("student_id")
    tel1 = (r.get("tel1") or "").strip()
    tel2 = (r.get("tel2") or "").strip()
    st_name = r.get("student_name") or ""
    c_name = r.get("class_name") or ""
    g_name = r.get("guardian_name") or "Responsável"

    chosen_phone = tel2 if (tel2 and len(tel2) >= 10 and tel2 != tel1) else tel1
    if chosen_phone == tel2 and tel2 != tel1:
        sec_count += 1
    else:
        pri_count += 1

    digits = "".join(ch for ch in chosen_phone if ch.isdigit())
    if not digits.startswith("55") and len(digits) in [10, 11]:
        digits = "55" + digits

    # Achar guardian_id
    g_id = guardian_lookup.get((st_id, digits)) or guardian_lookup.get(st_id)
    if not g_id:
        # Se não achou guardian_id, buscar qualquer guardian da escola
        res_dummy = client.table("guardians").select("id").eq("school_id", SCHOOL_ID).limit(1).execute()
        g_id = res_dummy.data[0]["id"] if res_dummy.data else str(uuid.uuid4())

    wa_jid = f"{digits}@s.whatsapp.net"
    variant = random.choice(variants)

    body_text = (
        variant.replace("{{nome_responsavel}}", g_name)
        .replace("{{nome_aluno}}", st_name)
        .replace("{{turma}}", c_name)
        .replace("{{escola}}", "EE PEI Profª Décia")
    )

    messages_to_insert.append({
        "id": str(uuid.uuid4()),
        "school_id": SCHOOL_ID,
        "campaign_id": campaign_id,
        "student_id": st_id,
        "guardian_id": g_id,
        "tracking_ref": f"FLW-{uuid.uuid4().hex[:8].upper()}",
        "template_id": f"variant_{(idx % len(variants)) + 1}",
        "wa_jid": wa_jid,
        "body_preview": body_text,
        "status": "pending",
        "created_at": now_iso
    })

batch_size = 25
inserted = 0
for i in range(0, len(messages_to_insert), batch_size):
    batch = messages_to_insert[i:i + batch_size]
    client.table("messages").insert(batch).execute()
    inserted += len(batch)
    print(f"   • Enfileiradas {inserted}/{len(messages_to_insert)} mensagens...")

print("\n" + "=" * 80)
print("🎉 CAMPANHA DE FOLLOW-UP ENFILEIRADA COM ÉXITO NO SUPABASE!")
print(f"   • Campaign ID:                   {campaign_id}")
print(f"   • Total de Mensagens na Fila:   {inserted}")
print(f"   • Enviadas para Telefone 2:     {sec_count}")
print(f"   • Enviadas para Telefone 1:     {pri_count}")
print("=" * 80 + "\n")

with open(ROOT / "scripts" / "latest_followup_campaign_id.txt", "w", encoding="utf-8") as f:
    f.write(campaign_id)

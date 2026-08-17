"""
scripts/enqueue_followup_campaign.py

Cria e enfileira a campanha de Follow-up da Reunião de Pais de 5 de Agosto para os alunos
que NÃO confirmaram (1) e NÃO justificaram ausência (2), priorizando o SEGUNDO CONTATO (Telefone 2) de cada aluno.
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
print("🚀 ENFILEIRANDO CAMPANHA DE FOLLOW-UP (SEGUNDO CONTATO DE RESPONSÁVEL)")
print("=" * 80)

# 1. Carregar alunos não confirmados do arquivo unconfirmed_report.json
json_path = ROOT / "scripts" / "unconfirmed_report.json"
if not json_path.exists():
    print("❌ Arquivo unconfirmed_report.json não encontrado. Execute generate_complete_meeting_report.py primeiro.")
    sys.exit(1)

with open(json_path, "r", encoding="utf-8") as f:
    unconfirmed_records = json.load(f)

# Filtrar estritamente quem NÃO justificou ausência (excluir intent JUSTIFICADO_AUSENTE)
target_list = [r for r in unconfirmed_records if r.get("intent") != "JUSTIFICADO_AUSENTE"]

print(f"📌 Total de Alunos Alvo para Follow-up (Sem Confirmação e Sem Justificativa): {len(target_list)}")

# 2. Inicializar repositório e serviços
repo = SupabaseRepository(timeout=30.0, attempts=3)
client = repo.client.schema("busca_ativa_v2")
ai_service = CampaignAIService()

# 3. Gerar 20 variações de IA para anti-bloqueio Meta
print("\n🤖 Gerando 20 variações de IA para o Follow-up...")
try:
    variants = ai_service._generate_fallback_variants(base_message=BASE_FOLLOWUP_MSG, num_variants=20)
    print(f"✅ Geradas {len(variants)} variações com sucesso!")
except Exception as e:
    variants = [BASE_FOLLOWUP_MSG]

# 4. Criar a nova Campanha de Follow-up no Supabase
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
print(f"\n✅ Campanha Criada no Supabase! ID: {campaign_id}")

# 5. Criar registros na tabela 'messages' para os telefones escolhidos
messages_to_insert = []
sec_count = 0
pri_count = 0

for r in target_list:
    st_id = r.get("student_id")
    tel1 = (r.get("tel1") or "").strip()
    tel2 = (r.get("tel2") or "").strip()
    st_name = r.get("student_name") or ""
    c_name = r.get("class_name") or ""
    g_name = r.get("guardian_name") or "Responsável"

    # Regra de Escolha do Telefone: Priorizar Telefone 2 se for válido; senão usar Telefone 1
    chosen_phone = tel2 if (tel2 and len(tel2) >= 10 and tel2 != tel1) else tel1
    
    if chosen_phone == tel2 and tel2 != tel1:
        sec_count += 1
    else:
        pri_count += 1

    digits = "".join(ch for ch in chosen_phone if ch.isdigit())
    if not digits.startswith("55") and len(digits) in [10, 11]:
        digits = "55" + digits

    wa_jid = f"{digits}@s.whatsapp.net"
    variant = random.choice(variants)

    # Personalizar texto
    body_text = (
        variant.replace("{{nome_responsavel}}", g_name)
        .replace("{{nome_aluno}}", st_name)
        .replace("{{turma}}", c_name)
        .replace("{{escola}}", "EE PEI Profª Décia")
    )

    msg_id = str(uuid.uuid4())
    messages_to_insert.append({
        "id": msg_id,
        "school_id": SCHOOL_ID,
        "campaign_id": campaign_id,
        "student_id": st_id,
        "wa_jid": wa_jid,
        "body": body_text,
        "status": "pending",
        "created_at": now_iso
    })

# Inserir mensagens em lote de 50 no Supabase
batch_size = 50
inserted_total = 0
for i in range(0, len(messages_to_insert), batch_size):
    batch = messages_to_insert[i:i + batch_size]
    client.table("messages").insert(batch).execute()
    inserted_total += len(batch)
    print(f"   • Lote de {len(batch)} mensagens enfileirado... ({inserted_total}/{len(messages_to_insert)})")

print("\n" + "=" * 80)
print(f"🎉 ENFILEIRAMENTO CONCLUÍDO COM ÉXITO!")
print(f"   • ID da Campanha:               {campaign_id}")
print(f"   • Total de Mensagens na Fila:   {inserted_total}")
print(f"   • Enviadas para Telefone 2 (Segundos Contatos): {sec_count}")
print(f"   • Enviadas para Telefone 1 (Principais):        {pri_count}")
print("=" * 80 + "\n")

# Salvar o ID da campanha no arquivo local para facilitar
with open(ROOT / "scripts" / "latest_followup_campaign_id.txt", "w", encoding="utf-8") as f:
    f.write(campaign_id)

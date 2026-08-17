"""
scripts/resume_pending_sends.py

Finaliza os 15 envios pendentes da campanha do 2º Lote no Supabase via ExtraordinaryCampaignService.
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if sys.platform.startswith("win"):
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True)

from app.services.extraordinary_campaign_service import ExtraordinaryCampaignService
from app.infrastructure.supabase.repositories import SupabaseRepository

CAMPAIGN_ID = "5318046f-80d8-40e5-999e-ac0d83b8917f"

print("=" * 80)
print("🚀 FINALIZANDO MENSAGENS PENDENTES DA CAMPANHA 2º LOTE")
print("=" * 80)

service = ExtraordinaryCampaignService()
repo = SupabaseRepository(timeout=15.0, attempts=2)

# Consultar pendentes antes
res_p = repo.client.schema("busca_ativa_v2").table("messages").select("id, status").eq("campaign_id", CAMPAIGN_ID).eq("status", "pending").execute()
pending_msgs = res_p.data or []

print(f"📌 Total de Mensagens Pendentes Identificadas: {len(pending_msgs)}")

if not pending_msgs:
    print("✅ Não há mensagens pendentes! Todos os envios foram concluídos.")
    sys.exit(0)

# Processar os envios pendentes
print("⏳ Disparando mensagens pendentes...")
try:
    processed = service.process_pending_campaign_messages(campaign_id=CAMPAIGN_ID, max_batch=50)
    print(f"✅ SUCESSO! {processed} mensagens processadas e enviadas!")
except Exception as e:
    print(f"⚠️ Erro no processamento: {e}")

# Consultar métricas finais
res_final = repo.client.schema("busca_ativa_v2").table("messages").select("status").eq("campaign_id", CAMPAIGN_ID).execute()
all_final = res_final.data or []

sent = sum(1 for m in all_final if m.get("status") in ["sent", "delivered", "read", "replied"])
pending = sum(1 for m in all_final if m.get("status") == "pending")
failed = sum(1 for m in all_final if m.get("status") == "failed")

print("\n" + "=" * 80)
print(f"📊 RESULTADO FINAL DA CAMPANHA:")
print(f"   • Total de Contatos: {len(all_final)}")
print(f"   • Enviados com Êxito: {sent}")
print(f"   • Falhas: {failed}")
print(f"   • Pendentes: {pending}")
print("=" * 80 + "\n")

"""
scripts/check_pending_messages.py
Verifica o progresso em tempo real da campanha mais recente no Supabase.
"""
import sys
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if sys.platform.startswith("win"):
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True)

from app.infrastructure.supabase.repositories import SupabaseRepository

SCHOOL_ID = "aac99735-32cb-4615-b2cb-0be315f18374"

repo = SupabaseRepository(timeout=15.0, attempts=2)
client = repo.client

print("=" * 80)
print("📊 PROGRESSO EM TEMPO REAL DA CAMPANHA DE DISPARO")
print("=" * 80)

# Buscar as 3 últimas campanhas criadas
res_c = client.schema("busca_ativa_v2").table("campaigns").select("*").eq("school_id", SCHOOL_ID).order("created_at", desc=True).limit(3).execute()
camps = res_c.data or []

if not camps:
    print("⚠️ Nenhuma campanha recente encontrada.")
    sys.exit(0)

latest_c = camps[0]
c_id = latest_c["id"]
c_name = latest_c.get("name")
c_created = latest_c.get("created_at")
tf = latest_c.get("target_filter") or {}
classes = tf.get("classes", [])

print(f"\n📌 Campanha Ativa Atual: '{c_name}' (ID: {c_id})")
print(f"   • Criada em:      {c_created}")
print(f"   • Turmas no filtro: {classes}")

# Buscar mensagens da campanha atual
res_m = client.schema("busca_ativa_v2").table("messages").select("id, status, student_id, wa_jid").eq("campaign_id", c_id).execute()
msgs = res_m.data or []

total = len(msgs)
status_counts = defaultdict(int)
for m in msgs:
    status_counts[m.get("status") or "pending"] += 1

sent_success = status_counts["sent"] + status_counts["delivered"] + status_counts["read"] + status_counts["replied"]
pending = status_counts["pending"]
failed = status_counts["failed"]

print(f"\n📊 MÉTRICAS GERAIS DA CAMPANHA ATUAL:")
print(f"   • Total de Contatos Enfileirados: {total}")
print(f"   • ✅ Já Enviados com Sucesso:      {sent_success}")
print(f"   • ⏳ FALTAM ENVIAR (PENDENTES):    {pending}")
print(f"   • ❌ Falhas de Envio:              {failed}")

if total > 0:
    pct_concluido = ((sent_success + failed) / total) * 100
    print(f"   • 📈 Progresso do Envio:          {pct_concluido:.1f}% concluído")

# Mapear turmas
st_ids = list(set(m["student_id"] for m in msgs if m.get("student_id")))
res_st = client.schema("busca_ativa_v2").table("students").select("id, name, class_name").in_("id", st_ids).execute() if st_ids else None
st_dict = {s["id"]: s for s in (res_st.data if res_st else [])}

turma_map = defaultdict(lambda: {"total": 0, "sent": 0, "pending": 0, "failed": 0})
for m in msgs:
    st = st_dict.get(m.get("student_id"), {})
    t_name = st.get("class_name") or "Outras"
    st_val = m.get("status") or "pending"
    turma_map[t_name]["total"] += 1
    if st_val in ["sent", "delivered", "read", "replied"]:
        turma_map[t_name]["sent"] += 1
    elif st_val in ["failed", "erro"]:
        turma_map[t_name]["failed"] += 1
    else:
        turma_map[t_name]["pending"] += 1

print("\n🏫 DETALHAMENTO POR TURMA NESA CAMPANHA:")
for t_name, t_data in sorted(turma_map.items()):
    print(f"   🔹 {t_name}: {t_data['sent']}/{t_data['total']} enviados | ⏳ Pendentes: {t_data['pending']} | ❌ Falhas: {t_data['failed']}")

print("\n" + "=" * 80)

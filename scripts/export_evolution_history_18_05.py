import os
import sys
import re
import requests
from datetime import datetime
from dotenv import load_dotenv
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding='utf-8')
except AttributeError:
    pass

ROOT_DIR = Path.cwd()
sys.path.append(str(ROOT_DIR))
load_dotenv(ROOT_DIR / ".env")

EVOLUTION_API_URL = os.getenv("EVOLUTION_API_URL")
EVOLUTION_API_KEY = os.getenv("EVOLUTION_API_KEY")
INSTANCE_NAME = os.getenv("EVOLUTION_API_INSTANCE")

PROTOCOL_RE = re.compile(r'P-([A-F0-9]{6})', re.IGNORECASE)
TEMPLATE_MARKERS = ["para justificar, responda", "codigo do aluno:", "exemplo:"]
CONFIRM_KEYWORDS = ["obrigado", "obrigada", "agradeço", "agradecemos", "motivo:", "entendi", "ciente"]


def is_confirmation(text: str) -> bool:
    tl = text.lower()
    return any(k in tl for k in CONFIRM_KEYWORDS) and not any(k in tl for k in TEMPLATE_MARKERS)


def extract_text(msg: dict) -> str:
    m = msg.get("message", {})
    if "conversation" in m:
        return m["conversation"]
    if "extendedTextMessage" in m:
        return m.get("extendedTextMessage", {}).get("text", "")
    if "audioMessage" in m:
        return "[AUDIO]"
    if "imageMessage" in m:
        return "[IMAGEM]"
    return msg.get("conversation", "")


def fetch_conversation(jid: str, limit: int = 50):
    url = f"{EVOLUTION_API_URL}/chat/findMessages/{INSTANCE_NAME}"
    headers = {"apikey": EVOLUTION_API_KEY, "Content-Type": "application/json"}
    payload = {"where": {"key": {"remoteJid": jid}}, "limit": limit}
    try:
        r = requests.post(url, json=payload, headers=headers, timeout=15)
        if r.status_code == 200:
            return r.json().get("messages", {}).get("records", [])
        return []
    except Exception:
        return []


def scan_jid(jid: str, target_date: datetime.date):
    """Retorna (escola_msgs, pai_msgs) para o JID no dia alvo."""
    records = fetch_conversation(jid, limit=100)
    escola = []
    pai = []
    for msg in records:
        ts = msg.get("messageTimestamp", 0)
        if not ts:
            continue
        dt = datetime.fromtimestamp(ts)
        if dt.date() != target_date:
            continue
        text = extract_text(msg).strip()
        if not text:
            continue
        entry = {"dt": dt, "time": dt.strftime("%H:%M"), "text": text}
        if msg.get("key", {}).get("fromMe"):
            escola.append(entry)
        else:
            pai.append(entry)
    return escola, pai


def run():
    TARGET_DATE = datetime(2026, 5, 18).date()

    print("=" * 60)
    print("  RELATÓRIO CAMPANHA 18/05/2026 — v4")
    print("  Estratégia: scan JID + LID, detecção por confirmação")
    print("=" * 60)

    # Dados da campanha
    from app.infrastructure.supabase.repositories import SupabaseRepository
    repo = SupabaseRepository()
    client = repo.client.schema("busca_ativa_v2")
    campaign_id = "e1ea30f0-e8b2-44aa-af4c-33a792c2fc8c"

    students = {s["id"]: s["name"] for s in client.table("students").select("id,name").execute().data}
    camp_msgs = (client.table("messages")
                 .select("wa_jid,student_id,guardian_id,status")
                 .eq("campaign_id", campaign_id)
                 .execute().data)

    # jid -> {student_name, guardian_id}
    jid_info = {}
    for m in camp_msgs:
        if m.get("wa_jid"):
            jid_info[m["wa_jid"]] = {
                "student_name": students.get(m["student_id"], "?"),
                "guardian_id": m.get("guardian_id"),
                "status": m.get("status"),
            }

    # Mapa de identidade: guardian_id -> [lid_jid, wa_jid]
    id_map = client.table("phone_identity_map").select("lid_jid,wa_jid,guardian_id").execute().data
    guardian_to_lids = {}
    for entry in id_map:
        g = entry.get("guardian_id")
        if not g:
            continue
        guardian_to_lids.setdefault(g, set())
        if entry.get("lid_jid"):
            guardian_to_lids[g].add(entry["lid_jid"])
        if entry.get("wa_jid"):
            guardian_to_lids[g].add(entry["wa_jid"])

    print(f"\n  {len(jid_info)} JIDs de campanha | {len(guardian_to_lids)} guardiões com LID mapeado")

    # Para cada JID da campanha, varre o JID + todos LIDs do mesmo guardião
    results = {}  # student_name -> {justified, motivo, msgs_escola, msgs_pai}
    total = len(jid_info)

    print(f"\n[Varrendo {total} contatos + seus LIDs...]\n")

    for idx, (jid, info) in enumerate(jid_info.items(), 1):
        student_name = info["student_name"]
        guardian_id = info.get("guardian_id")

        # Todos os JIDs a varrer para este guardião
        jids_to_scan = {jid}
        if guardian_id and guardian_id in guardian_to_lids:
            jids_to_scan.update(guardian_to_lids[guardian_id])

        all_escola = []
        all_pai = []
        for j in jids_to_scan:
            e, p = scan_jid(j, TARGET_DATE)
            all_escola.extend(e)
            all_pai.extend(p)

        all_escola.sort(key=lambda x: x["dt"])
        all_pai.sort(key=lambda x: x["dt"])

        # Detecta justificativa:
        # 1) pai enviou algo
        # 2) escola enviou confirmação (2+ outbound com agradecimento)
        has_pai = len(all_pai) > 0
        escola_confirmou = False
        confirm_text = ""
        if len(all_escola) > 1:
            for em in all_escola[1:]:
                if is_confirmation(em["text"]):
                    escola_confirmou = True
                    confirm_text = em["text"][:150]
                    break

        justified = has_pai or escola_confirmou

        # Extrai motivo do pai ou da confirmação da escola
        motivo = ""
        if all_pai:
            motivo = all_pai[0]["text"][:120]
        elif confirm_text:
            motivo = confirm_text

        results[student_name] = {
            "justified": justified,
            "has_pai": has_pai,
            "escola_confirmou": escola_confirmou,
            "motivo": motivo,
            "pai_msgs": all_pai,
            "escola_msgs": all_escola,
            "jids_scanned": jids_to_scan,
        }

        status_icon = "✅" if justified else "❌"
        if idx % 10 == 0 or justified:
            print(f"  [{idx}/{total}] {status_icon} {student_name}")

    # Separa justificados / não justificados
    justificados = [(k, v) for k, v in results.items() if v["justified"]]
    nao_justificados = [(k, v) for k, v in results.items() if not v["justified"]]
    justificados.sort(key=lambda x: x[0])
    nao_justificados.sort(key=lambda x: x[0])

    # Relatório
    os.makedirs(str(ROOT_DIR / "relatorios"), exist_ok=True)
    path = ROOT_DIR / "relatorios" / "RELATORIO_FINAL_PRECISO_18_05.txt"

    with open(path, "w", encoding="utf-8") as f:
        f.write("=" * 65 + "\n")
        f.write("  RELATÓRIO — BUSCA ATIVA 18/05/2026\n")
        f.write("  Estratégia: scan JID + LID + detecção por confirmação\n")
        f.write("=" * 65 + "\n\n")
        f.write(f"  Alunos na campanha  : {len(results)}\n")
        f.write(f"  ✅ JUSTIFICADOS     : {len(justificados)}\n")
        f.write(f"  ❌ SEM RESPOSTA     : {len(nao_justificados)}\n")
        f.write("=" * 65 + "\n\n")

        f.write(f"✅ ALUNOS COM JUSTIFICATIVA ({len(justificados)})\n")
        f.write("-" * 65 + "\n")
        for name, v in justificados:
            sinais = []
            if v["has_pai"]: sinais.append("pai respondeu")
            if v["escola_confirmou"]: sinais.append("escola confirmou")
            f.write(f"\n[V] {name}\n")
            f.write(f"    Sinal: {' + '.join(sinais)}\n")
            if v["motivo"]:
                f.write(f"    Motivo: {v['motivo']}\n")
            for pm in v["pai_msgs"]:
                f.write(f"    {pm['time']} PAI: {pm['text']}\n")
            for em in v["escola_msgs"]:
                short = em['text'][:100]
                f.write(f"    {em['time']} ESCOLA: {short}\n")
            f.write("-" * 55 + "\n")

        f.write(f"\n❌ SEM RESPOSTA ({len(nao_justificados)})\n")
        f.write("-" * 65 + "\n")
        for name, v in nao_justificados:
            f.write(f"  {name}\n")

    print(f"\n{'='*55}")
    print(f"✅ JUSTIFICADOS : {len(justificados)}")
    print(f"❌ SEM RESPOSTA : {len(nao_justificados)}")
    print(f"\nJUSTIFICATIVAS ENCONTRADAS:")
    for name, v in justificados:
        print(f"  • {name}")
        if v["motivo"]:
            print(f"    → {v['motivo'][:80]}")
    print(f"\nRelatório: {path}")


if __name__ == "__main__":
    run()

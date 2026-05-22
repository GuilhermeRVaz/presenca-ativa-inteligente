"""
backfill_lids_from_conversations.py  v2

Estratégia correta:
1. Lista TODOS os chats @lid da instância via /chat/findChats
2. Para cada chat @lid, busca as mensagens
3. Procura mensagens outbound (fromMe=True) que contenham o protocolo P-XXXXXX
4. Cruza o protocolo com os dados da campanha para identificar o guardian_id + wa_jid
5. Salva no phone_identity_map: lid_jid -> guardian_id + wa_jid

Resultado: scan futuro de relatório vai encontrar respostas via LID.

Uso:
    python scripts/backfill_lids_from_conversations.py
    python scripts/backfill_lids_from_conversations.py --campaign-id <uuid>
    python scripts/backfill_lids_from_conversations.py --dry-run
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
import time
import requests
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

EVOLUTION_API_URL = os.getenv("EVOLUTION_API_URL", "").rstrip("/")
EVOLUTION_API_KEY = os.getenv("EVOLUTION_API_KEY", "")
INSTANCE_NAME    = os.getenv("EVOLUTION_API_INSTANCE", "")
HEADERS = {"apikey": EVOLUTION_API_KEY, "Content-Type": "application/json"}

PROTOCOL_RE = re.compile(r'P-([A-F0-9]{6})', re.IGNORECASE)


# ---------------------------------------------------------------------------
# Evolution helpers
# ---------------------------------------------------------------------------

def list_all_lid_chats() -> list[str]:
    """Retorna todos os JIDs @lid da instância."""
    url = f"{EVOLUTION_API_URL}/chat/findChats/{INSTANCE_NAME}"
    try:
        r = requests.post(url, json={}, headers=HEADERS, timeout=20)
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, list):
                return [
                    str(c.get("remoteJid") or c.get("id") or "")
                    for c in data
                    if str(c.get("remoteJid", "") or c.get("id", "")).endswith("@lid")
                ]
    except Exception as e:
        print(f"  [ERR] findChats: {e}")
    return []


def fetch_conversation(jid: str, limit: int = 30) -> list[dict]:
    """Retorna mensagens de uma conversa."""
    url = f"{EVOLUTION_API_URL}/chat/findMessages/{INSTANCE_NAME}"
    payload = {"where": {"key": {"remoteJid": jid}}, "limit": limit}
    try:
        r = requests.post(url, json=payload, headers=HEADERS, timeout=15)
        if r.status_code == 200:
            return r.json().get("messages", {}).get("records", [])
    except Exception:
        pass
    return []


def extract_protocols_from_records(records: list[dict]) -> list[str]:
    """Extrai protocolos P-XXXXXX das mensagens outbound (fromMe=True)."""
    protos = []
    for rec in records:
        if not rec.get("key", {}).get("fromMe"):
            continue
        m = rec.get("message", {})
        text = (
            m.get("conversation", "")
            or m.get("extendedTextMessage", {}).get("text", "")
        )
        found = PROTOCOL_RE.findall(text)
        protos.extend(f"P-{p.upper()}" for p in found)
    return list(dict.fromkeys(protos))  # deduplica mantendo ordem


def has_inbound_response(records: list[dict]) -> bool:
    """Retorna True se há pelo menos uma mensagem inbound (pai respondeu)."""
    return any(not rec.get("key", {}).get("fromMe") for rec in records)


# ---------------------------------------------------------------------------
# Supabase helpers
# ---------------------------------------------------------------------------

def _build_supabase():
    from app.infrastructure.supabase.repositories import SupabaseRepository
    return SupabaseRepository()


def _short_protocol(tracking_ref: str) -> str:
    return hashlib.sha256(tracking_ref.encode()).hexdigest()[:6].upper()


def get_campaign_protocol_map(repo, campaign_id: str) -> dict:
    """Retorna {protocol -> {wa_jid, guardian_id, school_id, student_name}} da campanha."""
    msgs = (repo.client.schema("busca_ativa_v2")
            .table("messages")
            .select("wa_jid, tracking_ref, guardian_id, school_id, student_id, status")
            .eq("campaign_id", campaign_id)
            .execute().data or [])

    students = {s["id"]: s["name"] for s in
                repo.client.schema("busca_ativa_v2").table("students").select("id,name").execute().data or []}

    proto_map = {}
    for m in msgs:
        if not m.get("tracking_ref"):
            continue
        proto = f"P-{_short_protocol(m['tracking_ref'])}"
        proto_map[proto] = {
            "wa_jid": m.get("wa_jid"),
            "guardian_id": m.get("guardian_id"),
            "school_id": m.get("school_id"),
            "student_name": students.get(m.get("student_id"), "?"),
            "status": m.get("status"),
        }
    return proto_map


def lid_already_mapped(repo, lid_jid: str) -> bool:
    res = (repo.client.schema("busca_ativa_v2")
           .table("phone_identity_map")
           .select("id")
           .eq("lid_jid", lid_jid)
           .limit(1)
           .execute())
    return bool(res.data)


def upsert_lid(repo, *, school_id: str, wa_jid: str, lid_jid: str,
               guardian_id: str, dry_run: bool) -> bool:
    if dry_run:
        return True
    try:
        repo.upsert_phone_identity(
            school_id=school_id,
            lid_jid=lid_jid,
            wa_jid=wa_jid,
            phone_e164=None,
            guardian_id=guardian_id,
            confidence="HIGH",
            source="backfill",
        )
        return True
    except Exception as e:
        print(f"    [DB ERR] {e}")
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(campaign_id: str | None, dry_run: bool) -> None:
    print("=" * 65)
    print("  BACKFILL LIDs v2 — Estratégia: findChats + protocolo")
    if dry_run:
        print("  MODO DRY RUN (sem gravação no banco)")
    print("=" * 65)

    repo = _build_supabase()

    if not campaign_id:
        res = (repo.client.schema("busca_ativa_v2")
               .table("campaigns")
               .select("id,name")
               .order("created_at", desc=True)
               .limit(1)
               .execute())
        if not res.data:
            print("Nenhuma campanha encontrada.")
            return
        campaign_id = res.data[0]["id"]
        print(f"Campanha: {res.data[0]['name']} ({campaign_id})")
    else:
        print(f"Campanha ID: {campaign_id}")

    print("\n[1] Carregando mapa de protocolos da campanha...")
    proto_map = get_campaign_protocol_map(repo, campaign_id)
    print(f"    {len(proto_map)} protocolos mapeados")

    print("\n[2] Listando todos os chats @lid da instância Evolution...")
    lid_chats = list_all_lid_chats()
    print(f"    {len(lid_chats)} chats @lid encontrados")

    print("\n[3] Varrendo chats @lid em busca de protocolos da campanha...\n")

    stats = {"scanned": 0, "match": 0, "new_lid": 0, "skip_mapped": 0,
             "no_proto": 0, "no_response": 0}

    for i, lid_jid in enumerate(lid_chats, 1):
        records = fetch_conversation(lid_jid, limit=30)
        stats["scanned"] += 1

        if not records:
            continue

        protos = extract_protocols_from_records(records)
        if not protos:
            stats["no_proto"] += 1
            continue

        # Verifica se algum protocolo pertence à campanha
        matched_proto = None
        for p in protos:
            if p in proto_map:
                matched_proto = p
                break

        if not matched_proto:
            continue

        info = proto_map[matched_proto]
        student_name = info["student_name"]
        wa_jid = info["wa_jid"]
        guardian_id = info["guardian_id"]
        school_id = info["school_id"]

        # Verifica se o pai respondeu nessa conversa @lid
        responded = has_inbound_response(records)
        resp_tag = "[respondeu]" if responded else "[so outbound]"

        stats["match"] += 1

        # Verifica se já mapeado
        if lid_already_mapped(repo, lid_jid):
            print(f"  [{i:03d}] {lid_jid}  → {matched_proto} {student_name} {resp_tag}  [já mapeado]")
            stats["skip_mapped"] += 1
            continue

        ok = upsert_lid(
            repo,
            school_id=school_id or "",
            wa_jid=wa_jid or "",
            lid_jid=lid_jid,
            guardian_id=guardian_id or "",
            dry_run=dry_run,
        )
        tag = "DRY-RUN" if dry_run else ("SALVO" if ok else "ERRO")
        print(f"  [{i:03d}] {lid_jid}  → {matched_proto} {student_name} {resp_tag}  [{tag}]")
        if ok:
            stats["new_lid"] += 1

        time.sleep(0.2)

    print("\n" + "=" * 65)
    print("RESULTADO DO BACKFILL v2")
    print(f"  Chats @lid varridos       : {stats['scanned']}")
    print(f"  Matches com a campanha    : {stats['match']}")
    print(f"  LIDs novos salvos         : {stats['new_lid']}")
    print(f"  LIDs já mapeados          : {stats['skip_mapped']}")
    print(f"  Chats sem protocolo nosso : {stats['no_proto']}")
    print("=" * 65)

    if stats["new_lid"] > 0:
        print(f"\n✅ {stats['new_lid']} LID(s) novo(s) mapeados!")
        print("   Agora rode novamente o relatório (export_evolution_history_18_05.py)")
        print("   para obter o número correto de justificativas via scan automático.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill LIDs v2 — via findChats + protocolo")
    parser.add_argument("--campaign-id", type=str, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run(campaign_id=args.campaign_id, dry_run=args.dry_run)

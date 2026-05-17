from __future__ import annotations

import argparse
import sys
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

load_dotenv(ROOT_DIR / ".env")

from app.core.config import settings
from app.infrastructure.supabase.repositories import SupabaseRepository

SCHEMA = "busca_ativa_v2"

@dataclass
class ChatEvent:
    timestamp: datetime
    sender: str
    body: str
    type: str # 'OUTBOUND_INITIAL', 'OUTBOUND_FOLLOWUP', 'INBOUND'
    has_protocol: bool = False
    has_reason: bool = False

def extract_protocol(text: str) -> str | None:
    match = re.search(r"P-[A-Z0-9]{6}", text or "")
    return match.group(0) if match else None

def analyze_inbound(text: str, reason: str | None) -> tuple[bool, bool]:
    has_proto = extract_protocol(text) is not None
    has_reason = reason is not None and reason != "OUTROS"
    return has_proto, has_reason

def main():
    parser = argparse.ArgumentParser(description="Auditor de Conversas PAI")
    parser.add_argument("--campaign-id", help="ID da campanha")
    parser.add_argument("--school-id", default=settings.default_school_id)
    args = parser.parse_args()

    repo = SupabaseRepository()
    client = repo.client.schema(SCHEMA)

    campaign_id = args.campaign_id
    if not campaign_id:
        today = date.today().strftime("%d/%m/%Y")
        c_rows = client.table("campaigns").select("id, name, absence_days").eq("school_id", args.school_id).eq("absence_days", today).order("created_at", desc=True).limit(1).execute().data
        if not c_rows: return
        campaign_id = c_rows[0]["id"]
        campaign_name = c_rows[0]["name"]
    else:
        c_rows = client.table("campaigns").select("id, name, absence_days").eq("id", campaign_id).execute().data
        campaign_name = c_rows[0]["name"] if c_rows else "Campanha Desconhecida"

    # 1. Pegar Mapa de Identidade (LIDs)
    identity_map = {}
    id_rows = client.table("phone_identity_map").select("wa_jid, lid_jid").execute().data or []
    for row in id_rows:
        identity_map[row["lid_jid"]] = row["wa_jid"]

    # 2. Pegar TODAS as mensagens e respostas da campanha + respostas órfãs de hoje
    all_msgs = client.table("messages").select("*, students(*), guardians(*)").eq("campaign_id", campaign_id).execute().data or []
    
    # Busca ampla de respostas: da campanha OU de hoje (para pegar follow-ups manuais/outros)
    all_resps = client.table("responses").select("*").or_(f"campaign_id.eq.{campaign_id},received_at.gte.{date.today().isoformat()}").execute().data or []

    # 3. Organizar por Aluno
    # EXCLUIR 'failed', 'error', 'pending'
    sent_msgs = [m for m in all_msgs if m.get("status") in ["sent", "delivered", "read", "replied"]]
    
    student_puzzle = defaultdict(lambda: {"outbounds": [], "inbounds": [], "student": {}, "guardian": {}})
    
    for m in sent_msgs:
        sid = m.get("student_id")
        student_puzzle[sid]["outbounds"].append(m)
        student_puzzle[sid]["student"] = m.get("students") or {}
        student_puzzle[sid]["guardian"] = m.get("guardians") or {}

    # Distribuir respostas para os alunos (usando ID, JID ou Protocolo)
    for r in all_resps:
        sid = r.get("student_id")
        body = r.get("body") or ""
        proto = extract_protocol(body)
        
        target_sid = sid
        if not target_sid and proto:
            # Se tem protocolo, busca qual aluno tem esse protocolo no envio inicial
            for m in sent_msgs:
                if proto in (m.get("body_preview") or ""):
                    target_sid = m.get("student_id")
                    break
        
        if not target_sid:
            # Tenta via JID/Identity Map
            sender = r.get("sender_jid")
            resolved_sender = identity_map.get(sender, sender)
            for sid_key, data in student_puzzle.items():
                if data["guardian"].get("phone_e164") in resolved_sender or (data["outbounds"] and data["outbounds"][0].get("wa_jid") == resolved_sender):
                    target_sid = sid_key
                    break
        
        if target_sid and target_sid in student_puzzle:
            student_puzzle[target_sid]["inbounds"].append(r)

    # 4. Construir Diário Auditado
    final_blocks = []
    for sid, data in student_puzzle.items():
        events: list[ChatEvent] = []
        
        # Ordenar Outbounds por data
        sorted_out = sorted(data["outbounds"], key=lambda x: x.get("sent_at") or x.get("created_at"))
        for i, m in enumerate(sorted_out):
            etype = "OUTBOUND_INITIAL" if i == 0 else "OUTBOUND_FOLLOWUP"
            ts_str = m.get("sent_at") or m.get("created_at")
            events.append(ChatEvent(
                timestamp=datetime.fromisoformat(ts_str.replace("Z", "+00:00")),
                sender="PAI Escola Décia",
                body=m.get("body_preview") or "",
                type=etype
            ))
            
        # Adicionar Inbounds
        for r in data["inbounds"]:
            has_p, has_r = analyze_inbound(r.get("body") or "", r.get("reason"))
            ts_str = r.get("received_at")
            events.append(ChatEvent(
                timestamp=datetime.fromisoformat(ts_str.replace("Z", "+00:00")),
                sender="Responsável",
                body=r.get("body") or "",
                type="INBOUND",
                has_protocol=has_p,
                has_reason=has_r
            ))
            
        events.sort(key=lambda x: x.timestamp)
        
        # Resumo do Bloco
        responded = any(e.type == "INBOUND" for e in events)
        gave_reason = any(e.has_reason for e in events)
        gave_proto = any(e.has_protocol for e in events)
        
        final_blocks.append({
            "student": data["student"],
            "guardian": data["guardian"],
            "events": events,
            "summary": {
                "responded": responded,
                "gave_reason": gave_reason,
                "gave_proto": gave_proto,
                "protocol": extract_protocol(data["outbounds"][0].get("body_preview") if data["outbounds"] else "")
            }
        })

    # 5. Gerar TXT Final
    txt_lines = [
        f"DIÁRIO AUDITADO DE CONVERSAS - {campaign_name}",
        f"DATA: {date.today().strftime('%d/%m/%Y')}",
        f"TOTAL DE CONVERSAS ATIVAS (ENVIADAS): {len(final_blocks)}",
        "________________________________________________________________________________\n"
    ]

    for i, b in enumerate(final_blocks, 1):
        std = b["student"]
        grd = b["guardian"]
        sumry = b["summary"]
        
        status_line = "✅ RESPONDEU" if sumry["responded"] else "❌ SEM RESPOSTA"
        if sumry["gave_reason"]: status_line += " | 📝 COM MOTIVO"
        if sumry["gave_proto"]: status_line += " | 🔑 COM PROTOCOLO"
        
        txt_lines.append(f"BLOCO {i}/{len(final_blocks)} - {status_line}")
        txt_lines.append(f"ALUNO: {std.get('name')} | TURMA: {std.get('class_name')} | RA: {std.get('ra')}")
        txt_lines.append(f"RESPONSÁVEL: {grd.get('name')} | TEL: {grd.get('phone_e164')} | PROTOCOLO: {sumry['protocol']}")
        txt_lines.append("-" * 80)
        
        for e in b["events"]:
            prefix = f"[{e.timestamp.strftime('%H:%M')}] {e.sender}"
            if e.type == "OUTBOUND_INITIAL": prefix += " (INICIAL)"
            elif e.type == "OUTBOUND_FOLLOWUP": prefix += " (FOLLOW-UP)"
            
            txt_lines.append(f"{prefix}: {e.body.strip()}")
            if e.type == "INBOUND":
                tags = []
                if e.has_protocol: tags.append("PROTOCOLO_OK")
                if e.has_reason: tags.append("MOTIVO_OK")
                if tags: txt_lines.append(f"      >>> [SISTEMA]: {', '.join(tags)}")
        
        txt_lines.append("\n" + "="*80 + "\n")

    # 6. Markdown de Fechamento
    responded_total = len([b for b in final_blocks if b["summary"]["responded"]])
    reason_total = len([b for b in final_blocks if b["summary"]["gave_reason"]])
    
    md_lines = [
        f"# FECHAMENTO OPERACIONAL — {campaign_name}",
        f"📊 **Balanço da Busca Ativa**",
        f"- 📧 Mensagens Enviadas: {len(final_blocks)}",
        f"- 💬 Conversas com Resposta: {responded_total}",
        f"- 📝 Justificativas Coletadas: {reason_total}",
        f"- ⚠️ Alunos Silenciosos: {len(final_blocks) - responded_total}",
        "\n## 📋 LISTA DE QUEM NÃO RESPONDEU",
    ]
    for b in final_blocks:
        if not b["summary"]["responded"]:
            md_lines.append(f"- {b['student'].get('name')} ({b['student'].get('class_name')})")

    # Salvar
    out_dir = ROOT_DIR / "relatorios" / "consolidados"
    out_dir.mkdir(parents=True, exist_ok=True)
    file_stem = f"auditoria_{date.today().isoformat()}_{campaign_id[:8]}"
    
    (out_dir / f"{file_stem}.txt").write_text("\n".join(txt_lines), encoding="utf-8")
    (out_dir / f"{file_stem}.md").write_text("\n".join(md_lines), encoding="utf-8")
    
    print(f"Auditoria concluida: {len(final_blocks)} conversas analisadas.")
    print(f"Arquivos: {file_stem}.txt e .md")

if __name__ == "__main__":
    main()

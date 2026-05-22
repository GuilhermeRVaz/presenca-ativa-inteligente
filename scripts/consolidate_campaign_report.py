from __future__ import annotations

import argparse
import os
import re
import requests
import sys
import time
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

load_dotenv(ROOT_DIR / ".env")

from app.core.config import settings
from app.infrastructure.supabase.repositories import SupabaseRepository

SCHEMA = "busca_ativa_v2"

EVOLUTION_API_URL = os.getenv("EVOLUTION_API_URL", "").rstrip("/")
EVOLUTION_API_KEY = os.getenv("EVOLUTION_API_KEY", "")
INSTANCE_NAME = os.getenv("EVOLUTION_API_INSTANCE", "")
EVO_HEADERS = {"apikey": EVOLUTION_API_KEY, "Content-Type": "application/json"}

PROTOCOL_RE = re.compile(r'P-([A-F0-9]{6})', re.IGNORECASE)
TEMPLATE_MARKERS = ["para justificar, responda", "codigo do aluno:", "exemplo:"]
CONFIRM_KEYWORDS = ["obrigado", "obrigada", "agradeço", "agradecemos", "motivo:", "entendi", "ciente"]

@dataclass
class ChatEvent:
    timestamp: datetime
    sender: str
    body: str
    type: str # 'OUTBOUND_INITIAL', 'OUTBOUND_FOLLOWUP', 'INBOUND'
    has_protocol: bool = False
    has_reason: bool = False
    is_dynamic: bool = False
    from_evolution: bool = False  # detectado via scan Evolution, nao veio da tabela responses

def extract_protocol(text: str) -> str | None:
    match = re.search(r"P-[A-Z0-9]{6}", text or "")
    return match.group(0) if match else None

def analyze_inbound(text: str, reason: str | None) -> tuple[bool, bool]:
    has_proto = extract_protocol(text) is not None
    if reason is not None and reason != "OUTROS":
        return has_proto, True
        
    # Limpa protocolos do formato P-XXXXXX para avaliar apenas o motivo real
    clean_body = re.sub(r"P-[A-Z0-9]{6}", "", text, flags=re.IGNORECASE).strip()
    
    # Palavras-chave comuns em justificativas de faltas escolares em portugues
    keywords = [
        "febre", "gripe", "garganta", "dor", "estomago", "vomito", "vomitando", "diarreia",
        "doente", "viagem", "viajou", "viajar", "viajando", "medico", "medica", "neurologista",
        "dentista", "consulta", "exame", "atestado", "clinica", "hospital", "posto", "upa",
        "saude", "tratamento", "frio", "roupa", "tenis", "compras", "forum", "guarda", "lins",
        "justificar", "falta", "faltou", "ausente", "motivo", "porque", "pois", "devido",
        "tosse", "vacina", "vacinar", "reacao", "reacoes", "colica", "colicas",
        "inalacao", "inalando", "inalar", "ouvido", "ouvidos", "sangue", "sangramento",
        "chovendo", "chuva", "choveu", "buscou", "buscar", "remedio", "remedios",
        "enjoo", "enjoos", "enjoando", "mal estar", "passando mal", "indisposto",
        "indisposta", "disposicao", "acordou", "acordei",
    ]
    
    normalized = normalize_text(clean_body).lower()
    has_keyword = any(kw in normalized for kw in keywords)
    has_reason = has_keyword or len(clean_body) >= 12
    return has_proto, has_reason

def normalize_text(value: str | None) -> str:
    text = str(value or "")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.upper()
    text = re.sub(r"[^A-Z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()

def clean_text(value: str | None) -> str:
    text = re.sub(r"<Mensagem editada>", "", str(value or ""), flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip()

def _evo_extract_text(msg: dict) -> str:
    """Extrai texto de uma mensagem da Evolution API."""
    m = msg.get("message", {})
    if "conversation" in m:
        return m["conversation"] or ""
    if "extendedTextMessage" in m:
        return m.get("extendedTextMessage", {}).get("text", "")
    return ""

def _evo_is_confirmation(text: str) -> bool:
    """Escola enviou confirmacao de justificativa (ex: 'obrigado, motivo: ...')."""
    tl = text.lower()
    return any(k in tl for k in CONFIRM_KEYWORDS) and not any(k in tl for k in TEMPLATE_MARKERS)

def _evo_fetch_conversation(jid: str, limit: int = 50) -> list[dict]:
    """Busca mensagens de um chat via Evolution API."""
    url = f"{EVOLUTION_API_URL}/chat/findMessages/{INSTANCE_NAME}"
    payload = {"where": {"key": {"remoteJid": jid}}, "limit": limit}
    try:
        r = requests.post(url, json=payload, headers=EVO_HEADERS, timeout=15)
        if r.status_code == 200:
            return r.json().get("messages", {}).get("records", [])
    except Exception:
        pass
    return []

def _parse_evo_timestamp(value: Any) -> datetime | None:
    try:
        timestamp = int(value or 0)
    except (TypeError, ValueError):
        return None
    if timestamp <= 0:
        return None
    if timestamp > 10_000_000_000:
        timestamp = int(timestamp / 1000)
    return datetime.fromtimestamp(timestamp, tz=timezone.utc)

def _parse_db_timestamp(value: Any) -> datetime:
    text = str(value or "").strip()
    if not text:
        return datetime.now(timezone.utc)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(timezone.utc)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed

def _evo_scan_jid(jid: str, target_date: date) -> tuple[list[dict], list[dict]]:
    """Varre um JID no dia da campanha. Retorna (escola_msgs, pai_msgs)."""
    records = _evo_fetch_conversation(jid, limit=100)
    escola = []
    pai = []
    for msg in records:
        msg_dt = _parse_evo_timestamp(msg.get("messageTimestamp", 0))
        if not msg_dt:
            continue
        if msg_dt.date() != target_date:
            continue
        text = _evo_extract_text(msg).strip()
        if not text:
            continue
        entry = {"dt": msg_dt, "time": msg_dt.strftime("%H:%M"), "text": text}
        if msg.get("key", {}).get("fromMe"):
            escola.append(entry)
        else:
            pai.append(entry)
    return escola, pai

def _evo_find_missing_responses(student_puzzle: dict, identity_map: dict, campaign_date: date) -> dict:
    """Varre Evolution API para alunos sem inbound response na tabela responses.
    Retorna {student_id: list[ChatEvent]} com eventos inbound detectados via Evolution."""
    found = {}

    # Monta guardiao -> [lids] a partir do identity_map (inverter)
    guardian_to_lids = defaultdict(set)
    for lid_jid, wa_jid in identity_map.items():
        guardian_to_lids[wa_jid].add(lid_jid)

    students_to_scan = []
    for sid, data in student_puzzle.items():
        if data["inbounds"]:
            continue  # ja tem resposta na tabela responses
        students_to_scan.append((sid, data))

    if not students_to_scan:
        print("  [Evolution] Todos os alunos ja tem resposta na tabela responses. Scan pulado.")
        return found

    print(f"  [Evolution] {len(students_to_scan)} alunos sem resposta no banco. Varrendo WhatsApp...")
    scanned = 0
    found_count = 0

    for sid, data in students_to_scan:
        outbound_jid = data["outbounds"][0].get("wa_jid") if data["outbounds"] else None
        if not outbound_jid:
            continue

        # Todos os JIDs a varrer: wa_jid + LIDs mapeados
        jids_to_scan = {outbound_jid}
        if outbound_jid in guardian_to_lids:
            jids_to_scan.update(guardian_to_lids[outbound_jid])

        all_escola = []
        all_pai = []
        for j in jids_to_scan:
            e, p = _evo_scan_jid(j, campaign_date)
            all_escola.extend(e)
            all_pai.extend(p)

        all_escola.sort(key=lambda x: x["dt"])
        all_pai.sort(key=lambda x: x["dt"])

        # Detecta justificativa: pai enviou algo OU escola confirmou (2+ outbound com agradecimento)
        has_pai = len(all_pai) > 0
        escola_confirmou = False
        confirm_text = ""
        if len(all_escola) > 1:
            for em in all_escola[1:]:
                if _evo_is_confirmation(em["text"]):
                    escola_confirmou = True
                    confirm_text = em["text"][:200]
                    break

        if not has_pai and not escola_confirmou:
            continue

        events = []
        student_name = data["student"].get("name", "?")
        student_id = data["student"].get("id") or sid

        if has_pai:
            reason_texts = []
            for pm in all_pai:
                proto_ok = extract_protocol(pm["text"]) is not None
                _, reason_ok = analyze_inbound(pm["text"], None)
                events.append(ChatEvent(
                    timestamp=pm["dt"],
                    sender="Responsável",
                    body=pm["text"],
                    type="INBOUND",
                    has_protocol=proto_ok,
                    has_reason=reason_ok,
                    from_evolution=True,
                ))
                if reason_ok:
                    reason_texts.append(pm["text"][:80])

            print(f"  [EVO OK] {student_name} - pai respondeu ({len(all_pai)} msgs): {reason_texts[0] if reason_texts else '?'}")

        elif escola_confirmou:
            proto_ok = extract_protocol(confirm_text) is not None
            _, reason_ok = analyze_inbound(confirm_text, None)
            events.append(ChatEvent(
                timestamp=all_escola[-1]["dt"],
                sender="PAI Escola Décia",
                body=f"[CONFIRMAÇÃO EVOLUTION] {confirm_text}"[:300],
                type="INBOUND",
                has_protocol=proto_ok,
                has_reason=reason_ok,
                from_evolution=True,
            ))
            print(f"  [EVO OK] {student_name} - escola confirmou: {confirm_text[:80]}")

        if events:
            student_puzzle[sid]["inbounds_evo"] = events
            found[sid] = events
            found_count += 1

        scanned += 1
        if scanned % 5 == 0:
            time.sleep(0.3)

    print(f"  [Evolution] Scan concluido: {scanned} varridos, {found_count} respostas encontradas no WhatsApp")
    return found

def student_name_score(student_name: str, text: str) -> float:
    student_norm = normalize_text(student_name)
    text_norm = normalize_text(text)
    if not student_norm or not text_norm:
        return 0.0
    if student_norm in text_norm:
        return 1.0

    tokens = student_norm.split()
    first_token_hit = bool(tokens and tokens[0] in text_norm)
    token_hits = sum(1 for token in tokens if len(token) > 2 and token in text_norm)
    token_score = token_hits / max(len(tokens), 1)
    ratio = SequenceMatcher(None, student_norm, text_norm[: max(len(student_norm) * 2, 80)]).ratio()
    score = max(token_score, ratio)
    if not first_token_hit:
        score = min(score, 0.49)
    return score

def suggest_student(messages: list[dict[str, Any]], text: str) -> tuple[str, float, str]:
    scored: list[tuple[float, str]] = []
    for message in messages:
        student = message.get("students") or {}
        name = str(student.get("name") or "")
        score = student_name_score(name, text)
        scored.append((score, name))
    scored.sort(reverse=True, key=lambda item: item[0])
    if not scored:
        return "", 0.0, ""
    top_score, top_name = scored[0]
    second_score = scored[1][0] if len(scored) > 1 else 0.0
    delta = top_score - second_score
    if top_score >= 0.58 and delta >= 0.15:
        return top_name, top_score, "SUGESTAO_TEXTUAL_NAO_CONFIRMADA"
    return "", top_score, "SEM_SUGESTAO_SEGURA"

def run_consolidate(campaign_id: str, school_id: str) -> dict:
    """Função reutilizável chamada pelo campaign_reporter."""
    repo = SupabaseRepository()
    client = repo.client.schema(SCHEMA)

    c_rows = client.table("campaigns").select("id, name, absence_days").eq("id", campaign_id).execute().data
    campaign_name = c_rows[0]["name"] if c_rows else "Campanha Desconhecida"
    absence_days_str = c_rows[0]["absence_days"] if c_rows else date.today().strftime("%d/%m/%Y")

    try:
        campaign_date = datetime.strptime(absence_days_str.split(",")[0].strip(), "%d/%m/%Y").date()
    except Exception:
        campaign_date = date.today()

    # 1. Pegar Mapa de Identidade (LIDs)
    identity_map = {}
    id_rows = client.table("phone_identity_map").select("wa_jid, lid_jid").execute().data or []
    for row in id_rows:
        identity_map[row["lid_jid"]] = row["wa_jid"]

    # 2. Pegar TODAS as mensagens e respostas da campanha + respostas órfãs de hoje
    all_msgs = client.table("messages").select("*, students(*), guardians(*)").eq("campaign_id", campaign_id).execute().data or []
    
    # Busca ampla de respostas: da campanha OU do dia da campanha (para pegar follow-ups manuais/outros)
    campaign_date_iso = campaign_date.isoformat()
    all_resps_raw = client.table("responses").select("*").or_(f"campaign_id.eq.{campaign_id},received_at.gte.{campaign_date_iso}T00:00:00+00:00").execute().data or []
    
    # Filtrar respostas em memoria para garantir que sao da campanha ou da mesma data
    all_resps = []
    for r in all_resps_raw:
        if r.get("campaign_id") == campaign_id:
            all_resps.append(r)
            continue
        rx_at_str = r.get("received_at")
        if rx_at_str:
            rx_date = datetime.fromisoformat(rx_at_str.replace("Z", "+00:00")).date()
            if rx_date == campaign_date:
                all_resps.append(r)

    # 3. Organizar por Aluno
    sent_msgs = [m for m in all_msgs if m.get("status") in ["sent", "delivered", "read", "replied"]]
    
    student_puzzle = defaultdict(lambda: {"outbounds": [], "inbounds": [], "student": {}, "guardian": {}})
    
    for m in sent_msgs:
        sid = m.get("student_id")
        student_puzzle[sid]["outbounds"].append(m)
        student_puzzle[sid]["student"] = m.get("students") or {}
        student_puzzle[sid]["guardian"] = m.get("guardians") or {}

    # Pegar push_name de cada sender_jid
    sessions = {}
    senders = {r.get("sender_jid") for r in all_resps if r.get("sender_jid")}
    if senders:
        s_rows = client.table("conversation_sessions").select("sender_jid, push_name").eq("school_id", school_id).in_("sender_jid", list(senders)).execute().data or []
        for s in s_rows:
            sessions[s["sender_jid"]] = s.get("push_name") or ""

    # Distribuir respostas de forma inteligente e agrupada por sender_jid
    by_sender = defaultdict(list)
    for r in all_resps:
        if r.get("sender_jid"):
            by_sender[r["sender_jid"]].append(r)
            
    for sender, resps in by_sender.items():
        target_sid = None
        
        for r in resps:
            if r.get("student_id"):
                target_sid = r["student_id"]
                break
                
        if not target_sid:
            for r in resps:
                proto = extract_protocol(r.get("body") or "")
                if proto:
                    for m in sent_msgs:
                        if proto in (m.get("body_preview") or ""):
                            target_sid = m.get("student_id")
                            break
                    if target_sid:
                        break
                        
        if not target_sid:
            resolved_sender = identity_map.get(sender, sender)
            for sid_key, data in student_puzzle.items():
                phone = data["guardian"].get("phone_e164") or ""
                if phone and phone in resolved_sender:
                    target_sid = sid_key
                    break
                if data["outbounds"] and data["outbounds"][0].get("wa_jid") == resolved_sender:
                    target_sid = sid_key
                    break
                    
        if not target_sid:
            push_name = sessions.get(sender, "")
            combined_text = " | ".join(clean_text(r.get("body")) for r in resps)
            suggestion_text = f"{push_name} | {combined_text}"
            suggested_name, score, note = suggest_student(sent_msgs, suggestion_text)
            if suggested_name:
                for m in sent_msgs:
                    if m.get("students", {}).get("name") == suggested_name:
                        target_sid = m.get("student_id")
                        break
                        
        if target_sid and target_sid in student_puzzle:
            existing_ids = {x.get("id") for x in student_puzzle[target_sid]["inbounds"] if x.get("id")}
            for r in resps:
                if r.get("id") not in existing_ids:
                    student_puzzle[target_sid]["inbounds"].append(r)

    # 3.5 Evolution Fallback: varrer WhatsApp para alunos sem resposta no banco
    print(f"\n  [Evolution] Buscando respostas diretamente no WhatsApp para alunos sem retorno no banco...")
    evo_found = _evo_find_missing_responses(student_puzzle, identity_map, campaign_date)
    for sid, evo_events in evo_found.items():
        student_puzzle[sid]["inbounds_evo"] = evo_events
    print()

    # 4. Construir Diário Auditado
    final_blocks = []
    for sid, data in student_puzzle.items():
        events: list[ChatEvent] = []
        
        sorted_out = sorted(data["outbounds"], key=lambda x: x.get("sent_at") or x.get("created_at"))
        for i, m in enumerate(sorted_out):
            etype = "OUTBOUND_INITIAL" if i == 0 else "OUTBOUND_FOLLOWUP"
            ts_str = m.get("sent_at") or m.get("created_at")
            events.append(ChatEvent(
                timestamp=_parse_db_timestamp(ts_str),
                sender="PAI Escola Décia",
                body=m.get("body_preview") or "",
                type=etype
            ))
            
        for r in data["inbounds"]:
            has_p, has_r = analyze_inbound(r.get("body") or "", r.get("reason"))
            ts_str = r.get("received_at")
            is_dyn = not r.get("student_id") or r.get("student_id") != sid
            events.append(ChatEvent(
                timestamp=_parse_db_timestamp(ts_str),
                sender="Responsável",
                body=r.get("body") or "",
                type="INBOUND",
                has_protocol=has_p,
                has_reason=has_r,
                is_dynamic=is_dyn
            ))

        for evo_event in data.get("inbounds_evo", []):
            events.append(evo_event)
            
        events.sort(key=lambda x: x.timestamp)
        
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
                if e.from_evolution: tags.append("ORIGEM_EVOLUTION")
                if e.has_protocol: tags.append("PROTOCOLO_OK")
                if e.has_reason: tags.append("MOTIVO_OK")
                if getattr(e, "is_dynamic", False): tags.append("RESOLVIDO_POR_IA_TEXTUAL")
                if tags: txt_lines.append(f"      >>> [SISTEMA]: {', '.join(tags)}")
        
        txt_lines.append("\n" + "="*80 + "\n")

    # 6. Markdown de Fechamento
    responded_total = len([b for b in final_blocks if b["summary"]["responded"]])
    reason_total = len([b for b in final_blocks if b["summary"]["gave_reason"]])

    # ── DIAGNÓSTICO: tabela por aluno ─────────────────────────────────────
    print("\n" + "=" * 80)
    print("  DIAGNÓSTICO DE DETECÇÃO DE JUSTIFICATIVAS")
    print("=" * 80)
    header = f"  {'PROTOCOLO':<10} {'ALUNO':<35} {'RESP':<5} {'MOTIVO':<7} {'DETALHE'}"
    print(header)
    print("  " + "-" * 76)
    for b in final_blocks:
        s = b["summary"]
        proto = s.get("protocol", "?") or "?"
        name = (b["student"].get("name") or "?")[:33]
        resp = "SIM" if s["responded"] else "NAO"
        motivo = "SIM" if s["gave_reason"] else "NAO"

        # Coletar detalhes das mensagens inbound
        inbound_texts = []
        for e in b["events"]:
            if e.type == "INBOUND":
                tags = []
                if e.from_evolution: tags.append("EVO")
                if e.has_reason: tags.append("REASON")
                if e.has_protocol: tags.append("PROTO")
                inbound_texts.append(f"[{'|'.join(tags)}] {e.body[:50]}")
        detalhe = " | ".join(inbound_texts[:3]) if inbound_texts else "-"

        print(f"  {proto:<10} {name:<35} {resp:<5} {motivo:<7} {detalhe[:70]}")

    print("  " + "-" * 76)
    print(f"  TOTAL: {len(final_blocks)} conversas | Responderam: {responded_total} | Justificaram: {reason_total} | Sem resposta: {len(final_blocks) - responded_total}")
    print("=" * 80 + "\n")
    
    md_lines = [
        f"# FECHAMENTO OPERACIONAL — {campaign_name}",
        f"📊 **Balanço da Busca Ativa**",
        f"- 📧 Mensagens Enviadas: {len(final_blocks)}",
        f"- 💬 Conversas com Resposta: {responded_total}",
        f"- 📝 Justificativas Coletadas: {reason_total}",
        f"- ⚠️ Alunos Silenciosos: {len(final_blocks) - responded_total}",
        "\n## ✅ RESPOSTAS E JUSTIFICATIVAS RECEBIDAS"
    ]
    
    for b in final_blocks:
        if b["summary"]["responded"]:
            std = b["student"]
            inbound_msgs = []
            for e in b["events"]:
                if e.type == "INBOUND":
                    inbound_msgs.append(f"  - *[{e.timestamp.strftime('%H:%M')}]* {e.body.strip()}")
            
            proto_status = "🔑 Protocolo Confirmado" if b["summary"]["gave_proto"] else "⚠️ Sem Protocolo"
            reason_status = "📝 Justificativa Identificada" if b["summary"]["gave_reason"] else "❓ Sem Motivo Claro"
            
            md_lines.append(f"### 👤 {std.get('name')} ({std.get('class_name')})")
            md_lines.append(f"- **Status**: {proto_status} | {reason_status}")
            md_lines.append("- **Mensagens Recebidas**:")
            md_lines.extend(inbound_msgs)
            md_lines.append("")
            
    md_lines.append("\n## 📋 LISTA DE QUEM NÃO RESPONDEU")
    for b in final_blocks:
        if not b["summary"]["responded"]:
            md_lines.append(f"- {b['student'].get('name')} ({b['student'].get('class_name')})")
            
    # Salvar
    out_dir = ROOT_DIR / "relatorios" / "consolidados"
    out_dir.mkdir(parents=True, exist_ok=True)
    file_stem = f"auditoria_{campaign_date.isoformat()}_{campaign_id[:8]}"
    
    (out_dir / f"{file_stem}.txt").write_text("\n".join(txt_lines), encoding="utf-8")
    (out_dir / f"{file_stem}.md").write_text("\n".join(md_lines), encoding="utf-8")
    
    evo_responded = len([b for b in final_blocks if any(e.from_evolution for e in b["events"] if e.type == "INBOUND")])
    print(f"Auditoria concluida: {len(final_blocks)} conversas analisadas.")
    print(f"  (via DB: {responded_total - evo_responded} | via Evolution: {evo_responded})")
    print(f"Arquivos: {file_stem}.txt e .md")
    
    return {
        "total_conversas": len(final_blocks),
        "responderam": responded_total,
        "justificaram": reason_total,
        "sem_resposta": len(final_blocks) - responded_total,
        "evolution_encontrados": evo_responded,
        "arquivos": [f"{file_stem}.txt", f"{file_stem}.md"]
    }

def main():
    parser = argparse.ArgumentParser(description="Auditor de Conversas PAI")
    parser.add_argument("--campaign-id", help="ID da campanha")
    parser.add_argument("--school-id", default=settings.default_school_id)
    args = parser.parse_args()

    campaign_id = args.campaign_id
    if not campaign_id:
        repo = SupabaseRepository()
        client = repo.client.schema(SCHEMA)
        today = date.today().strftime("%d/%m/%Y")
        c_rows = client.table("campaigns").select("id, name, absence_days").eq("school_id", args.school_id).eq("absence_days", today).order("created_at", desc=True).limit(1).execute().data
        if not c_rows:
            print("Nenhuma campanha encontrada para hoje.")
            return
        campaign_id = c_rows[0]["id"]

    run_consolidate(campaign_id=campaign_id, school_id=args.school_id)

if __name__ == "__main__":
    main()

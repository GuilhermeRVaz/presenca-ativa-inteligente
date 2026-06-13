"""
full_day_report.py — Relatório completo dia a dia
Consolida TODAS as mensagens e respostas de uma campanha, incluindo:
- Status de entrega por destinatário
- Justificativas recebidas (mesmo as UNRESOLVED com texto)
- Agrupamento inteligente por responsável/JID
- Saída em Markdown + CSV + Excel
"""
import os
import sys
import argparse
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from unicodedata import normalize
import unicodedata

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from dotenv import load_dotenv
load_dotenv()
from supabase import create_client, ClientOptions

# ──────────────────────────────────────────────────────────────────────────────
# MONKEY-PATCH: Retentativas globais para qualquer consulta Supabase/Postgrest
# ──────────────────────────────────────────────────────────────────────────────
try:
    from postgrest._sync.request_builder import SyncQueryRequestBuilder
    
    _original_postgrest_execute = SyncQueryRequestBuilder.execute
    
    def _robust_postgrest_execute(self, *args, **kwargs):
        import time
        last_error = None
        for attempt in range(1, 4):
            try:
                return _original_postgrest_execute(self, *args, **kwargs)
            except Exception as exc:
                last_error = exc
                err_str = str(exc).lower()
                exc_class = exc.__class__.__name__
                
                is_network_err = (
                    "connect" in err_str or 
                    "timeout" in err_str or 
                    "getaddrinfo" in err_str or 
                    "connection" in err_str or
                    "http" in exc_class.lower() or
                    "timeout" in exc_class.lower() or
                    "error" in exc_class.lower()
                )
                if "apierror" in exc_class.lower() or "postgrest" in exc.__class__.__module__:
                    is_network_err = False
                    
                if not is_network_err:
                    raise exc
                    
                if attempt >= 3:
                    break
                time.sleep(2 ** attempt)
        raise last_error

    SyncQueryRequestBuilder.execute = _robust_postgrest_execute
except Exception:
    pass
# ──────────────────────────────────────────────────────────────────────────────

# ──────────────────────────────────────────────────────────────────────────────
CONFIDENCE_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2, "UNRESOLVED": 3}


def safe_str(v) -> str:
    if v is None:
        return ""
    try:
        return str(v).encode("utf-8", errors="replace").decode("utf-8")
    except Exception:
        return repr(v)


def slugify(text: str) -> str:
    text = normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def make_client():
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_KEY"]
    from supabase.lib.client_options import SyncClientOptions
    return create_client(url, key, options=SyncClientOptions(schema="busca_ativa_v2", postgrest_client_timeout=30.0))


def _parse_campaign_ids(campaign_id: str | list) -> list[str]:
    if isinstance(campaign_id, list):
        return campaign_id
    if isinstance(campaign_id, str) and "," in campaign_id:
        return [c.strip() for c in campaign_id.split(",")]
    return [campaign_id]


def fetch_campaign(client, campaign_id: str) -> dict:
    campaign_ids = _parse_campaign_ids(campaign_id)
    res = client.table("campaigns").select("*").in_("id", campaign_ids).execute()
    if not res.data:
        raise SystemExit(f"Campaigns {campaign_ids} not found.")
    return res.data[0]


def fetch_messages(client, campaign_id: str) -> list[dict]:
    """Outbound messages sent in this campaign."""
    campaign_ids = _parse_campaign_ids(campaign_id)
    res = (
        client.table("messages")
        .select("id,student_id,guardian_id,wa_jid,status,sent_at,evolution_msg_id,body_preview")
        .in_("campaign_id", campaign_ids)
        .order("sent_at")
        .execute()
    )
    return res.data or []


def fetch_responses(client, campaign_id: str) -> list[dict]:
    """All inbound responses linked to this campaign (or not)."""
    campaign_ids = _parse_campaign_ids(campaign_id)
    res = (
        client.table("responses")
        .select("id,sender_jid,student_id,guardian_id,campaign_id,identity_confidence,body,reason,received_at")
        .in_("campaign_id", campaign_ids)
        .order("received_at")
        .execute()
    )
    return res.data or []


def fetch_orphan_responses(client, school_id: str, campaign_id: str, date_str: str) -> list[dict]:
    """Responses received on the campaign date but without campaign_id linked."""
    day_start = f"{date_str}T00:00:00+00:00"
    day_end = f"{date_str}T23:59:59+00:00"
    res = (
        client.table("responses")
        .select("id,sender_jid,student_id,guardian_id,campaign_id,identity_confidence,body,reason,received_at")
        .eq("school_id", school_id)
        .is_("campaign_id", "null")
        .gte("received_at", day_start)
        .lte("received_at", day_end)
        .order("received_at")
        .execute()
    )
    return res.data or []


def fetch_next_day_responses(client, school_id: str, campaign_id: str, next_date_str: str) -> list[dict]:
    """Responses received the day after the campaign (late replies)."""
    campaign_ids = _parse_campaign_ids(campaign_id)
    day_start = f"{next_date_str}T00:00:00+00:00"
    day_end = f"{next_date_str}T23:59:59+00:00"
    res = (
        client.table("responses")
        .select("id,sender_jid,student_id,guardian_id,campaign_id,identity_confidence,body,reason,received_at")
        .eq("school_id", school_id)
        .in_("campaign_id", campaign_ids)
        .gte("received_at", day_start)
        .lte("received_at", day_end)
        .order("received_at")
        .execute()
    )
    return res.data or []


def fetch_students(client, student_ids: list[str]) -> dict[str, dict]:
    if not student_ids:
        return {}
    res = client.table("students").select("id,name,class_name,ra").in_("id", student_ids).execute()
    return {r["id"]: r for r in (res.data or [])}


def fetch_guardians(client, guardian_ids: list[str]) -> dict[str, dict]:
    if not guardian_ids:
        return {}
    res = client.table("guardians").select("id,name,phone_e164,wa_jid").in_("id", guardian_ids).execute()
    return {r["id"]: r for r in (res.data or [])}


def fetch_phone_identity_map(client, school_id: str) -> dict[str, str]:
    """Returns lid_jid -> guardian_id"""
    res = client.table("phone_identity_map").select("lid_jid,guardian_id,confidence").eq("school_id", school_id).execute()
    result = {}
    for r in (res.data or []):
        if r.get("lid_jid") and r.get("guardian_id"):
            result[r["lid_jid"]] = r["guardian_id"]
    return result


def normalize_jid(jid: str) -> str:
    """Normalize a JID to its number part for cross-matching."""
    if not jid:
        return ""
    return jid.split("@")[0]


# ──────────────────────────────────────────────────────────────────────────────

def build_report(client, campaign_id: str) -> str:
    # First fetch the single campaign to get school_id
    temp_campaign_ids = _parse_campaign_ids(campaign_id)
    temp_campaign = fetch_campaign(client, temp_campaign_ids[0])
    school_id = temp_campaign["school_id"]

    # Resolve campaign group (RF-01)
    from app.application.analytics.campaign_analytics import resolve_campaign_group
    campaign_ids, c_rows = resolve_campaign_group(client, school_id, campaign_id)

    # Use c_rows to build the campaign name and date
    campaign = c_rows[0] if c_rows else temp_campaign
    absence_days = campaign.get("absence_days", "")
    if len(campaign_ids) > 1:
        camp_name = " + ".join(c.get("name", "") for c in c_rows if c.get("name")) or f"{campaign.get('name', campaign_ids[0][:8])} + Follow-up"
    else:
        camp_name = campaign.get("name", campaign_ids[0][:8])

    # Parse campaign date
    created = campaign.get("created_at", "")
    try:
        campaign_date = datetime.fromisoformat(created.replace("Z", "+00:00")).date()
    except Exception:
        try:
            campaign_date = datetime.strptime(absence_days.split(",")[0].strip(), "%d/%m/%Y").date()
        except Exception:
            campaign_date = datetime.now().date()
            
    camp_date = campaign_date.isoformat()

    # 1. Pegar Mapa de Identidade (LIDs)
    identity_map = {}
    id_rows = client.table("phone_identity_map").select("wa_jid, lid_jid").execute().data or []
    for row in id_rows:
        identity_map[row["lid_jid"]] = row["wa_jid"]

    # 2. Pegar todas as mensagens
    all_msgs = client.table("messages").select("*, students(*), guardians(*)").in_("campaign_id", campaign_ids).execute().data or []

    # 3. Pegar todas as respostas da campanha + respostas do mesmo dia
    campaign_date_iso = campaign_date.isoformat()
    or_filters = [f"campaign_id.in.({','.join(campaign_ids)})", f"received_at.gte.{campaign_date_iso}T00:00:00+00:00"]
    all_resps_raw = client.table("responses").select("*").or_(",".join(or_filters)).execute().data or []
    
    all_resps = []
    for r in all_resps_raw:
        if r.get("campaign_id") in campaign_ids:
            all_resps.append(r)
            continue
        rx_at_str = r.get("received_at")
        if rx_at_str:
            try:
                rx_date = datetime.fromisoformat(rx_at_str.replace("Z", "+00:00")).date()
                if rx_date == campaign_date:
                    all_resps.append(r)
            except Exception:
                pass

    # Pegar push_name de cada sender_jid
    sessions = {}
    senders = {r.get("sender_jid") for r in all_resps if r.get("sender_jid")}
    if senders:
        s_rows = client.table("conversation_sessions").select("sender_jid, push_name").eq("school_id", school_id).in_("sender_jid", list(senders)).execute().data or []
        for s in s_rows:
            sessions[s["sender_jid"]] = s.get("push_name") or ""

    # Bulk-fetch students/guardians maps
    all_student_ids = list({m.get("student_id") for m in all_msgs if m.get("student_id")} |
                           {r.get("student_id") for r in all_resps if r.get("student_id")})
    all_guardian_ids = list({m.get("guardian_id") for m in all_msgs if m.get("guardian_id")} |
                            {r.get("guardian_id") for r in all_resps if r.get("guardian_id")})

    students_map = fetch_students(client, all_student_ids)
    guardians_map = fetch_guardians(client, all_guardian_ids)

    def get_student_key(student_id: str) -> str:
        if not student_id:
            return ""
        std = students_map.get(student_id) or {}
        ra = std.get("ra")
        if ra and str(ra).strip():
            return f"ra:{str(ra).strip()}"
        return f"id:{student_id}"

    # Agrupar mensagens por aluno único (mesmo com falhas)
    student_puzzle = defaultdict(lambda: {"outbounds": [], "inbounds": [], "student": {}, "guardian": {}})
    student_id_to_key = {}
    for m in all_msgs:
        sid = m.get("student_id")
        if not sid:
            continue
        skey = get_student_key(sid)
        student_id_to_key[sid] = skey
        
        student_puzzle[skey]["outbounds"].append(m)
        if not student_puzzle[skey]["student"]:
            student_puzzle[skey]["student"] = students_map.get(sid) or m.get("students") or {}
        if not student_puzzle[skey]["guardian"]:
            student_puzzle[skey]["guardian"] = guardians_map.get(m.get("guardian_id")) or m.get("guardians") or {}

    # Import helpers from consolidate_campaign_report
    from scripts.consolidate_campaign_report import analyze_inbound, extract_protocol, suggest_student, clean_text

    # Distribuir respostas por aluno único
    by_sender = defaultdict(list)
    for r in all_resps:
        if r.get("sender_jid"):
            by_sender[r["sender_jid"]].append(r)

    sent_msgs = [m for m in all_msgs if m.get("status") in ["sent", "delivered", "read", "replied"]]
    mapped_response_ids = set()

    for sender, resps in by_sender.items():
        target_skey = None
        
        for r in resps:
            sid = r.get("student_id")
            if sid:
                target_skey = student_id_to_key.get(sid) or get_student_key(sid)
                break
                
        if not target_skey:
            for r in resps:
                proto = extract_protocol(r.get("body") or "")
                if proto:
                    for m in sent_msgs:
                        if proto in (m.get("body_preview") or ""):
                            sid = m.get("student_id")
                            if sid:
                                target_skey = student_id_to_key.get(sid) or get_student_key(sid)
                                break
                    if target_skey:
                        break
                        
        if not target_skey:
            resolved_sender = identity_map.get(sender, sender)
            for skey, data in student_puzzle.items():
                phone = data["guardian"].get("phone_e164") or ""
                if phone and phone in resolved_sender:
                    target_skey = skey
                    break
                if data["outbounds"] and any(m.get("wa_jid") == resolved_sender for m in data["outbounds"]):
                    target_skey = skey
                    break
                    
        if not target_skey:
            push_name = sessions.get(sender, "")
            combined_text = " | ".join(clean_text(r.get("body")) for r in resps)
            suggestion_text = f"{push_name} | {combined_text}"
            suggested_name, score, note = suggest_student(sent_msgs, suggestion_text)
            if suggested_name:
                for m in sent_msgs:
                    if m.get("students", {}).get("name") == suggested_name:
                        sid = m.get("student_id")
                        if sid:
                            target_skey = student_id_to_key.get(sid) or get_student_key(sid)
                            break
                        
        if target_skey and target_skey in student_puzzle:
            existing_ids = {x.get("id") for x in student_puzzle[target_skey]["inbounds"] if x.get("id")}
            for r in resps:
                if r.get("id") not in existing_ids:
                    student_puzzle[target_skey]["inbounds"].append(r)
                mapped_response_ids.add(r.get("id"))
        else:
            for r in resps:
                if r.get("id"):
                    mapped_response_ids.add(r.get("id"))

    # Track which targeted students responded
    responded_student_keys = set()
    for skey, data in student_puzzle.items():
        has_success = any(m.get("status") in ["sent", "delivered", "read", "replied"] for m in data["outbounds"])
        if not has_success:
            continue
        if len(data["inbounds"]) > 0:
            responded_student_keys.add(skey)

    # Summary stats
    total = len(student_puzzle)
    sent = sum(1 for skey, data in student_puzzle.items() if any(m.get("status") in ["sent", "delivered", "read", "replied"] for m in data["outbounds"]))
    failed = sum(1 for skey, data in student_puzzle.items() if not any(m.get("status") in ["sent", "delivered", "read", "replied"] for m in data["outbounds"]) and any(m.get("status") == "failed" for m in data["outbounds"]))
    with_resp = len(responded_student_keys)

    high_conf = sum(1 for r in all_resps if r.get("identity_confidence") == "HIGH")
    unresolved = sum(1 for r in all_resps if r.get("identity_confidence") == "UNRESOLVED")

    # ── Group responses by sender for display ──────────────────────────────────
    grouped_resp: dict[str, dict] = {}
    
    for skey, data in student_puzzle.items():
        if skey not in responded_student_keys:
            continue
        for r in data["inbounds"]:
            jid = r.get("sender_jid") or "unknown"
            if jid not in grouped_resp:
                grouped_resp[jid] = {
                    "jid": jid,
                    "student_id": data["student"].get("id"),
                    "guardian_id": data["guardian"].get("id"),
                    "confidence": r.get("identity_confidence", "UNRESOLVED"),
                    "texts": [],
                    "received_at": r.get("received_at")
                }
            
            current_conf = r.get("identity_confidence", "UNRESOLVED")
            if CONFIDENCE_ORDER.get(current_conf, 9) < CONFIDENCE_ORDER.get(grouped_resp[jid]["confidence"], 9):
                grouped_resp[jid]["confidence"] = current_conf
            
            txt = safe_str(r.get("body") or r.get("reason") or "").strip()
            if txt and txt not in grouped_resp[jid]["texts"]:
                grouped_resp[jid]["texts"].append(txt)

    unmapped_resps = [r for r in all_resps if r.get("id") not in mapped_response_ids]
    for r in unmapped_resps:
        jid = r.get("sender_jid") or "unknown"
        if jid not in grouped_resp:
            grouped_resp[jid] = {
                "jid": jid,
                "student_id": r.get("student_id"),
                "guardian_id": r.get("guardian_id"),
                "confidence": r.get("identity_confidence", "UNRESOLVED"),
                "texts": [],
                "received_at": r.get("received_at")
            }
        
        current_conf = r.get("identity_confidence", "UNRESOLVED")
        if CONFIDENCE_ORDER.get(current_conf, 9) < CONFIDENCE_ORDER.get(grouped_resp[jid]["confidence"], 9):
            grouped_resp[jid]["confidence"] = current_conf
        
        txt = safe_str(r.get("body") or r.get("reason") or "").strip()
        if txt and txt not in grouped_resp[jid]["texts"]:
            grouped_resp[jid]["texts"].append(txt)

    # ── Build output lines ────────────────────────────────────────────────────
    lines = []
    lines.append(f"# Relatório Operacional — {camp_name}")
    lines.append(f"**Data da campanha:** {camp_date}  ")
    lines.append(f"**Dia(s) de falta:** {safe_str(absence_days)}  ")
    lines.append(f"**ID da campanha:** `{', '.join(campaign_ids)}`  ")
    lines.append(f"**Gerado em:** {datetime.now().strftime('%d/%m/%Y %H:%M')}  ")
    lines.append("")

    lines.append("## Resumo")
    lines.append("")
    lines.append(f"| Métrica | Valor |")
    lines.append(f"|---|---|")
    lines.append(f"| Total de destinatários | **{total}** |")
    lines.append(f"| Mensagens enviadas com sucesso | **{sent}** |")
    lines.append(f"| Falhas de envio | **{failed}** |")
    lines.append(f"| Respostas recebidas (de responsáveis distintos) | **{with_resp}** |")
    lines.append(f"| Identidade confirmada (HIGH) | **{high_conf}** |")
    lines.append(f"| Não resolvidos (UNRESOLVED) | **{unresolved}** |")
    lines.append("")

    # ── Alunos com resposta ───────────────────────────────────────────────────
    lines.append("---")
    lines.append("## Justificativas Recebidas")
    lines.append("")

    for jid, data in sorted(grouped_resp.items(), key=lambda x: CONFIDENCE_ORDER.get(x[1]["confidence"], 9)):
        sid = data["student_id"]
        gid = data["guardian_id"]
        conf = data["confidence"]
        text_block = " | ".join(data["texts"])
        recv_at = (data["received_at"] or "")[:16].replace("T", " ")

        student = students_map.get(sid, {}) if sid else {}
        guardian = guardians_map.get(gid, {}) if gid else {}

        student_name = safe_str(student.get("name") or "Aluno não identificado")
        student_class = safe_str(student.get("class_name") or "")
        student_ra = safe_str(student.get("ra") or "")
        guardian_name = safe_str(guardian.get("name") or "Responsável não identificado")

        conf_emoji = {"HIGH": "🟢", "MEDIUM": "🟡", "LOW": "🟠", "UNRESOLVED": "🔴"}.get(conf, "❓")

        lines.append(f"### {conf_emoji} {student_name}")
        if student_class:
            lines.append(f"**Turma:** {student_class} | **RA:** {student_ra}  ")
        lines.append(f"**Responsável:** {guardian_name}  ")
        lines.append(f"**Confiança:** {conf} | **JID:** `{jid}` | **Último sinal:** {recv_at}  ")
        lines.append("")
        if text_block:
            lines.append(f"> {text_block}")
        else:
            lines.append("> *(sem texto capturado)*")
        lines.append("")

    # ── Alunos SEM resposta ───────────────────────────────────────────────────
    lines.append("---")
    lines.append("## Sem Resposta")
    lines.append("")
    lines.append("| RA | Aluno | Turma | Status Envio |")
    lines.append("|---|---|---|---|")

    no_reply_count = 0
    sorted_no_reply_students = []
    for skey, data in student_puzzle.items():
        if skey in responded_student_keys:
            continue
        std = data["student"]
        sname = safe_str(std.get("name") or "?")
        sorted_no_reply_students.append((sname, skey, data))

    sorted_no_reply_students.sort(key=lambda x: x[0])

    for sname, skey, data in sorted_no_reply_students:
        std = data["student"]
        sclass = safe_str(std.get("class_name") or "")
        sra = safe_str(std.get("ra") or "")
        
        success_msgs = [m for m in data["outbounds"] if m.get("status") in ["sent", "delivered", "read", "replied"]]
        if success_msgs:
            status = success_msgs[-1].get("status")
        else:
            status = data["outbounds"][0].get("status") if data["outbounds"] else "failed"
            
        lines.append(f"| {sra} | {sname} | {sclass} | {status} |")
        no_reply_count += 1

    lines.append("")
    lines.append(f"*Total sem resposta: {no_reply_count} alunos*")
    lines.append("")

    return "\n".join(lines)


def write_outputs(out_dir: Path, stem: str, markdown: str):
    out_dir.mkdir(parents=True, exist_ok=True)

    md_path = out_dir / f"{stem}.md"
    md_path.write_text(markdown, encoding="utf-8")
    print(f"[OK] Markdown: {md_path}")

    # CSV simples das linhas de "Sem Resposta"
    try:
        import csv
        csv_path = out_dir / f"{stem}_sem_resposta.csv"
        rows = []
        in_table = False
        for line in markdown.splitlines():
            if line.startswith("| RA |"):
                in_table = True
                continue
            if line.startswith("|---|"):
                continue
            if in_table:
                if not line.startswith("|"):
                    break
                parts = [p.strip() for p in line.split("|")[1:-1]]
                rows.append(parts)
        with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["RA", "Aluno", "Turma", "Status Envio"])
            writer.writerows(rows)
        print(f"[OK] CSV sem resposta: {csv_path}")
    except Exception as e:
        print(f"[WARN] CSV: {e}")

    # Excel
    try:
        import openpyxl
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.title = "Sem Resposta"
        ws.append(["RA", "Aluno", "Turma", "Status Envio"])
        rows_plain = []
        in_table = False
        for line in markdown.splitlines():
            if line.startswith("| RA |"):
                in_table = True
                continue
            if line.startswith("|---|"):
                continue
            if in_table:
                if not line.startswith("|"):
                    break
                parts = [p.strip() for p in line.split("|")[1:-1]]
                ws.append(parts)
        xl_path = out_dir / f"{stem}.xlsx"
        wb.save(xl_path)
        print(f"[OK] Excel: {xl_path}")
    except ImportError:
        print("[WARN] openpyxl não instalado, excel ignorado.")
    except Exception as e:
        print(f"[WARN] Excel: {e}")


def main():
    ap = argparse.ArgumentParser(description="Relatório completo de campanha")
    ap.add_argument("--campaign-id", required=True, help="UUID da campanha")
    ap.add_argument("--out-dir", default="relatorios/campanhas_v2", help="Diretório de saída")
    args = ap.parse_args()

    client = make_client()
    print(f"[...] Gerando relatório para campanha {args.campaign_id}")
    markdown = build_report(client, args.campaign_id)

    out_dir = Path(args.out_dir)
    camp_date = datetime.now().strftime("%d_%m_%Y")
    campaign_ids = _parse_campaign_ids(args.campaign_id)
    camp_short = campaign_ids[0][:8] if len(campaign_ids) == 1 else f"{campaign_ids[0][:8]}_combined"
    stem = f"relatorio_completo_{camp_date}_{camp_short}"
    write_outputs(out_dir, stem, markdown)


if __name__ == "__main__":
    main()

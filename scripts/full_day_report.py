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
    return create_client(url, key, options=ClientOptions(schema="busca_ativa_v2"))


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
    campaign_ids = _parse_campaign_ids(campaign_id)
    campaign = fetch_campaign(client, campaign_id)
    school_id = campaign["school_id"]
    absence_days = campaign.get("absence_days", "")
    if len(campaign_ids) > 1:
        camp_name = f"{campaign.get('name', campaign_ids[0][:8])} + Follow-up"
    else:
        camp_name = campaign.get("name", campaign_ids[0][:8])

    # Parse campaign date
    created = campaign.get("created_at", "")
    camp_date = created[:10] if created else "????-??-??"
    next_date = ""
    try:
        d = datetime.fromisoformat(created.replace("Z", "+00:00"))
        from datetime import timedelta
        next_d = d + timedelta(days=1)
        next_date = next_d.strftime("%Y-%m-%d")
    except Exception:
        pass

    messages = fetch_messages(client, campaign_id)
    
    # Deduplicate outbound messages by student_id to ensure unique students
    unique_messages = {}
    for m in messages:
        sid = m.get("student_id")
        if not sid:
            continue
        if sid not in unique_messages:
            unique_messages[sid] = m
        else:
            # Prefer successful sent statuses over failed
            curr_status = unique_messages[sid].get("status")
            new_status = m.get("status")
            if curr_status == "failed" and new_status != "failed":
                unique_messages[sid] = m
            elif curr_status != "failed" and new_status == "failed":
                pass
            else:
                curr_sent = unique_messages[sid].get("sent_at") or ""
                new_sent = m.get("sent_at") or ""
                if new_sent > curr_sent:
                    unique_messages[sid] = m
    messages = list(unique_messages.values())

    responses = fetch_responses(client, campaign_id)

    # Also fetch late replies (next day)
    if next_date:
        late = fetch_next_day_responses(client, school_id, campaign_id, next_date)
        # Avoid duplicates
        existing_ids = {r["id"] for r in responses}
        for r in late:
            if r["id"] not in existing_ids:
                responses.append(r)

    # Collect all IDs to bulk-fetch
    all_student_ids = list({m["student_id"] for m in messages if m.get("student_id")} |
                           {r["student_id"] for r in responses if r.get("student_id")})
    all_guardian_ids = list({m["guardian_id"] for m in messages if m.get("guardian_id")} |
                            {r["guardian_id"] for r in responses if r.get("guardian_id")})

    students_map = fetch_students(client, all_student_ids)
    guardians_map = fetch_guardians(client, all_guardian_ids)
    phone_id_map = fetch_phone_identity_map(client, school_id)

    # Group responses by student_id (best) or by sender_jid (fallback)
    # Key = student_id if known, else sender_jid
    resp_by_student: dict[str, list] = {}
    for resp in responses:
        key = resp.get("student_id") or resp.get("sender_jid") or "unknown"
        resp_by_student.setdefault(key, []).append(resp)

    # For messages without a response linked, attempt to link via phone_identity_map
    # by wa_jid -> guardian -> student
    guardian_to_student: dict[str, str] = {}
    for msg in messages:
        g = msg.get("guardian_id")
        s = msg.get("student_id")
        if g and s:
            guardian_to_student[g] = s

    # Enrich unresolved responses with phone_identity_map
    for resp in responses:
        if not resp.get("student_id") and resp.get("sender_jid"):
            g_id = phone_id_map.get(resp["sender_jid"])
            if g_id:
                s_id = guardian_to_student.get(g_id)
                if s_id:
                    resp["_inferred_student_id"] = s_id
                    resp["_inferred_guardian_id"] = g_id

    # ── Build per-student blocks ──────────────────────────────────────────────
    lines = []
    lines.append(f"# Relatório Operacional — {camp_name}")
    lines.append(f"**Data da campanha:** {camp_date}  ")
    lines.append(f"**Dia(s) de falta:** {safe_str(absence_days)}  ")
    lines.append(f"**ID da campanha:** `{', '.join(campaign_ids)}`  ")
    lines.append(f"**Gerado em:** {datetime.now().strftime('%d/%m/%Y %H:%M')}  ")
    lines.append("")

    # Summary stats
    total = len(messages)
    sent = sum(1 for m in messages if m.get("status") in ("sent", "delivered", "read"))
    failed = sum(1 for m in messages if m.get("status") == "failed")
    with_resp = len({r.get("student_id") or r.get("sender_jid") for r in responses})
    high_conf = sum(1 for r in responses if r.get("identity_confidence") == "HIGH")
    unresolved = sum(1 for r in responses if r.get("identity_confidence") == "UNRESOLVED")

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

    responded_student_ids = set()

    # Group responses by sender for the report display
    grouped_resp: dict[str, dict] = {}
    for resp in responses:
        jid = resp.get("sender_jid", "unknown")
        if jid not in grouped_resp:
            sid = resp.get("student_id") or resp.get("_inferred_student_id")
            gid = resp.get("guardian_id") or resp.get("_inferred_guardian_id")
            grouped_resp[jid] = {
                "jid": jid,
                "student_id": sid,
                "guardian_id": gid,
                "confidence": resp.get("identity_confidence", "UNRESOLVED"),
                "texts": [],
                "received_at": resp.get("received_at")
            }
        
        # Update confidence to the highest one found for this sender
        current_conf = resp.get("identity_confidence", "UNRESOLVED")
        if CONFIDENCE_ORDER.get(current_conf, 9) < CONFIDENCE_ORDER.get(grouped_resp[jid]["confidence"], 9):
            grouped_resp[jid]["confidence"] = current_conf
            # Also update IDs if they were missing
            if not grouped_resp[jid]["student_id"]:
                grouped_resp[jid]["student_id"] = resp.get("student_id") or resp.get("_inferred_student_id")
            if not grouped_resp[jid]["guardian_id"]:
                grouped_resp[jid]["guardian_id"] = resp.get("guardian_id") or resp.get("_inferred_guardian_id")

        txt = safe_str(resp.get("body") or resp.get("reason") or "").strip()
        if txt:
            grouped_resp[jid]["texts"].append(txt)

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

        if sid:
            responded_student_ids.add(sid)

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
    for msg in sorted(messages, key=lambda m: safe_str(students_map.get(m.get("student_id", ""), {}).get("class_name", ""))):
        sid = msg.get("student_id")
        if sid and sid in responded_student_ids:
            continue
        student = students_map.get(sid, {}) if sid else {}
        sname = safe_str(student.get("name") or sid or "?")
        sclass = safe_str(student.get("class_name") or "")
        sra = safe_str(student.get("ra") or "")
        status = safe_str(msg.get("status") or "?")
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

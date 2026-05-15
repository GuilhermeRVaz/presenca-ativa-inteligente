from __future__ import annotations

import argparse
import csv
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import settings
from app.infrastructure.supabase.repositories import SupabaseRepository


DEFAULT_LEGACY_REPORT = Path(
    r"C:\Users\user\buscaativadecia\exports_whatsapp"
    r"\Campanha_Diaria_2026_05_12_dia_12\RELATORIO_JUSTIFICATIVAS_DIA_12.txt"
)


@dataclass(frozen=True)
class LegacyEntry:
    ordem: int
    aluno: str
    turma: str
    ra: str
    status_carga: str
    status_resposta: str
    categoria: str
    justificativa: str
    arquivo: str


def normalize_text(value: str | None) -> str:
    text = str(value or "")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.upper()
    text = re.sub(r"[^A-Z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_ra(value: str | None) -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    digits = digits.lstrip("0")
    if len(digits) > 9:
        digits = digits[:-1]
    return digits


def parse_legacy_report(path: Path) -> list[LegacyEntry]:
    if not path.exists():
        return []

    entries: list[LegacyEntry] = []
    current: dict[str, str] | None = None
    header_re = re.compile(r"^\[(?P<ordem>\d+)\]\s+(?P<aluno>.+)$")

    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.rstrip()
        match = header_re.match(line)
        if match:
            if current:
                entries.append(_legacy_entry(current))
            current = {
                "ordem": match.group("ordem"),
                "aluno": match.group("aluno").strip(),
            }
            continue
        if current is None or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = normalize_text(key)
        current[key] = value.strip()

    if current:
        entries.append(_legacy_entry(current))
    return entries


def _legacy_entry(data: dict[str, str]) -> LegacyEntry:
    return LegacyEntry(
        ordem=int(data.get("ordem", "0")),
        aluno=data.get("aluno", ""),
        turma=data.get("TURMA", ""),
        ra=data.get("RA", ""),
        status_carga=data.get("STATUS CARGA", ""),
        status_resposta=data.get("STATUS RESPOSTA", ""),
        categoria=data.get("CATEGORIA", ""),
        justificativa=data.get("JUSTIFICATIVA", ""),
        arquivo=data.get("ARQUIVO", ""),
    )


def pct(part: int, total: int) -> str:
    if total <= 0:
        return "0.0%"
    return f"{part / total * 100:.1f}%"


def fetch_all(query: Any, *, page_size: int = 1000) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    start = 0
    while True:
        page = query.range(start, start + page_size - 1).execute().data or []
        rows.extend(page)
        if len(page) < page_size:
            return rows
        start += page_size


def day_range(date_text: str) -> tuple[str, str]:
    date_value = datetime.strptime(date_text, "%Y-%m-%d").date()
    start = datetime.combine(date_value, datetime.min.time()).replace(tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    return start.isoformat(), end.isoformat()


def load_campaign_data(client: Any, campaign_id: str, school_id: str, date_text: str) -> dict[str, Any]:
    start_iso, end_iso = day_range(date_text)

    campaign_rows = (
        client.table("campaigns")
        .select("id,name,status,absence_days,created_at,updated_at,total_sent,total_replied")
        .eq("id", campaign_id)
        .eq("school_id", school_id)
        .limit(1)
        .execute()
        .data
        or []
    )

    messages = fetch_all(
        client.table("messages")
        .select(
            "id,school_id,campaign_id,student_id,guardian_id,tracking_ref,evolution_msg_id,"
            "wa_jid,template_id,body_preview,status,sent_at,created_at,"
            "students(id,ra,name,class_name),"
            "guardians(id,name,phone_e164,wa_jid)"
        )
        .eq("campaign_id", campaign_id)
        .eq("school_id", school_id)
        .order("created_at")
    )

    responses = fetch_all(
        client.table("responses")
        .select(
            "id,message_id,school_id,guardian_id,campaign_id,student_id,raw_message_id,"
            "sender_jid,body,identity_confidence,classified,reason,ai_confidence,"
            "is_ack,needs_review,received_at,created_at,"
            "students(id,ra,name,class_name),"
            "guardians(id,name,phone_e164,wa_jid)"
        )
        .eq("school_id", school_id)
        .eq("campaign_id", campaign_id)
        .order("received_at")
    )

    raw_inbound_day = fetch_all(
        client.table("raw_inbound")
        .select("id,school_id,message_id,sender_jid,processed,processing_error,received_at")
        .eq("school_id", school_id)
        .gte("received_at", start_iso)
        .lt("received_at", end_iso)
        .order("received_at")
    )

    sender_jids = sorted({row.get("sender_jid") for row in responses if row.get("sender_jid")})
    sessions: list[dict[str, Any]] = []
    phone_maps: list[dict[str, Any]] = []
    for sender in sender_jids:
        sessions.extend(
            client.table("conversation_sessions")
            .select("*")
            .eq("school_id", school_id)
            .eq("sender_jid", sender)
            .execute()
            .data
            or []
        )
        query = client.table("phone_identity_map").select("*").eq("school_id", school_id)
        if str(sender).endswith("@lid"):
            query = query.eq("lid_jid", sender)
        else:
            query = query.eq("wa_jid", sender)
        phone_maps.extend(query.execute().data or [])

    response_raw_ids = [row.get("raw_message_id") for row in responses if row.get("raw_message_id")]
    raw_for_responses: list[dict[str, Any]] = []
    for raw_id in response_raw_ids:
        raw_for_responses.extend(
            client.table("raw_inbound")
            .select("id,school_id,message_id,sender_jid,processed,processing_error,received_at")
            .eq("message_id", raw_id)
            .execute()
            .data
            or []
        )

    return {
        "campaign": campaign_rows[0] if campaign_rows else None,
        "messages": messages,
        "responses": responses,
        "raw_inbound_day": raw_inbound_day,
        "sessions": sessions,
        "phone_maps": phone_maps,
        "raw_for_responses": raw_for_responses,
    }


def build_audit(
    *,
    campaign_id: str,
    school_id: str,
    date_text: str,
    legacy_entries: list[LegacyEntry],
    data: dict[str, Any],
) -> tuple[str, list[dict[str, Any]]]:
    campaign = data["campaign"]
    messages = data["messages"]
    responses = data["responses"]
    raw_inbound_day = data["raw_inbound_day"]
    sessions = data["sessions"]
    phone_maps = data["phone_maps"]
    raw_for_responses = data["raw_for_responses"]

    message_by_student_ra = {
        normalize_ra(((msg.get("students") or {}).get("ra"))): msg
        for msg in messages
        if msg.get("students")
    }
    responses_by_student_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for response in responses:
        if response.get("student_id"):
            responses_by_student_id[str(response["student_id"])].append(response)

    raw_ids = {row.get("message_id") for row in raw_for_responses}
    session_senders = {row.get("sender_jid") for row in sessions}
    phone_map_senders = {row.get("lid_jid") or row.get("wa_jid") for row in phone_maps}
    response_sender_counts = Counter(row.get("sender_jid") for row in responses if row.get("sender_jid"))

    identified = [r for r in responses if r.get("guardian_id") and r.get("student_id") and r.get("campaign_id")]
    unresolved = [r for r in responses if r.get("identity_confidence") == "UNRESOLVED"]
    without_campaign = [r for r in responses if not r.get("campaign_id")]
    without_guardian = [r for r in responses if not r.get("guardian_id")]
    without_student = [r for r in responses if not r.get("student_id")]
    without_raw = [r for r in responses if r.get("raw_message_id") not in raw_ids]
    without_session = [r for r in responses if r.get("sender_jid") not in session_senders]
    with_phone_map = [r for r in responses if r.get("sender_jid") in phone_map_senders]
    repeated_sender_responses = sum(count for count in response_sender_counts.values() if count > 1)

    legacy_enqueued = [entry for entry in legacy_entries if entry.status_carga == "ENFILEIRADO"]
    legacy_not_enqueued = [entry for entry in legacy_entries if entry.status_carga != "ENFILEIRADO"]
    legacy_with_response = [
        entry
        for entry in legacy_entries
        if entry.status_resposta in {"COM_RESPOSTA", "RESPOSTA_APENAS_MIDIA"}
    ]
    legacy_without_text = [
        entry
        for entry in legacy_entries
        if entry.status_resposta == "CONVERSA_EXPORTADA_SEM_RESPOSTA_TEXTUAL_POS_ENVIO"
    ]
    legacy_e2ee = [
        entry
        for entry in legacy_entries
        if entry.status_resposta == "SEM_CONVERSA_EXPORTADA_PROVAVEL_E2EE"
    ]

    rows_for_csv: list[dict[str, Any]] = []
    legacy_matched_messages = 0
    legacy_matched_responses = 0
    legacy_response_rows = []
    for entry in legacy_entries:
        ra = normalize_ra(entry.ra)
        msg = message_by_student_ra.get(ra)
        db_responses = responses_by_student_id.get(str(msg.get("student_id"))) if msg else []
        if msg:
            legacy_matched_messages += 1
        if db_responses:
            legacy_matched_responses += 1
        row = {
            "ordem": entry.ordem,
            "aluno_legacy": entry.aluno,
            "ra_legacy": entry.ra,
            "status_carga_legacy": entry.status_carga,
            "status_resposta_legacy": entry.status_resposta,
            "categoria_legacy": entry.categoria,
            "db_message_found": bool(msg),
            "db_message_status": msg.get("status") if msg else "",
            "db_student_id": msg.get("student_id") if msg else "",
            "db_guardian_id": msg.get("guardian_id") if msg else "",
            "db_response_count_for_student": len(db_responses or []),
            "db_response_confidences": ",".join(sorted({r.get("identity_confidence", "") for r in db_responses or []})),
        }
        rows_for_csv.append(row)
        if entry.status_resposta in {"COM_RESPOSTA", "RESPOSTA_APENAS_MIDIA"}:
            legacy_response_rows.append(row)

    status_counts = Counter(msg.get("status") or "NULL" for msg in messages)
    confidence_counts = Counter(resp.get("identity_confidence") or "NULL" for resp in responses)
    legacy_status_counts = Counter(entry.status_resposta for entry in legacy_entries)
    legacy_category_counts = Counter(entry.categoria for entry in legacy_entries)

    lines = [
        "# Auditoria Operacional da Campanha",
        "",
        f"- Campanha: {(campaign or {}).get('name', 'NAO_ENCONTRADA')}",
        f"- Campaign ID: {campaign_id}",
        f"- School ID: {school_id}",
        f"- Data auditada: {date_text}",
        "",
        "## 1. Base força-bruta usada como oráculo",
        "",
        f"- Faltosos preliminares: {len(legacy_entries)}",
        f"- Enfileirados: {len(legacy_enqueued)}",
        f"- Nao enfileirados: {len(legacy_not_enqueued)}",
        f"- Com resposta textual/mista ou midia: {len(legacy_with_response)}",
        f"- Conversa exportada sem resposta textual pos-envio: {len(legacy_without_text)}",
        f"- Sem conversa exportada/provavel E2EE: {len(legacy_e2ee)}",
        "",
        "Status legacy:",
        *[f"- {key}: {value}" for key, value in legacy_status_counts.most_common()],
        "",
        "Categorias legacy:",
        *[f"- {key}: {value}" for key, value in legacy_category_counts.most_common()],
        "",
        "## 2. Banco de dados atual",
        "",
        f"- Mensagens outbound da campanha: {len(messages)}",
        *[f"- messages.status={key}: {value}" for key, value in sorted(status_counts.items())],
        f"- Responses vinculadas a campaign_id: {len(responses)}",
        *[f"- responses.identity_confidence={key}: {value}" for key, value in sorted(confidence_counts.items())],
        f"- Raw inbound no dia {date_text}: {len(raw_inbound_day)}",
        f"- Conversation sessions para senders das responses: {len(sessions)}",
        f"- Phone identity map hits para senders das responses: {len(phone_maps)}",
        "",
        "## 3. Matriz de eficacia do pipeline minimo",
        "",
        "| Metrica | Resultado | Taxa |",
        "| --- | ---: | ---: |",
        f"| Responses com raw_inbound correspondente | {len(responses) - len(without_raw)}/{len(responses)} | {pct(len(responses) - len(without_raw), len(responses))} |",
        f"| Responses com session correspondente | {len(responses) - len(without_session)}/{len(responses)} | {pct(len(responses) - len(without_session), len(responses))} |",
        f"| Responses com campaign_id | {len(responses) - len(without_campaign)}/{len(responses)} | {pct(len(responses) - len(without_campaign), len(responses))} |",
        f"| Responses com guardian_id | {len(responses) - len(without_guardian)}/{len(responses)} | {pct(len(responses) - len(without_guardian), len(responses))} |",
        f"| Responses com student_id | {len(responses) - len(without_student)}/{len(responses)} | {pct(len(responses) - len(without_student), len(responses))} |",
        f"| Responses totalmente identificadas | {len(identified)}/{len(responses)} | {pct(len(identified), len(responses))} |",
        f"| Responses UNRESOLVED | {len(unresolved)}/{len(responses)} | {pct(len(unresolved), len(responses))} |",
        f"| Responses com phone_identity_map | {len(with_phone_map)}/{len(responses)} | {pct(len(with_phone_map), len(responses))} |",
        f"| Responses de senders repetidos | {repeated_sender_responses}/{len(responses)} | {pct(repeated_sender_responses, len(responses))} |",
        "",
        "## 4. Comparacao legacy x banco",
        "",
        "| Metrica | Resultado | Taxa |",
        "| --- | ---: | ---: |",
        f"| Alunos legacy encontrados em messages da campanha | {legacy_matched_messages}/{len(legacy_entries)} | {pct(legacy_matched_messages, len(legacy_entries))} |",
        f"| Alunos enfileirados legacy encontrados em messages | {sum(1 for e in legacy_enqueued if message_by_student_ra.get(normalize_ra(e.ra)))}/{len(legacy_enqueued)} | {pct(sum(1 for e in legacy_enqueued if message_by_student_ra.get(normalize_ra(e.ra))), len(legacy_enqueued))} |",
        f"| Alunos legacy com alguma response vinculada no banco | {legacy_matched_responses}/{len(legacy_entries)} | {pct(legacy_matched_responses, len(legacy_entries))} |",
        f"| Casos COM_RESPOSTA legacy com response vinculada | {sum(1 for r in legacy_response_rows if r['db_response_count_for_student'])}/{len(legacy_with_response)} | {pct(sum(1 for r in legacy_response_rows if r['db_response_count_for_student']), len(legacy_with_response))} |",
        "",
        "## 5. Falhas operacionais a auditar primeiro",
        "",
        f"- Responses sem raw_inbound: {len(without_raw)}",
        f"- Responses sem session: {len(without_session)}",
        f"- Responses sem guardian_id: {len(without_guardian)}",
        f"- Responses sem student_id: {len(without_student)}",
        f"- Responses sem campaign_id: {len(without_campaign)}",
        f"- Responses UNRESOLVED: {len(unresolved)}",
        "",
        "## 6. Amostra para auditoria humana",
        "",
    ]

    sample = sorted(
        responses,
        key=lambda r: (
            0 if r.get("identity_confidence") == "UNRESOLVED" else 1,
            str(r.get("received_at") or ""),
        ),
    )[:20]
    if not sample:
        lines.append("- Nenhuma response vinculada a esta campanha no banco.")
    for idx, response in enumerate(sample, 1):
        student = response.get("students") or {}
        guardian = response.get("guardians") or {}
        body = re.sub(r"\s+", " ", str(response.get("body") or "")).strip()
        if len(body) > 180:
            body = body[:177] + "..."
        lines.append(
            f"{idx}. response={response.get('id')} | conf={response.get('identity_confidence')} | "
            f"sender={response.get('sender_jid')} | aluno={student.get('name') or 'SEM_ALUNO'} | "
            f"responsavel={guardian.get('name') or 'SEM_RESPONSAVEL'} | texto={body}"
        )

    return "\n".join(lines) + "\n", rows_for_csv


def main() -> int:
    parser = argparse.ArgumentParser(description="Audita o pipeline minimo de uma campanha real.")
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--date", required=True, help="Data da campanha em YYYY-MM-DD.")
    parser.add_argument("--school-id", default=settings.default_school_id)
    parser.add_argument("--legacy-report", type=Path, default=DEFAULT_LEGACY_REPORT)
    parser.add_argument("--out-dir", type=Path, default=ROOT_DIR / "relatorios" / "auditoria")
    args = parser.parse_args()

    load_dotenv(ROOT_DIR / ".env")
    if not args.school_id:
        raise SystemExit("DEFAULT_SCHOOL_ID nao configurado e --school-id nao informado.")

    repo = SupabaseRepository()
    client = repo.client.schema("busca_ativa_v2")

    legacy_entries = parse_legacy_report(args.legacy_report)
    data = load_campaign_data(client, args.campaign_id, args.school_id, args.date)
    report, csv_rows = build_audit(
        campaign_id=args.campaign_id,
        school_id=args.school_id,
        date_text=args.date,
        legacy_entries=legacy_entries,
        data=data,
    )

    args.out_dir.mkdir(parents=True, exist_ok=True)
    stamp = args.date.replace("-", "_")
    report_path = args.out_dir / f"audit_campaign_{stamp}_{args.campaign_id[:8]}.md"
    csv_path = args.out_dir / f"audit_campaign_{stamp}_{args.campaign_id[:8]}_legacy_compare.csv"
    report_path.write_text(report, encoding="utf-8")

    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        fieldnames = [
            "ordem",
            "aluno_legacy",
            "ra_legacy",
            "status_carga_legacy",
            "status_resposta_legacy",
            "categoria_legacy",
            "db_message_found",
            "db_message_status",
            "db_student_id",
            "db_guardian_id",
            "db_response_count_for_student",
            "db_response_confidences",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter=";")
        writer.writeheader()
        writer.writerows(csv_rows)

    print(report)
    print(f"Relatorio salvo em: {report_path}")
    print(f"Comparativo CSV salvo em: {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

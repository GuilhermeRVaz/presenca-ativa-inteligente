import openpyxl
from pathlib import Path
import re
import sys
import unicodedata
from collections import defaultdict
from difflib import SequenceMatcher
from datetime import datetime, timezone

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from app.core.config import settings
from app.infrastructure.supabase.repositories import SupabaseRepository

def normalize_name(name: str) -> str:
    if not name:
        return ""
    text = unicodedata.normalize("NFKD", name)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.upper()
    text = re.sub(r"[^A-Z\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()

def normalize_ra(raw_ra: str) -> str:
    if not raw_ra:
        return ""
    digits = re.sub(r"[^0-9]", "", raw_ra)
    digits = digits.lstrip("0")
    if len(digits) > 9:
        digits = digits[:-1]
    return digits

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Create June/July Bolsa Família justification campaign.")
    parser.add_argument("--dry-run", action="store_true", help="Simulate campaign creation without writing to database.")
    args = parser.parse_args()

    print("Initializing Supabase Database Connection...")
    repo = SupabaseRepository()
    client = repo.client.schema("busca_ativa_v2")
    school_id = settings.default_school_id

    jj_dir = ROOT_DIR / "presencaeausenciasjunhojulho"
    files = list(jj_dir.glob("RELATORIO_FREQUENCIA_*.xlsx"))

    # 1. Parse Excel data
    print("Parsing June/July attendance files...")
    excel_data = defaultdict(lambda: defaultdict(lambda: defaultdict(dict)))

    for f in sorted(files, key=lambda p: p.name):
        wb = openpyxl.load_workbook(f, read_only=True, data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        wb.close()
        
        if len(rows) < 9:
            continue
            
        month = str(rows[2][0] or "").strip()
        doc_type = str(rows[3][0] or "").strip()
        turma_raw = str(rows[7][0] or "").strip()
        turma = turma_raw.replace("Turma:", "").strip() if "Turma:" in turma_raw else turma_raw
        
        header = rows[8]
        col_nome = 1
        col_ra = 2
        col_total = len(header) - 1
        
        for r in rows[9:]:
            if not r or len(r) < 3 or r[0] is None or not isinstance(r[0], int):
                continue
                
            nome_raw = str(r[col_nome] or "").strip()
            ra_raw = str(r[col_ra] or "").strip()
            total_val = r[col_total]
            
            if not nome_raw:
                continue
                
            nome_norm = normalize_name(nome_raw)
            days_data = {}
            for d in range(1, 32):
                col_idx = 2 + d
                if col_idx < len(r) - 1:
                    val = r[col_idx]
                    if val is not None and val != "-":
                        days_data[d] = int(val)
                        
            norm_doc_type = "Presenças" if "Presen" in doc_type else "Faltas"
            
            excel_data[month][norm_doc_type][turma][nome_norm] = {
                "nome_original": nome_raw,
                "ra": ra_raw,
                "days": days_data,
                "total": int(total_val or 0)
            }

    # 2. Read students from BFjunhojulho.md
    bf_md_path = jj_dir / "BFjunhojulho.md"
    content = bf_md_path.read_text(encoding="utf-8")
    student_blocks = re.findall(r"(###\s+([^\n]+)\n(.*?))(?=###|\Z)", content, re.DOTALL)
    
    infrequent_students = []
    
    for full_block, s_name, block_body in student_blocks:
        s_name_clean = s_name.strip()
        nome_norm = normalize_name(s_name_clean)
        
        serie_match = re.search(r"-\s*\*\*Série:\*\*\s*(.*)", block_body)
        serie = serie_match.group(1).strip() if serie_match else "Ensino Fundamental"
        threshold = 60.0 if "Infantil" in serie or "Creche" in serie or "Pré" in serie else 75.0
        
        m_reports = {}
        matched_ra = None
        matched_turma_raw = None
        
        for month in ["Junho", "Julho"]:
            presences = None
            absences = None
            abs_days = []
            matched_turma = None
            
            if month in excel_data:
                for t in excel_data[month]["Presenças"]:
                    for ex_nome_norm, ex_student in excel_data[month]["Presenças"][t].items():
                        ratio = SequenceMatcher(None, nome_norm, ex_nome_norm).ratio()
                        if ratio >= 0.85 or nome_norm in ex_nome_norm or ex_nome_norm in nome_norm:
                            presences = ex_student["total"]
                            matched_ra = ex_student["ra"]
                            matched_turma = t
                            break
                            
                for t in excel_data[month]["Faltas"]:
                    for ex_nome_norm, ex_student in excel_data[month]["Faltas"][t].items():
                        ratio = SequenceMatcher(None, nome_norm, ex_nome_norm).ratio()
                        if ratio >= 0.85 or nome_norm in ex_nome_norm or ex_nome_norm in nome_norm:
                            absences = ex_student["total"]
                            abs_days = sorted(ex_student["days"].keys())
                            break
            
            m_reports[month] = {
                "presences": presences,
                "absences": absences,
                "abs_days": abs_days,
                "turma": matched_turma
            }
            if matched_turma:
                matched_turma_raw = matched_turma
                
        is_infrequent = False
        infrequent_months = []
        
        for month in ["Junho", "Julho"]:
            rep = m_reports[month]
            if rep["presences"] is not None and rep["absences"] is not None:
                total_cls = rep["presences"] + rep["absences"]
                freq = (rep["presences"] / total_cls) * 100 if total_cls > 0 else 100.0
                if freq < threshold:
                    is_infrequent = True
                    infrequent_months.append((month, freq, rep["abs_days"]))
            elif rep["absences"] is not None and rep["absences"] > 0 and (rep["presences"] is None or rep["presences"] == 0):
                is_infrequent = True
                infrequent_months.append((month, 0.0, rep["abs_days"]))
                
        if is_infrequent and matched_ra:
            infrequent_students.append({
                "name": s_name_clean,
                "ra": matched_ra,
                "turma": matched_turma_raw,
                "months": infrequent_months
            })

    print(f"\nFound {len(infrequent_students)} infrequent students below threshold for June/July:")
    for s in infrequent_students[:10]:
        months_str = ", ".join(f"{m} ({f:.1f}%)" for m, f, _ in s["months"])
        print(f"  - {s['name']} | Turma: {s['turma']} | {months_str}")

    # 3. Create Campaign in Database
    campaign_name = "Campanha Bolsa Família — Justificativas Junho/Julho 2026"

    if args.dry_run:
        campaign_id = "dry-run-campaign-jj"
        print(f"\n[DRY RUN] Would create campaign: {campaign_name}")
    else:
        existing = client.table("campaigns").select("id").eq("school_id", school_id).eq("name", campaign_name).limit(1).execute().data
        if existing:
            campaign_id = existing[0]["id"]
            print(f"\nCampaign already exists: {campaign_name} ({campaign_id})")
        else:
            campaign_data = {
                "school_id": school_id,
                "name": campaign_name,
                "type": "absence",
                "campaign_type": "manual",
                "status": "draft",
                "absence_days": "Junho/Julho 2026",
                "total_sent": 0,
                "total_failed": 0
            }
            res = client.table("campaigns").insert(campaign_data).execute()
            if not res.data:
                raise RuntimeError("Failed to create campaign in database.")
            campaign_id = res.data[0]["id"]
            print(f"\nCampaign created successfully: {campaign_name} ({campaign_id})")

    # 4. Enqueue messages
    enqueued_count = 0

    for idx, s in enumerate(infrequent_students, 1):
        clean_ra = normalize_ra(s["ra"])
        
        db_std = client.table("students").select("id").eq("ra", clean_ra).limit(1).execute().data
        if not db_std:
            # Fallback search by fuzzy name
            all_stds = client.table("students").select("id, name, ra").execute().data or []
            s_norm = normalize_name(s["name"])
            matched_id = None
            for db_s in all_stds:
                if SequenceMatcher(None, s_norm, normalize_name(db_s.get("name", ""))).ratio() >= 0.85:
                    matched_id = db_s["id"]
                    break
            if matched_id:
                student_id = matched_id
            else:
                print(f"  [{idx}/{len(infrequent_students)}] Student not found in DB: {s['name']} | RA: {s['ra']}")
                continue
        else:
            student_id = db_std[0]["id"]

        # Resolve primary guardian
        guardian_res = (
            client.table("student_guardians")
            .select("guardian_id, guardians(id, name, phone_e164, wa_jid)")
            .eq("student_id", student_id)
            .eq("is_primary", True)
            .limit(1)
            .execute()
        )
        
        if not guardian_res.data or not guardian_res.data[0].get("guardians"):
            print(f"  [{idx}/{len(infrequent_students)}] Primary guardian not found for: {s['name']}")
            continue
            
        guardian = guardian_res.data[0]["guardians"]
        guardian_id = guardian["id"]
        wa_jid = guardian.get("wa_jid")
        guardian_name = guardian.get("name", "Responsável")

        # Query existing responses
        db_resps = client.table("responses").select("*").eq("student_id", student_id).execute().data or []
        db_just_days = defaultdict(list)
        for resp in db_resps:
            rx_at = resp.get("received_at")
            if rx_at:
                m_date = re.search(r"-(\d{2})-(\d{2})", rx_at)
                if m_date:
                    mn, dy = int(m_date.group(1)), int(m_date.group(2))
                    resp_month = "Junho" if mn == 6 else ("Julho" if mn == 7 else None)
                    if resp_month:
                        db_just_days[resp_month].append(dy)

        absence_details = []
        justification_details = []

        for m, f, abs_days in s["months"]:
            abs_days_str = ", ".join(map(str, abs_days))
            absence_details.append(f"{abs_days_str} de {m}")
            
            just_days = db_just_days.get(m, [])
            if just_days:
                just_days_str = ", ".join(map(str, sorted(just_days)))
                justification_details.append(f"{just_days_str} de {m}")

        absences_text = " e ".join(absence_details)
        justifications_text = " e ".join(justification_details) if justification_details else "nenhuma registrada"

        turma_clean = re.sub(r"[^a-zA-Z0-9\s]", "", s["turma"])
        m_t = re.search(r"(\d)\s*Ano\s*(\d[A-Z])", turma_clean, re.IGNORECASE)
        pretty_turma = f"{m_t.group(1)}º Ano {m_t.group(2)[1]}" if m_t else s["turma"]

        custom_message = (
            f"Olá {guardian_name}, a escola Décia está realizando o levantamento de informações para "
            f"fornecer o relatório de frequência com motivos e justificativas de ausências que será "
            f"enviado ao responsável do programa Bolsa Família referentes aos meses de Junho e Julho.\n\n"
            f"Notamos que o(a) aluno(a) *{s['name']}*, da turma *{pretty_turma}*, esteve abaixo do limite "
            f"de presença regulamentar.\n"
            f"• Dias com faltas: {absences_text}\n"
            f"• Justificativas registradas via busca ativa: {justifications_text}\n\n"
            f"Ressaltamos que essas faltas impactam diretamente no relatório de frequência do Programa Bolsa Família e na manutenção do benefício.\n\n"
            f"Por favor, responda a esta mensagem informando o motivo dessas ausências. Caso possua atestado médico ou comprovante, você pode nos enviar uma foto do documento diretamente por aqui pelo WhatsApp."
        )

        tracking_ref = f"BFJJ{campaign_id[:6]}-STU{student_id[:8]}"

        metadata = {
            "turma": s["turma"],
            "data_falta": absences_text,
            "ra": s["ra"],
            "nome_excel": s["name"],
            "guardian_name": guardian_name,
            "guardian_phone": guardian.get("phone_e164", ""),
            "custom_message": custom_message
        }

        if args.dry_run:
            print(f"  [DRY RUN] Would enqueue message for {s['name']} ({guardian_name})")
            enqueued_count += 1
        else:
            msg_exist = client.table("messages").select("id").eq("campaign_id", campaign_id).eq("student_id", student_id).limit(1).execute().data
            if msg_exist:
                continue
                
            row = {
                "school_id": school_id,
                "campaign_id": campaign_id,
                "student_id": student_id,
                "guardian_id": guardian_id,
                "tracking_ref": tracking_ref,
                "wa_jid": wa_jid,
                "template_id": "bolsa_familia_custom",
                "status": "pending",
                "metadata": metadata
            }
            msg_res = client.table("messages").insert(row).execute()
            if not msg_res.data:
                raise RuntimeError(f"Failed to enqueue message for {s['name']}")
            print(f"  [OK] Enqueued message for: {s['name']} | Responsável: {guardian_name}")
            enqueued_count += 1

    print(f"\n============================================================")
    print(f"  Summary: {enqueued_count} messages prepared for campaign ID {campaign_id}")
    if not args.dry_run and enqueued_count > 0:
        print(f"\n  To execute and send this campaign to parents via WhatsApp, run:")
        print(f"  .venv\\Scripts\\python.exe scripts/campaign_orchestrator.py --campaign-id {campaign_id}")
    print(f"============================================================\n")

if __name__ == "__main__":
    main()

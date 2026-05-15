"""
campaign_loader.py — Fase 1: Preparação e Carga da Campanha de Busca Ativa

Responsabilidades:
  1. Ler o Relatorio_Consolidado_BuscaAtiva.xlsx
  2. Identificar os alunos faltosos para o dia solicitado (coluna = número do dia)
  3. Criar um registro de Campanha na tabela busca_ativa_v2.campaigns (status='draft')
  4. Resolver o UUID de cada aluno faltoso via RA (fallback: nome)
  5. Popular a fila (busca_ativa_v2.messages) com status='pending'
  6. NENHUM disparo ocorre aqui — apenas preparação da fila.

Uso:
  python scripts/campaign_loader.py --day 4
  python scripts/campaign_loader.py --day 4 --month 5 --report relatorios/Relatorio_Consolidado_BuscaAtiva.xlsx
  python scripts/campaign_loader.py --day 4 --dry-run   # Simula sem gravar no banco
"""

import argparse
import hashlib
import sys
import json
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

# ─── Bootstrap do path para importar módulos do projeto ─────────────────────
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.config import settings
from app.core.logging import logger

# ─── Constantes ──────────────────────────────────────────────────────────────

# Colunas mínimas esperadas no Excel consolidado
REQUIRED_COLS = {"RA", "NOME"}


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _is_absence(val) -> bool:
    """
    Define se um valor na coluna do dia representa uma falta.
    Regras:
      - Não nulo/vazio
      - Não é '0' nem 'C' (Comparecimento)
      - É um número > 0 (ex: quantidade de aulas)
      - É a string 'F' ou 'FALTA'
    """
    s = str(val).strip().upper()
    
    # Casos de presença ou vazio
    if s in ("", "NAN", "NONE", "0", "C", "COMPARECIMENTO"):
        return False
        
    # Marcadores explícitos de falta
    if s in ("F", "FALTA"):
        return True
        
    # Tenta converter para número (ex: 1, 2, 9 aulas perdidas)
    try:
        num_val = float(s.replace(",", "."))
        return num_val > 0
    except ValueError:
        # Se não é número nem marcador conhecido, mas tem conteúdo,
        # por segurança para escola integral, vamos considerar falta? 
        # O usuário pediu especificamente: número > 0 ou 'F'/'FALTA'.
        return False

def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Normaliza cabeçalhos: sem espaços, maiúsculas."""
    df.columns = [str(c).strip().upper() for c in df.columns]
    return df


def _find_day_column(df: pd.DataFrame, day: int) -> str:
    """
    Localiza a coluna do dia no DataFrame.
    Suporta formatos: '4', '04', '04/05', '04/05/2026', etc.
    Retorna o nome exato da coluna ou lança ValueError.
    """
    day_str = str(day)
    day_padded = day_str.zfill(2)
    for col in df.columns:
        col_clean = col.strip().upper()
        # Match exato simples
        if col_clean == day_str or col_clean == day_padded:
            return col
        # Match se a coluna começa com o número do dia seguido de separador
        if col_clean.startswith(day_padded + "/") or col_clean.startswith(day_str + "/"):
            return col
    raise ValueError(
        f"Coluna do dia '{day}' não encontrada. Colunas disponíveis:\n"
        + ", ".join(df.columns.tolist())
    )


def _build_supabase_client():
    """Constrói o client Supabase usando o padrão do projeto."""
    if not settings.supabase_url or not settings.supabase_key:
        raise RuntimeError("SUPABASE_URL e SUPABASE_KEY devem estar configurados no .env")
    from supabase import create_client
    from supabase.lib.client_options import SyncClientOptions
    options = SyncClientOptions(postgrest_client_timeout=60.0)
    return create_client(settings.supabase_url, settings.supabase_key, options=options)


def _resolve_student_uuid(client, school_id: str, ra: str, name: str) -> str | None:
    """
    Resolve o UUID do aluno:
      1. Busca pelo RA (exato) — mais confiável
      2. Fallback por Nome exato
    Retorna None se não encontrado.
    """
    # Tentativa 1: por RA
    ra_clean = str(ra).strip()
    if ra_clean and ra_clean.lower() not in ("nan", "none", ""):
        res = (
            client.schema("busca_ativa_v2")
            .table("students")
            .select("id")
            .eq("school_id", school_id)
            .eq("ra", ra_clean)
            .limit(1)
            .execute()
        )
        if res.data:
            return str(res.data[0]["id"])

    # Tentativa 2: por Nome
    name_clean = str(name).strip()
    if name_clean and name_clean.lower() not in ("nan", "none", ""):
        res = (
            client.schema("busca_ativa_v2")
            .table("students")
            .select("id")
            .eq("school_id", school_id)
            .eq("name", name_clean)
            .limit(1)
            .execute()
        )
        if res.data:
            return str(res.data[0]["id"])

    return None


def _resolve_primary_guardian(client, student_id: str) -> dict | None:
    """Retorna o responsável principal (is_primary=True) vinculado ao aluno."""
    res = (
        client.schema("busca_ativa_v2")
        .table("student_guardians")
        .select("guardian_id, guardians(id, name, phone_e164, wa_jid)")
        .eq("student_id", student_id)
        .eq("is_primary", True)
        .limit(1)
        .execute()
    )
    if res.data and res.data[0].get("guardians"):
        return res.data[0]["guardians"]
    return None


def _create_campaign(client, school_id: str, day: int, month: int, year: int, total: int, dry_run: bool) -> str:
    """
    Cria a campanha no Supabase com status='draft'.
    Retorna o campaign_id (UUID).
    Se já existir uma campanha para o mesmo dia/mês/ano, reutiliza-a.
    """
    campaign_name = f"Busca Ativa — Faltas dia {day:02d}/{month:02d}/{year}"
    absence_days = f"{day:02d}/{month:02d}/{year}"

    if dry_run:
        fake_id = hashlib.md5(campaign_name.encode()).hexdigest()
        fake_uuid = f"{fake_id[:8]}-{fake_id[8:12]}-{fake_id[12:16]}-{fake_id[16:20]}-{fake_id[20:32]}"
        logger.info("dry_run: campanha NÃO criada no banco", name=campaign_name, fake_id=fake_uuid)
        return fake_uuid

    # Verifica se já existe para evitar duplicação
    existing = (
        client.schema("busca_ativa_v2")
        .table("campaigns")
        .select("id")
        .eq("school_id", school_id)
        .eq("name", campaign_name)
        .limit(1)
        .execute()
    )
    if existing.data:
        campaign_id = str(existing.data[0]["id"])
        logger.warning("Campanha já existente — reutilizando", campaign_id=campaign_id, name=campaign_name)
        return campaign_id

    res = (
        client.schema("busca_ativa_v2")
        .table("campaigns")
        .insert({
            "school_id": school_id,
            "name": campaign_name,
            "type": "absence",
            "absence_days": absence_days,
            "status": "draft",
            "total_sent": 0,
            "total_replied": 0,
        })
        .execute()
    )
    if not res.data:
        raise RuntimeError(f"Falha ao criar campanha: resposta vazia do Supabase")
    campaign_id = str(res.data[0]["id"])
    logger.info("Campanha criada", campaign_id=campaign_id, name=campaign_name)
    return campaign_id


def _enqueue_message(
    client,
    school_id: str,
    campaign_id: str,
    student_id: str,
    guardian_id: str,
    wa_jid: str | None,
    metadata: dict,
    dry_run: bool,
) -> str | None:
    """
    Insere uma mensagem na fila com status='pending'.
    Usa um tracking_ref determinístico para ser idempotente:
    se o aluno já foi enfileirado para esta campanha, o INSERT é ignorado.
    """
    tracking_ref = f"CMP{campaign_id[:8]}-STU{student_id[:8]}"

    if dry_run:
        logger.info(
            "dry_run: mensagem NÃO enfileirada",
            tracking_ref=tracking_ref,
            student_id=student_id,
            guardian_id=guardian_id,
        )
        return tracking_ref

    # Verifica idempotência: não duplicar
    existing = (
        client.schema("busca_ativa_v2")
        .table("messages")
        .select("id")
        .eq("campaign_id", campaign_id)
        .eq("student_id", student_id)
        .limit(1)
        .execute()
    )
    if existing.data:
        logger.warning(
            "Aluno já enfileirado — pulando",
            student_id=student_id,
            tracking_ref=tracking_ref,
        )
        return str(existing.data[0]["id"])

    row = {
        "school_id": school_id,
        "campaign_id": campaign_id,
        "student_id": student_id,
        "guardian_id": guardian_id,
        "tracking_ref": tracking_ref,
        "wa_jid": wa_jid,
        "template_id": "busca_ativa_v1",
        "status": "pending",
        "metadata": metadata,
    }

    res = (
        client.schema("busca_ativa_v2")
        .table("messages")
        .insert(row)
        .execute()
    )
    if not res.data:
        raise RuntimeError(f"Falha ao enfileirar mensagem para student_id={student_id}")
    return str(res.data[0]["id"])


# ─── Função principal ─────────────────────────────────────────────────────────

def load_campaign(
    report_path: str,
    day: int,
    month: int | None = None,
    year: int | None = None,
    dry_run: bool = False,
) -> dict:
    """
    Executa a Fase 1 completa:
      - Lê o Excel
      - Identifica faltosos
      - Cria campanha
      - Popula fila
      - Retorna sumário com métricas
    """
    today = date.today()
    month = month or today.month
    year = year or today.year
    school_id = settings.default_school_id

    if not school_id:
        raise RuntimeError("DEFAULT_SCHOOL_ID não configurado no .env")

    # ── 1. Ler Excel ──────────────────────────────────────────────────────────
    path = Path(report_path)
    if not path.exists():
        raise FileNotFoundError(f"Relatório não encontrado: {report_path}")

    logger.info("Lendo relatório consolidado", path=str(path))
    df = pd.read_excel(path)
    df = _normalize_columns(df)

    missing = REQUIRED_COLS - set(df.columns)
    if missing:
        raise ValueError(f"Colunas obrigatórias ausentes no Excel: {missing}")

    day_col = _find_day_column(df, day)
    logger.info("Coluna do dia identificada", day=day, column=day_col)

    # ── 2. Filtrar faltosos ───────────────────────────────────────────────────
    mask = df[day_col].apply(_is_absence)
    faltosos = df[mask].copy()
    total_faltas = len(faltosos)

    logger.info("Alunos faltosos identificados", total=total_faltas, dia=day, mes=month)

    if total_faltas == 0:
        print(f"\n✅ Nenhuma falta registrada para o dia {day:02d}/{month:02d}.")
        return {"total_faltas": 0, "enfileirados": 0, "nao_encontrados": 0, "campaign_id": None}

    # ── 3. Conectar ao Supabase e criar campanha ──────────────────────────────
    client = _build_supabase_client()
    campaign_id = _create_campaign(client, school_id, day, month, year, total_faltas, dry_run)

    # ── 4. Processar cada faltoso ─────────────────────────────────────────────
    stats = {
        "total_faltas": total_faltas,
        "enfileirados": 0,
        "sem_uuid": 0,
        "sem_responsavel": 0,
        "ja_enfileirado": 0,
        "campaign_id": campaign_id,
        "nao_encontrados": [],
    }

    print(f"\n{'='*60}")
    print(f"  Campanha: Busca Ativa — Faltas dia {day:02d}/{month:02d}/{year}")
    print(f"  Mode: {'🧪 DRY RUN (sem gravação)' if dry_run else '🔴 PRODUÇÃO'}")
    print(f"  Total de faltosos: {total_faltas}")
    print(f"{'='*60}\n")

    for idx, row in faltosos.iterrows():
        ra = str(row.get("RA", "")).strip()
        name = str(row.get("NOME", "")).strip()
        turma = str(row.get("TURMA", row.get("CLASSE", ""))).strip()

        print(f"[{stats['enfileirados'] + stats['sem_uuid'] + stats['sem_responsavel'] + 1}/{total_faltas}] "
              f"{name} | RA: {ra} | Turma: {turma}")

        # 4a. Resolver UUID do aluno
        student_id = _resolve_student_uuid(client, school_id, ra, name)
        if not student_id:
            print(f"  ⚠️  Aluno NÃO encontrado no banco — pulando")
            stats["sem_uuid"] += 1
            stats["nao_encontrados"].append({"ra": ra, "nome": name, "turma": turma})
            continue

        # 4b. Resolver responsável principal
        guardian = _resolve_primary_guardian(client, student_id)
        if not guardian:
            print(f"  ⚠️  Responsável principal NÃO vinculado — pulando")
            stats["sem_responsavel"] += 1
            stats["nao_encontrados"].append({"ra": ra, "nome": name, "turma": turma, "motivo": "sem_responsavel"})
            continue

        guardian_id = str(guardian["id"])
        wa_jid = guardian.get("wa_jid")

        # 4c. Metadata a ser gravado (Turma + Data da Falta)
        metadata = {
            "turma": turma,
            "data_falta": f"{day:02d}/{month:02d}/{year}",
            "ra": ra,
            "nome_excel": name,
            "guardian_name": guardian.get("name", ""),
            "guardian_phone": guardian.get("phone_e164", ""),
        }

        # 4d. Enfileirar
        msg_id = _enqueue_message(
            client=client,
            school_id=school_id,
            campaign_id=campaign_id,
            student_id=student_id,
            guardian_id=guardian_id,
            wa_jid=wa_jid,
            metadata=metadata,
            dry_run=dry_run,
        )
        stats["enfileirados"] += 1
        wa_indicator = "✅ JID OK" if wa_jid else "⚠️  Sem JID (wa_jid NULL)"
        print(f"  ✅ Enfileirado | Responsável: {guardian.get('name')} | {wa_indicator}")

    # ── 5. Sumário Final ──────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"  SUMÁRIO DA CARGA")
    print(f"{'='*60}")
    print(f"  Campanha ID   : {campaign_id}")
    print(f"  Faltosos      : {stats['total_faltas']}")
    print(f"  ✅ Enfileirados: {stats['enfileirados']}")
    print(f"  ⚠️  Sem UUID   : {stats['sem_uuid']}")
    print(f"  ⚠️  Sem Resp.  : {stats['sem_responsavel']}")
    if dry_run:
        print(f"\n  🧪 DRY RUN: Nenhum dado foi gravado no banco.")
    else:
        print(f"\n  ✅ Fila populada! Execute o orquestrador quando pronto:")
        print(f"     python scripts/campaign_orchestrator.py --campaign-id {campaign_id}")
    print(f"{'='*60}\n")

    logger.info("Carga de campanha concluída", **{k: v for k, v in stats.items() if k != "nao_encontrados"})
    return stats


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Fase 1: Carrega faltosos do Excel e prepara a fila de campanha.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  python scripts/campaign_loader.py --day 4
  python scripts/campaign_loader.py --day 4 --month 5 --year 2026
  python scripts/campaign_loader.py --day 4 --dry-run
        """,
    )
    parser.add_argument(
        "--day", type=int, required=True,
        help="Número do dia das faltas (ex: 4 para dia 4).",
    )
    parser.add_argument(
        "--month", type=int, default=None,
        help="Mês (1-12). Padrão: mês atual.",
    )
    parser.add_argument(
        "--year", type=int, default=None,
        help="Ano. Padrão: ano atual.",
    )
    parser.add_argument(
        "--report", type=str, default=settings.consolidated_report_path,
        help="Caminho para o Excel consolidado.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Simula toda a operação sem gravar nada no banco.",
    )

    args = parser.parse_args()

    try:
        load_campaign(
            report_path=args.report,
            day=args.day,
            month=args.month,
            year=args.year,
            dry_run=args.dry_run,
        )
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"\n❌ ERRO: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

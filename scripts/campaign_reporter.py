"""
campaign_reporter.py — Orquestrador de Relatorios (V5)

Executa automaticamente ao ser chamado pelo botao "Fase 3" do painel Streamlit.
Gera TODOS os relatorios de uma campanha em sequencia:

  0. Backfill de LIDs (mapeia identidades mascaras no WhatsApp)
  1. Relatorio Executivo (metricas + Excel multi-planilha)
  2. Diario Auditado de Conversas (TXT + MD por aluno)
  3. Relatorio Completo (MD + CSV + Excel com justificativas)

Uso:
    python scripts/campaign_reporter.py
    python scripts/campaign_reporter.py --campaign-id <uuid>
    python scripts/campaign_reporter.py --skip-backfill
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    CYAN = '\033[96m'
    BLUE = '\033[94m'
    BOLD = '\033[1m'
    RESET = '\033[0m'


def _get_repository():
    from app.infrastructure.supabase.repositories import SupabaseRepository
    return SupabaseRepository()


def _find_latest_campaign(repo):
    operation = lambda: (
        repo.client.schema("busca_ativa_v2")
        .table("campaigns")
        .select("id, name, absence_days, created_at")
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    res = repo._execute_with_retry(operation, operation="find_latest_campaign")
    if not res.data:
        return None
    c = res.data[0]
    return {
        "id": c["id"],
        "name": c.get("name", "Campanha"),
        "absence_days": c.get("absence_days", ""),
        "created_at": c.get("created_at", "")
    }


def _get_campaign_info(repo, campaign_id):
    if isinstance(campaign_id, list):
        campaign_ids = campaign_id
    elif isinstance(campaign_id, str) and "," in campaign_id:
        campaign_ids = [c.strip() for c in campaign_id.split(",")]
    else:
        campaign_ids = [campaign_id]

    operation = lambda: (
        repo.client.schema("busca_ativa_v2")
        .table("campaigns")
        .select("name, absence_days")
        .in_("id", campaign_ids)
        .execute()
    )
    res = repo._execute_with_retry(operation, operation="get_campaign_info")
    if not res.data:
        return None
    name = " + ".join(c["name"] for c in res.data if c.get("name"))
    absence_days = res.data[0].get("absence_days", "")
    return {"name": name, "absence_days": absence_days}


def run_orchestrator(campaign_id=None, skip_backfill=False):
    """
    Orquestra a geracao de todos os relatorios de uma campanha.

    Args:
        campaign_id: UUID da campanha. Se None, usa a mais recente.
        skip_backfill: Se True, pula o mapeamento de LIDs.
    """
    from app.core.config import settings

    repo = _get_repository()
    school_id = settings.default_school_id

    # ── Identificar campanha ──────────────────────────────────────────────
    if not campaign_id:
        print(f"{Colors.CYAN}Buscando campanha mais recente...{Colors.RESET}")
        camp = _find_latest_campaign(repo)
        if not camp:
            print(f"{Colors.RED}ERRO: Nenhuma campanha encontrada no banco.{Colors.RESET}")
            return None
        
        absence_days = camp["absence_days"]
        # Buscar todas as campanhas da mesma data de falta para consolidar automaticamente
        operation = lambda: (
            repo.client.schema("busca_ativa_v2")
            .table("campaigns")
            .select("id, name")
            .eq("absence_days", absence_days)
            .execute()
        )
        same_day_camps = repo._execute_with_retry(operation, operation="find_same_day_campaigns")
        same_day_data = same_day_camps.data or []
        if len(same_day_data) > 1:
            campaign_ids = [c["id"] for c in same_day_data]
            campaign_name = " + ".join(c["name"] for c in same_day_data if c.get("name"))
            campaign_id = ",".join(campaign_ids)
            print(f"{Colors.GREEN}AUTO-CONSOLIDAÇÃO: Encontradas {len(campaign_ids)} campanhas para a data {absence_days}!{Colors.RESET}")
        else:
            campaign_id = camp["id"]
            campaign_name = camp["name"]
            campaign_ids = [campaign_id]
    else:
        if isinstance(campaign_id, list):
            campaign_ids = campaign_id
        elif isinstance(campaign_id, str) and "," in campaign_id:
            campaign_ids = [c.strip() for c in campaign_id.split(",")]
        else:
            campaign_ids = [campaign_id]

        info = _get_campaign_info(repo, campaign_id)
        if not info:
            print(f"{Colors.RED}ERRO: Campanha nao encontrada: {campaign_id}{Colors.RESET}")
            return None
        campaign_name = info["name"]
        absence_days = info["absence_days"]

    campaign_short = campaign_ids[0][:8] if len(campaign_ids) == 1 else f"{campaign_ids[0][:8]}_combined"

    print("=" * 65)
    print(f"{Colors.BOLD}  RELATORIOS CONSOLIDADOS{Colors.RESET}")
    print(f"  Campanha: {campaign_name}")
    print(f"  Faltas:   {absence_days}")
    print(f"  ID:       {campaign_id}")
    print("=" * 65)

    stats = {}

    # ── ETAPA 0: Backfill de LIDs ─────────────────────────────────────────
    if not skip_backfill:
        print(f"\n{Colors.CYAN}[ETAPA 1/4] Backfill de LIDs (mapeamento de identidades)...{Colors.RESET}")
        try:
            from scripts.backfill_lids_from_conversations import run as backfill_run
            backfill_run(campaign_id=campaign_id, dry_run=False)
            print(f"{Colors.GREEN}  OK{Colors.RESET}")
        except Exception as e:
            print(f"{Colors.YELLOW}  AVISO: Backfill falhou: {e}{Colors.RESET}")
            print(f"{Colors.YELLOW}  Continuando com os LIDs ja mapeados...{Colors.RESET}")
    else:
        print(f"\n{Colors.YELLOW}[ETAPA 1/4] Backfill PULADO (--skip-backfill){Colors.RESET}")

    # ── ETAPA 1: Relatorio Executivo ──────────────────────────────────────
    print(f"\n{Colors.CYAN}[ETAPA 2/4] Relatorio Executivo (metricas + Excel)...{Colors.RESET}")
    try:
        from app.application.analytics.campaign_analytics import CampaignAnalytics
        from app.application.analytics.report_exporter import ReportExporter

        analytics = CampaignAnalytics(repo)
        report = analytics.generate_report(school_id, campaign_id)

        print(f"  Alunos alvo:    {report.operational.total_students_targeted}")
        print(f"  Enviados:       {report.operational.messages_sent_success}")
        print(f"  Respostas:      {report.operational.responses_received}")
        print(f"  Taxa resposta:  {report.operational.response_rate*100:.1f}%")

        exporter = ReportExporter()
        excel_bytes = exporter.to_excel_bytes(report)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        excel_file = ROOT / "relatorios" / f"Relatorio_Executivo_{campaign_short}_{timestamp}.xlsx"
        excel_file.parent.mkdir(exist_ok=True)
        excel_file.write_bytes(excel_bytes)
        print(f"{Colors.GREEN}  Excel: {excel_file}{Colors.RESET}")

        stats["targeted"] = report.operational.total_students_targeted
        stats["sent"] = report.operational.messages_sent_success
        stats["responses"] = report.operational.responses_received
        stats["rate"] = report.operational.response_rate
    except Exception as e:
        print(f"{Colors.YELLOW}  AVISO: Relatorio executivo falhou: {e}{Colors.RESET}")

    # ── ETAPA 2: Diario Auditado ─────────────────────────────────────────
    print(f"\n{Colors.CYAN}[ETAPA 3/4] Diario Auditado de Conversas (TXT + MD)...{Colors.RESET}")
    try:
        from scripts.consolidate_campaign_report import run_consolidate
        result = run_consolidate(campaign_id=campaign_id, school_id=school_id)
        print(f"  Conversas:      {result['total_conversas']}")
        print(f"  Responderam:    {result['responderam']}")
        print(f"  Justificaram:   {result['justificaram']}")
        print(f"  Sem resposta:   {result['sem_resposta']}")
        evo = result.get('evolution_encontrados', 0)
        if evo:
            print(f"  Via Evolution:  {evo} (detectados no WhatsApp, nao estavam no banco)")
        print(f"{Colors.GREEN}  Arquivos: relatorios/consolidados/{result['arquivos'][0]}{Colors.RESET}")

        stats["conversas"] = result["total_conversas"]
        stats["responderam"] = result["responderam"]
        stats["justificaram"] = result["justificaram"]
        stats["sem_resposta"] = result["sem_resposta"]
        if stats.get("sent"):
            stats["rate"] = result["responderam"] / stats["sent"]
    except Exception as e:
        print(f"{Colors.YELLOW}  AVISO: Diario auditado falhou: {e}{Colors.RESET}")

    # ── ETAPA 3: Relatorio Completo ───────────────────────────────────────
    print(f"\n{Colors.CYAN}[ETAPA 4/4] Relatorio Completo (MD + CSV + Excel)...{Colors.RESET}")
    try:
        from scripts.full_day_report import build_report, write_outputs, make_client
        client = make_client()
        markdown = build_report(client, campaign_id)
        camp_date = datetime.now().strftime("%d_%m_%Y")
        stem = f"relatorio_completo_{camp_date}_{campaign_short}"
        out_dir = ROOT / "relatorios" / "campanhas_v2"
        write_outputs(out_dir, stem, markdown)
        print(f"{Colors.GREEN}  MD:  {out_dir / f'{stem}.md'}{Colors.RESET}")
        print(f"{Colors.GREEN}  CSV: {out_dir / f'{stem}_sem_resposta.csv'}{Colors.RESET}")
        print(f"{Colors.GREEN}  XLSX:{out_dir / f'{stem}.xlsx'}{Colors.RESET}")
    except Exception as e:
        print(f"{Colors.YELLOW}  AVISO: Relatorio completo falhou: {e}{Colors.RESET}")

    # ── Resumo final ──────────────────────────────────────────────────────
    print("\n" + "=" * 65)
    print(f"{Colors.BOLD}  RESUMO DA CAMPANHA{Colors.RESET}")
    print("=" * 65)
    if stats:
        if "sent" in stats:
            print(f"  Enviados:      {stats.get('sent', '?')}")
        if "responderam" in stats:
            print(f"  Responderam:   {stats.get('responderam', '?')}")
        if "justificaram" in stats:
            print(f"  Justificaram:  {stats.get('justificaram', '?')}")
        if "sem_resposta" in stats:
            print(f"  Sem resposta:  {stats.get('sem_resposta', '?')}")
        if "rate" in stats:
            print(f"  Taxa:          {stats['rate']*100:.1f}%")

    print(f"\n{Colors.BOLD}  ARQUIVOS GERADOS{Colors.RESET}")
    print(f"  relatorios/consolidados/auditoria_*.txt")
    print(f"  relatorios/consolidados/auditoria_*.md")
    print(f"  relatorios/campanhas_v2/relatorio_completo_*.md")
    print(f"  relatorios/campanhas_v2/relatorio_completo_*.csv")
    print(f"  relatorios/campanhas_v2/relatorio_completo_*.xlsx")
    print(f"  relatorios/Relatorio_Executivo_*.xlsx")
    print("=" * 65 + "\n")

    return stats


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Orquestrador de Relatorios de Campanha (V5)")
    parser.add_argument("--campaign-id", type=str, default=None,
                        help="UUID da campanha. Se nao informado, usa a mais recente.")
    parser.add_argument("--skip-backfill", action="store_true",
                        help="Pular o mapeamento de LIDs (mais rapido, porem menos respostas detectadas).")
    args = parser.parse_args()

    try:
        run_orchestrator(campaign_id=args.campaign_id, skip_backfill=args.skip_backfill)
    except Exception as e:
        print(f"\n{Colors.RED}ERRO CRITICO: {e}{Colors.RESET}")
        import traceback
        traceback.print_exc()

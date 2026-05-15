"""
campaign_reporter.py — Fase 3: Geração de Relatório de Fechamento da Campanha (V4 - Analytics Integrado)

Responsabilidades:
  1. Executar a reconciliação retrospectiva para identificar conversas pendentes.
  2. Gerar o relatório consolidado usando o motor de CampaignAnalytics.
  3. Exportar o relatório executivo em Excel.
  4. Exibir o resumo analítico e os insights no terminal.
"""

import argparse
import sys
from pathlib import Path
from datetime import datetime

# Cores para formatação
class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    CYAN = '\033[96m'
    BLUE = '\033[94m'
    BOLD = '\033[1m'
    RESET = '\033[0m'

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.config import settings
from app.infrastructure.supabase.repositories import SupabaseRepository
from app.application.analytics.campaign_analytics import CampaignAnalytics
from app.application.analytics.report_exporter import ReportExporter

def _build_repository() -> SupabaseRepository:
    return SupabaseRepository()

def run_reporter(campaign_id: str | None, export_excel: bool = True):
    repository = _build_repository()
    school_id = settings.default_school_id

    # 1. Identificar a campanha
    if not campaign_id:
        print(f"{Colors.CYAN}Buscando a campanha mais recente...{Colors.RESET}")
        res = (
            repository.client.schema("busca_ativa_v2")
            .table("campaigns")
            .select("id, name, created_at")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if not res.data:
            print(f"{Colors.RED}ERRO: Nenhuma campanha encontrada.{Colors.RESET}")
            return
        campaign_id = str(res.data[0]["id"])
        campaign_name = res.data[0]["name"]
    else:
        # Puxar nome da campanha informada
        res = repository.client.schema("busca_ativa_v2").table("campaigns").select("name").eq("id", campaign_id).execute()
        if not res.data:
            print(f"{Colors.RED}ERRO: Campanha não encontrada com ID: {campaign_id}{Colors.RESET}")
            return
        campaign_name = res.data[0]["name"]

    print(f"{Colors.GREEN}OK: Gerando relatório analítico para: {campaign_name}{Colors.RESET}")

    # 2. Executar Motor Analítico (Gera Reconciliação + Métricas)
    print(f"{Colors.CYAN}Processando reconciliação e métricas...{Colors.RESET}")
    analytics = CampaignAnalytics(repository)
    report = analytics.generate_report(school_id, campaign_id)

    # 3. Exibir Resumo no Terminal
    print("\n" + "="*70)
    print(f"{Colors.BOLD}RELATÓRIO ANALÍTICO DE FECHAMENTO{Colors.RESET}")
    print("="*70)
    print(f"{Colors.BOLD}Campanha:{Colors.RESET} {report.campaign_name}")
    print(f"{Colors.BOLD}Data:{Colors.RESET} {report.generated_at.strftime('%d/%m/%Y %H:%M')}")
    print("-" * 70)
    
    print(f"{Colors.BOLD}Métricas Operacionais:{Colors.RESET}")
    print(f"  • Alunos Alvo:         {report.operational.total_students_targeted}")
    print(f"  • Mensagens Enviadas:  {Colors.GREEN}{report.operational.messages_sent_success}{Colors.RESET}")
    print(f"  • Respostas Totais:    {Colors.CYAN}{report.operational.responses_received}{Colors.RESET}")
    print(f"  • Taxa de Resposta:    {Colors.BOLD}{report.operational.response_rate*100:.1f}%{Colors.RESET}")
    
    print(f"\n{Colors.BOLD}Falhas Estruturais:{Colors.RESET}")
    print(f"  • Sem Responsável:     {Colors.YELLOW}{report.structural.no_guardian_linked}{Colors.RESET}")
    print(f"  • Números Inválidos:   {Colors.YELLOW}{report.structural.invalid_numbers}{Colors.RESET}")
    
    print(f"\n{Colors.BOLD}Análise de Risco (Matriz PAI):{Colors.RESET}")
    print(f"  • {Colors.RED}ALTO RISCO (Evasão): {report.risk.high_risk}{Colors.RESET}")
    print(f"  • {Colors.YELLOW}MÉDIO RISCO:         {report.risk.medium_risk}{Colors.RESET}")
    print(f"  • {Colors.GREEN}BAIXO RISCO (Just.): {report.risk.low_risk}{Colors.RESET}")
    
    print("-" * 70)
    print(f"{Colors.BOLD}Insights Automáticos:{Colors.RESET}")
    for insight in report.insights:
        print(f"  💡 {insight}")
    
    print("-" * 70)
    if report.priority_cases:
        print(f"{Colors.BOLD}Casos Prioritários ({len(report.priority_cases)}):{Colors.RESET}")
        for case in report.priority_cases[:5]: # Top 5
            print(f"  ⚠️  {case.student_name}: {case.reason} ({case.risk_level})")
        if len(report.priority_cases) > 5:
            print(f"  ... e mais {len(report.priority_cases)-5} casos.")

    # 4. Exportar para Excel
    if export_excel:
        print(f"\n{Colors.CYAN}Exportando relatório executivo para Excel...{Colors.RESET}")
        exporter = ReportExporter()
        excel_bytes = exporter.to_excel_bytes(report)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        filename = f"Relatorio_Executivo_{campaign_id[:8]}_{timestamp}.xlsx"
        export_dir = ROOT / "relatorios"
        export_dir.mkdir(exist_ok=True)
        
        file_path = export_dir / filename
        with open(file_path, "wb") as f:
            f.write(excel_bytes)
        
        print(f"{Colors.GREEN}✅ Relatório salvo em: {file_path}{Colors.RESET}")

    print("="*70 + "\n")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fase 3: Reporter Analítico da Campanha")
    parser.add_argument("--campaign-id", type=str, default=None, help="ID da campanha. Se não informado, pega a mais recente.")
    parser.add_argument("--no-excel", action="store_true", help="Não gerar o arquivo Excel.")
    args = parser.parse_args()

    try:
        run_reporter(campaign_id=args.campaign_id, export_excel=not args.no_excel)
    except Exception as e:
        print(f"\n{Colors.RED}❌ ERRO AO GERAR RELATÓRIO: {e}{Colors.RESET}")
        import traceback
        traceback.print_exc()

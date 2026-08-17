"""
scripts/test_openai_variants.py
Testa a geração de 20 variações na OpenAI e mede o tempo exato de resposta.
"""
import time
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if sys.platform.startswith("win"):
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True)

from app.services.campaign_ai_service import CampaignAIService

base_msg = """Olá {{nome_responsavel}}, aqui é da {{escola}}. Convocamos você para a Reunião de Pais do aluno {{nome_aluno}} (Turma: {{turma}}) nesta próxima Quarta-feira, dia 5 de agosto, às 18:30. Vamos conversar sobre os alunos, as notas do 1º e 2º bimestre, obras e melhorias na escola, dar recados importantes, ouvir sugestões, etc... Sua presença é fundamental!
Temos o objetivo de ter a reunião com maior participação dos responsáveis já registrada, não faltem!
Por favor, responda com "1" para confirmar presença ou "2" caso precise justificar a ausência"""

print("⏳ Iniciando teste de geração de 20 variações...")
start = time.time()
try:
    srv = CampaignAIService()
    variants = srv.generate_variants(base_msg, num_variants=20)
    elapsed = time.time() - start
    print(f"✅ SUCESSO! {len(variants)} variações geradas em {elapsed:.2f} segundos.")
    for i, v in enumerate(variants[:3], 1):
        print(f"\n--- Variação {i} ---")
        print(v)
except Exception as e:
    elapsed = time.time() - start
    print(f"❌ ERRO após {elapsed:.2f} segundos: {e}")

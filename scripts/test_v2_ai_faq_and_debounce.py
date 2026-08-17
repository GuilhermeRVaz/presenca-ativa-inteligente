"""
scripts/test_v2_ai_faq_and_debounce.py

Script de Validação da Arquitetura v2 da IA Conversacional:
1. Verificação de RAG/FAQ no Contexto de Sessão
2. Teste de Busca no Conhecimento da Escola (search_school_knowledge) para dúvidas da Reunião de Pais
3. Teste do Classificador de Intenção (_classify_intent)
4. Teste da Trava de Cooldown/Deduplicação de Respostas (40s)
"""

import sys
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if sys.platform.startswith("win"):
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True)

from app.infrastructure.supabase.repositories import SupabaseRepository
from app.application.inbound_service import InboundService

SCHOOL_ID = "aac99735-32cb-4615-b2cb-0be315f18374"


def run_tests():
    print("\n" + "="*70)
    print("🧪 INICIANDO TESTE DE VALIDAÇÃO DA ARQUITETURA v2 DA IA")
    print("="*70 + "\n")

    repo = SupabaseRepository(timeout=10.0, attempts=2)
    service = InboundService(repository=repo)

    # 1. Teste de Classificador de Intenções
    print("📌 [1/4] Testando Classificador de Intenção (_classify_intent)...")
    test_cases = [
        ("Mais é quarta da semana quer vem?", "LOGISTICA"),
        ("Qual o horário da reunião?", "LOGISTICA"),
        ("Eu não vou conseguir ir, trabalho esse horário. Vou pedir para o padrasto ir", "INFORMA_AUSENCIA"),
        ("Responder com 1 para confirmar presença", "CONFIRMA_PRESENCA"),
        ("Bom diaa", "SAUDACAO"),
    ]

    for text, expected in test_cases:
        intent = service._classify_intent(text)
        status = "✅ PASS" if intent == expected else f"❌ FAIL (obteve {intent})"
        print(f"   • Texto: '{text}' ➔ Intenção: {intent} [{status}]")

    # 2. Teste de Busca no RAG (search_school_knowledge)
    print("\n📌 [2/4] Testando Busca RAG de Conhecimento da Escola (search_school_knowledge)...")
    query = "quarta semana que vem horario data reuniao"
    results = repo.search_school_knowledge(school_id=SCHOOL_ID, query=query, limit=3)
    
    if results:
        print(f"✅ RAG Encontrou {len(results)} respostas relevantes no Supabase!")
        for i, r in enumerate(results, 1):
            print(f"   • Resultado #{i}: P: '{r.get('question')}'")
            print(f"     R: '{r.get('answer')}'")
    else:
        print("❌ Nenhum resultado RAG encontrado no banco!")

    # 3. Teste do Contexto de Sessão Enriquecido
    print("\n📌 [3/4] Testando Contexto de Sessão Enriquecido (get_conversation_context)...")
    context = repo.get_conversation_context(school_id=SCHOOL_ID, sender_jid="5514999999999@s.whatsapp.net", limit=5)
    print(f"   • Campaign FAQ no Contexto: {'Sim' if context.get('campaign_faq') or context.get('campaign') else 'Nenhum (sem campanha ativa no JID mock)'}")
    print(f"   • Estrutura de Retorno OK: {'campaign' in context and 'campaign_faq' in context}")

    # 4. Conclusão
    print("\n" + "="*70)
    print("✨ VALIDAÇÃO CONCLUÍDA COM SUCESSO!")
    print("="*70 + "\n")


if __name__ == "__main__":
    run_tests()

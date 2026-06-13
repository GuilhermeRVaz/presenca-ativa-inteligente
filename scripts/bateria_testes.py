"""
bateria_testes.py — Sprint de Validação / Estabilização
Executa as Baterias 1 e 2 automatizáveis:
  - Bateria 1: Infraestrutura (10x mesma query)
  - Bateria 2: RAG (3 perguntas distintas, valida se retornou conteúdo)
"""
import sys
import requests
import time
from datetime import datetime

# Garante UTF-8 no stdout (Windows CP1252 nao suporta emojis)
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

SCHOOL_ID = "aac99735-32cb-4615-b2cb-0be315f18374"
BASE = "http://127.0.0.1:8000"

SEP = "=" * 60

def cor(txt, code): return f"\033[{code}m{txt}\033[0m"
def ok(txt):    return cor(f"[OK] {txt}", "92")
def err(txt):   return cor(f"[ERRO] {txt}", "91")
def warn(txt):  return cor(f"[AVISO] {txt}", "93")
def cyan(txt):  return cor(txt, "96")

# ─────────────────────────────────────────────────────────────
# BATERIA 1 — Infraestrutura: 10x a mesma query
# ─────────────────────────────────────────────────────────────
def bateria_1():
    print(f"\n{SEP}")
    print(cyan("BATERIA 1: INFRAESTRUTURA (10 chamadas consecutivas ao RAG)"))
    print(SEP)

    query = "Qual o horario de funcionamento da secretaria"
    results = []
    tempos = []

    for i in range(1, 11):
        start = time.time()
        try:
            r = requests.get(
                f"{BASE}/schools/{SCHOOL_ID}/knowledge",
                params={"query": query, "limit": 3},
                timeout=15,
            )
            elapsed = round((time.time() - start) * 1000)
            data = r.json()
            status = "OK" if r.status_code == 200 and isinstance(data, list) else "FALHA"
            count = len(data) if isinstance(data, list) else 0
            tempos.append(elapsed)
            results.append(status)
            tag = "[OK] " if status == "OK" else "[FALHA]"
            print(f"  {tag} Teste {i:02d}: {status} | {elapsed}ms | {count} resultados RAG")
        except Exception as e:
            elapsed = round((time.time() - start) * 1000)
            results.append("ERRO")
            tempos.append(elapsed)
            print(f"  [ERRO] Teste {i:02d}: ERRO | {elapsed}ms | {e}")
        time.sleep(0.5)

    sucessos = results.count("OK")
    avg = round(sum(tempos) / len(tempos)) if tempos else 0
    status_label = ok("ESTÁVEL") if sucessos == 10 else (warn("INSTÁVEL") if sucessos >= 7 else err("CRÍTICO"))

    print(f"\n  Resultado: {sucessos}/10 sucessos | Tempo médio: {avg}ms")
    print(f"  Status infra: {status_label}")
    return sucessos, avg


# ─────────────────────────────────────────────────────────────
# BATERIA 2 — RAG: 3 perguntas distintas
# ─────────────────────────────────────────────────────────────
def bateria_2():
    print(f"\n{SEP}")
    print(cyan("BATERIA 2: RAG (3 perguntas distintas)"))
    print(SEP)

    perguntas = [
        "Qual o horario de funcionamento da secretaria",
        "Quais documentos preciso para matricula",
        "Como faço transferência para outra escola",
    ]

    resultados = []
    for i, q in enumerate(perguntas, 1):
        start = time.time()
        try:
            r = requests.get(
                f"{BASE}/schools/{SCHOOL_ID}/knowledge",
                params={"query": q, "limit": 5},
                timeout=15,
            )
            elapsed = round((time.time() - start) * 1000)
            data = r.json()
            count = len(data) if isinstance(data, list) else 0
            tem_rag = count > 0

            tag = "[OK] " if tem_rag else "[SEM DADOS]"
            status = "COM CONTEUDO" if tem_rag else "SEM CONTEUDO"
            print(f"\n  {tag} Pergunta {i}: \"{q}\"")
            print(f"     Status HTTP: {r.status_code} | {elapsed}ms | {count} chunks RAG retornados")
            if tem_rag and data:
                first = data[0]
                content_preview = str(first.get("content", first.get("question", ""))[:120])
                print(f"     Preview chunk 1: \"{content_preview}...\"")
            resultados.append(tem_rag)
        except Exception as e:
            print(f"\n  [ERRO] Pergunta {i}: ERRO - {e}")
            resultados.append(False)
        time.sleep(0.3)

    rag_ok = sum(1 for r in resultados if r)
    status_label = ok("FUNCIONANDO") if rag_ok == 3 else (warn("PARCIAL") if rag_ok >= 1 else err("SEM DADOS"))
    print(f"\n  Resultado RAG: {rag_ok}/3 perguntas retornaram conteúdo")
    print(f"  Status RAG: {status_label}")
    return rag_ok


# ─────────────────────────────────────────────────────────────
# BATERIA 3 e 4 — Instruções manuais
# ─────────────────────────────────────────────────────────────
def instrucoes_manuais():
    print(f"\n{SEP}")
    print(cyan("BATERIA 3: MARLENE — Teste Manual (via WhatsApp)"))
    print(SEP)
    print("""
  Envie do celular de teste para o número da Marlene:

  Mensagem: "Meu filho faltou hoje porque estava doente."

  Esperado:
  ✅ Marlene responde pedindo nome do aluno e turma
  ✅ Log FastAPI mostra: webhook_result + identity_resolved
  ✅ n8n processa e retorna via Evolution

  Se aparecer:
  ❌ Resposta dupla          → problema de debounce
  ❌ Nenhuma resposta       → n8n não recebeu (verificar triagem webhook)
  ❌ Resposta genérica sem perguntar aluno → classificador errado
    """)

    print(f"\n{SEP}")
    print(cyan("BATERIA 4: DEBOUNCE — Teste Manual (via WhatsApp)"))
    print(SEP)
    print("""
  Em rápida sequência (< 3 segundos), envie:
  1. Um áudio OU foto
  2. Uma mensagem de texto: "Segue justificativa da falta"

  Esperado:
  ✅ Marlene responde UMA ÚNICA VEZ
  ✅ Log mostra: debounce_merged OU apenas 1 webhook_result processado

  Se aparecer:
  ❌ 2 ou 3 respostas → debounce não está funcionando
    """)


# ─────────────────────────────────────────────────────────────
# SUMÁRIO FINAL
# ─────────────────────────────────────────────────────────────
def sumario(b1_ok, b1_avg, b2_ok):
    print(f"\n{SEP}")
    print(cyan("SUMÁRIO DO SPRINT DE VALIDAÇÃO"))
    print(SEP)
    print(f"  {'Bateria 1 (Infra):':<30} {b1_ok}/10 OK | média {b1_avg}ms")
    print(f"  {'Bateria 2 (RAG):':<30} {b2_ok}/3 OK")
    print(f"  {'Bateria 3 (Marlene):':<30} → Aguarda teste manual")
    print(f"  {'Bateria 4 (Debounce):':<30} → Aguarda teste manual")

    if b1_ok == 10 and b2_ok == 3:
        print(f"\n  {ok('✅ BASE ESTÁVEL — pronto para testes com Marlene!')}")
    elif b1_ok >= 7 and b2_ok >= 1:
        print(f"\n  {warn('⚠️  BASE INSTÁVEL — algumas chamadas falharam. Investigue antes de testar Marlene.')}")
    else:
        print(f"\n  {err('❌ BASE CRÍTICA — instabilidade severa. Não teste Marlene ainda.')}")
    print()


if __name__ == "__main__":
    print(f"\nInício: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    b1_ok, b1_avg = bateria_1()
    b2_ok = bateria_2()
    instrucoes_manuais()
    sumario(b1_ok, b1_avg, b2_ok)

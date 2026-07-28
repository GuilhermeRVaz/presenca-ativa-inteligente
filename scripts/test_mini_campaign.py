"""
test_mini_campaign.py - Script de Teste de Sincronização e Entrega Mini-Campanha
"""

import os
import sys
import time
import httpx
from datetime import datetime

# Garantir encoding UTF-8 no terminal Windows
if sys.platform.startswith("win"):
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
    sys.stderr = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)

EVOLUTION_API_URL = os.getenv("EVOLUTION_API_URL", "http://localhost:8080").rstrip("/")
EVOLUTION_API_KEY = os.getenv("EVOLUTION_API_KEY", "clinivet_global_key_2026")
EVOLUTION_INSTANCE = os.getenv("EVOLUTION_API_INSTANCE", "escola-decia")

NUMBERS = [
    ("14981324832", "5514981324832"),
    ("14 98230-7099", "5514982307099"),
    ("1435222836", "551435222836"),
    ("14 99705-3808", "5514997053808"),
]

MESSAGE_TEMPLATE = (
    "🧪 [PAI - Teste de Sincronização]\n"
    "Olá! Este é um teste técnico do sistema de busca ativa do CEEJA Décia enviado em {now}.\n"
    "Se você recebeu esta mensagem, a sincronização do sistema está 100% ativa!"
)

def run_mini_campaign():
    now_str = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    url = f"{EVOLUTION_API_URL}/message/sendText/{EVOLUTION_INSTANCE}"
    headers = {
        "apikey": EVOLUTION_API_KEY,
        "Content-Type": "application/json"
    }

    print("=" * 70)
    print(f"🚀 INICIANDO MINI-CAMPANHA DE TESTE DE SINCRONIZAÇÃO ({len(NUMBERS)} números)")
    print(f"📍 Instância Evolution: {EVOLUTION_INSTANCE}")
    print(f"🌐 URL Endpoint: {url}")
    print("=" * 70)

    results = []

    for orig, phone in NUMBERS:
        text = MESSAGE_TEMPLATE.format(now=now_str)
        payload = {
            "number": phone,
            "text": text
        }

        print(f"\n📤 Disparando para {orig} -> Formato E164: {phone} ...")
        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.post(url, headers=headers, json=payload)
                status_code = resp.status_code
                data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else resp.text

                if status_code in (200, 201):
                    msg_id = None
                    if isinstance(data, dict):
                        msg_id = data.get("key", {}).get("id") or data.get("id") or data.get("messageId")
                    print(f"   ✅ HTTP {status_code} - Aceito pela Evolution API | ID: {msg_id}")
                    results.append({"number": phone, "success": True, "http_status": status_code, "msg_id": msg_id, "data": data})
                else:
                    print(f"   ❌ HTTP {status_code} - Erro na Evolution: {data}")
                    results.append({"number": phone, "success": False, "http_status": status_code, "error": str(data)})
        except Exception as exc:
            print(f"   💥 Exceção de Conexão: {exc}")
            results.append({"number": phone, "success": False, "error": str(exc)})

        # Intervalo de 3 segundos entre os testes para simular envio cadenciado
        time.sleep(3)

    print("\n" + "=" * 70)
    print("📊 RESUMO DOS DISPAROS DA MINI-CAMPANHA:")
    for r in results:
        status = "✅ SUCESSO (HTTP 201)" if r.get("success") else "❌ FALHA"
        print(f" - {r['number']}: {status} | ID: {r.get('msg_id', 'N/A')}")
    print("=" * 70)

if __name__ == "__main__":
    run_mini_campaign()

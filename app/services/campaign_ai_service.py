"""
app/services/campaign_ai_service.py

Serviço de Inteligência Artificial para Geração de Variações de Mensagem (Anti-Spam).
Gera exatamente N (padrão 20) versões parafraseadas de uma mensagem base escolar,
garantindo alta diversidade (saudações, despedidas, presença/ausência de emojis, estilos de frase)
e preservação rigorosa de todos os placeholders.
"""

from __future__ import annotations

import json
import re
import logging
from typing import Any
from app.core.config import settings

logger = logging.getLogger(__name__)

DEFAULT_PLACEHOLDERS = ["{{nome_responsavel}}", "{{nome_aluno}}", "{{turma}}", "{{escola}}"]


def _safe_log_warning(msg: str):
    try:
        logger.warning(msg)
    except Exception:
        pass


def _safe_log_error(msg: str):
    try:
        logger.error(msg)
    except Exception:
        pass


class CampaignAIService:
    """
    Serviço que interage com a OpenAI para gerar variações da mensagem de campanha com máxima diversidade.
    """

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or settings.openai_api_key

    def extract_placeholders(self, text: str) -> list[str]:
        """
        Extrai todos os placeholders no formato {{nome_variavel}} da mensagem base.
        """
        return list(set(re.findall(r"\{\{[a-zA-Z0-9_]+\}\}", text)))

    def generate_variants(
        self,
        base_message: str,
        category: str = "INFORMATIVA",
        num_variants: int = 20,
    ) -> list[str]:
        """
        Gera num_variants (padrão 20) versões parafraseadas da base_message.
        Garante alta diversidade de vocabulário, aberturas, saudações e emojis.
        """
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY não está configurada no ambiente .env")

        placeholders = self.extract_placeholders(base_message)
        placeholders_str = ", ".join(placeholders) if placeholders else "nenhum"

        system_prompt = (
            "Você é um Especialista em Comunicação Escolar Humanizada e Anti-Spam.\n"
            "Seu objetivo é gerar variações com MÁXIMA DIVERSIDADE de texto para envio no WhatsApp.\n\n"
            "Diretrizes de Diversidade Exigidas:\n"
            "1. Alterne as saudações iniciais entre cada variação: 'Olá {{nome_responsavel}}!', 'Bom dia!', "
            "'Prezada família...', 'Prezado(a) {{nome_responsavel}}', 'Atenção responsável:', 'Comunicado importante:' etc.\n"
            "2. Alterne a presença de emojis: algumas mensagens com emojis amigáveis (📚, 🏫, 📅, ✏️), outras totalmente sem emojis.\n"
            "3. Varie o tamanho das frases e a ordem dos parágrafos.\n"
            "4. Mantenha 100% o mesmo significado e objetivo original da mensagem escolar.\n"
            "5. REGRA DE OURO DOS PLACEHOLDERS: Todos estes placeholders (" + placeholders_str + ") "
            "devem ser MANTIDOS EXACTAMENTE COMO ESCRITOS (com chaves duplas {{...}}) em TODAS as variações geradas. "
            "Não altere a grafia dos placeholders nem os remova!\n"
            "6. Retorne ESTREITAMENTE um JSON com o formato: {\"variants\": [\"var1\", \"var2\", ..., \"var" + str(num_variants) + "\"]}"
        )

        user_prompt = (
            f"Categoria da Campanha: {category}\n"
            f"Mensagem Base Original:\n\"\"\"{base_message}\"\"\"\n\n"
            f"Gere exatamente {num_variants} variações altamente diversificadas em JSON estrito."
        )

        try:
            import requests

            url = "https://api.openai.com/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": "gpt-4o-mini",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "response_format": {"type": "json_object"},
                "temperature": 0.8,
            }

            res = requests.post(url, headers=headers, json=payload, timeout=45)
            res.raise_for_status()

            data = res.json()
            content = data["choices"][0]["message"]["content"]
            parsed = json.loads(content)

            variants = parsed.get("variants", [])

            validated_variants = []
            for idx, var in enumerate(variants[:num_variants]):
                missing = [ph for ph in placeholders if ph not in var]
                if missing:
                    _safe_log_warning(
                        f"Variação {idx+1} perdeu placeholders {missing}. Corrigindo automaticamente..."
                    )
                    for ph in missing:
                        var += f" ({ph})"
                validated_variants.append(var.strip())

            while len(validated_variants) < num_variants:
                validated_variants.append(base_message)

            return validated_variants

        except Exception as exc:
            _safe_log_error(f"Erro ao gerar variações por IA: {exc}")
            raise RuntimeError(f"Falha na geração de variações por IA: {exc}") from exc

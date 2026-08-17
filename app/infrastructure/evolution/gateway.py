from typing import Any
import time

import httpx

from app.core.config import settings
from app.domain.models import SendResult


class EvolutionGateway:
    def send_text(
        self, *, to_jid: str, text: str, dry_run: bool = False, max_retries: int = 3, retry_delay: float = 3.0
    ) -> SendResult:
        if to_jid.endswith("@lid"):
            phone = to_jid
        else:
            phone = to_jid.split("@", 1)[0]

        if dry_run:
            return SendResult(success=True, provider_message_id=None, mock=True)

        self._validate_config()
        payload = {"number": phone, "text": text}
        return self._post_with_retry(
            "message/sendText", payload, max_retries=max_retries, retry_delay=retry_delay, extract_id=True
        )

    def send_button_message(
        self,
        *,
        to_jid: str,
        title: str = "",
        description: str = "",
        buttons: list[dict[str, str]],
        dry_run: bool = False,
        max_retries: int = 3,
        retry_delay: float = 3.0,
    ) -> SendResult:
        if to_jid.endswith("@lid"):
            phone = to_jid
        else:
            phone = to_jid.split("@", 1)[0]

        if dry_run:
            return SendResult(success=True, provider_message_id=None, mock=True)

        self._validate_config()
        
        # Format buttons for Evolution API
        formatted_buttons = []
        for i, btn in enumerate(buttons):
            formatted_buttons.append({
                "buttonId": btn.get("id", f"BTN_{i}"),
                "buttonText": {"displayText": btn.get("text", "")},
                "type": "reply"
            })

        payload = {
            "number": phone,
            "title": title,
            "description": description,
            "buttons": formatted_buttons
        }
        return self._post_with_retry(
            "message/sendButtons", payload, max_retries=max_retries, retry_delay=retry_delay, extract_id=True
        )

    def send_presence(
        self,
        *,
        to_jid: str,
        presence: str = "composing",
        delay: int = 2000,
        dry_run: bool = False,
        max_retries: int = 2,
        retry_delay: float = 1.0,
    ) -> SendResult:
        if dry_run:
            return SendResult(success=True, provider_message_id=None, mock=True)

        self._validate_config()

        if "@" not in to_jid:
            number = f"{to_jid}@s.whatsapp.net"
        else:
            number = to_jid

        payload = {"number": number, "presence": presence, "delay": delay}
        return self._post_with_retry(
            "chat/sendPresence", payload, max_retries=max_retries, retry_delay=retry_delay, extract_id=False
        )

    def _post_with_retry(
        self,
        endpoint_path: str,
        payload: dict[str, Any],
        *,
        max_retries: int = 3,
        retry_delay: float = 3.0,
        extract_id: bool = True,
    ) -> SendResult:
        last_error = ""
        for attempt in range(1, max_retries + 1):
            try:
                with httpx.Client(timeout=settings.evolution_timeout_seconds) as client:
                    response = client.post(
                        self._send_url(endpoint_path),
                        headers=self._headers(),
                        json=payload,
                    )
                data = self._json(response)
                if response.status_code in (200, 201) and "error" not in response.text.lower():
                    provider_id = self._extract_provider_message_id(data) if extract_id else None
                    return SendResult(success=True, provider_message_id=provider_id)

                last_error = response.text
                err_lower = response.text.lower()
                is_transient = (
                    response.status_code in (500, 502, 503, 504)
                    or any(term in err_lower for term in ["connection closed", "socket closed", "connecting", "timeout"])
                )
                if not is_transient or attempt >= max_retries:
                    break

                print(
                    f"[EVOLUTION GATEWAY RETRY] Tentativa {attempt}/{max_retries} falhou com erro transiente "
                    f"({response.status_code}). Aguardando {retry_delay * attempt:.1f}s para reconexão..."
                )
                time.sleep(retry_delay * attempt)

            except httpx.HTTPError as exc:
                last_error = str(exc)
                if attempt >= max_retries:
                    break
                print(
                    f"[EVOLUTION GATEWAY RETRY] Tentativa {attempt}/{max_retries} falhou com exceção HTTP: "
                    f"{exc}. Aguardando {retry_delay * attempt:.1f}s..."
                )
                time.sleep(retry_delay * attempt)

        return SendResult(success=False, error=last_error)

    def _validate_config(self) -> None:
        missing = [
            name
            for name, value in {
                "EVOLUTION_API_URL": settings.evolution_api_url,
                "EVOLUTION_API_KEY": settings.evolution_api_key,
                "EVOLUTION_API_INSTANCE": settings.evolution_api_instance,
            }.items()
            if not value
        ]
        if missing:
            raise ValueError("Missing Evolution configuration: " + ", ".join(missing))

    def _send_url(self, endpoint_path: str = "message/sendText") -> str:
        return (
            f"{settings.evolution_api_url.rstrip('/')}/"
            f"{endpoint_path}/{settings.evolution_api_instance}"
        )

    @staticmethod
    def _headers() -> dict[str, str]:
        return {"apikey": settings.evolution_api_key, "Content-Type": "application/json"}

    @staticmethod
    def _json(response: httpx.Response) -> Any:
        try:
            return response.json()
        except ValueError:
            return {}

    @staticmethod
    def _extract_provider_message_id(data: Any) -> str | None:
        if not isinstance(data, dict):
            return None
        value = data.get("key", {}).get("id") or data.get("id") or data.get("messageId")
        return str(value) if value else None


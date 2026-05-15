import hashlib
from dataclasses import dataclass


@dataclass(frozen=True)
class FollowupTemplate:
    template_id: str
    text: str


FOLLOWUP_TEMPLATES = [
    FollowupTemplate(
        template_id="fup_01",
        text="Ola, {parent_name}. A escola ainda nao recebeu retorno sobre a ausencia de {student_name} no dia {absence_days}. E importante sabermos o motivo para acompanhamento escolar. Por favor, nos informe.",
    ),
    FollowupTemplate(
        template_id="fup_02",
        text="Prezado(a) {parent_name}, notamos que {student_name} faltou em {absence_days} e ate agora nao obtivemos resposta. Solicitamos retorno para regularizarmos a situacao.",
    ),
    FollowupTemplate(
        template_id="fup_03",
        text="Bom dia/boa tarde, {parent_name}. Nao tivemos comunicacao sobre a falta de {student_name} no dia {absence_days}. E fundamental o envio da justificativa. Aguardamos retorno.",
    ),
    FollowupTemplate(
        template_id="fup_04",
        text="A direcao da {school_name} informa que a ausencia de {student_name} em {absence_days} consta sem justificativa. Pedimos que nos comunique o motivo o quanto antes.",
    ),
    FollowupTemplate(
        template_id="fup_05",
        text="{parent_name}, identificamos que {student_name} nao compareceu em {absence_days} e nao houve retorno. A comunicacao da familia e essencial. Favor nos responder com a justificativa.",
    ),
    FollowupTemplate(
        template_id="fup_06",
        text="Ola, {parent_name}. Ainda nao recebemos retorno sobre a falta de {student_name} no dia {absence_days}. Por favor, envie a justificativa para a secretaria.",
    ),
    FollowupTemplate(
        template_id="fup_07",
        text="Prezados, a escola esta acompanhando as frequencias e notamos que {student_name} esteve ausente em {absence_days} sem justificativa. Solicitamos o motivo para nossos registros.",
    ),
    FollowupTemplate(
        template_id="fup_08",
        text="Responsavel, a falta de {student_name} em {absence_days} ainda nao foi regularizada. E necessario o envio da justificativa. Entre em contato hoje mesmo.",
    ),
    FollowupTemplate(
        template_id="fup_09",
        text="Caros, nao consta comunicacao sobre a ausencia de {student_name} no dia {absence_days}. Pedimos que nos informe o motivo para regularizar o registro do aluno.",
    ),
    FollowupTemplate(
        template_id="fup_10",
        text="Ultima tentativa de contato: {student_name} ainda nao teve sua falta do dia {absence_days} justificada. E imprescindivel o retorno da familia. Favor responder esta mensagem.",
    ),
]


class FollowupMessageCatalog:
    def __init__(self, school_name: str = "Escola Decia") -> None:
        self.school_name = (school_name or "Escola Decia").strip() or "Escola Decia"

    def build_message(
        self,
        *,
        parent_name: str,
        student_name: str,
        class_name: str,
        absence_days: str,
        campaign_id: str,
        unique_key: str,
    ) -> tuple[str, str]:
        template = self._choose_template(campaign_id=campaign_id, unique_key=unique_key)
        message = template.text.format(
            parent_name=(parent_name or "Responsavel").strip(),
            student_name=(student_name or "Aluno(a)").strip(),
            class_name=(class_name or "nao informada").strip(),
            absence_days=(absence_days or "27/04/2026").strip(),
            school_name=self.school_name,
        )
        return template.template_id, message

    @staticmethod
    def _choose_template(*, campaign_id: str, unique_key: str) -> FollowupTemplate:
        digest = hashlib.sha256(f"{campaign_id}|{unique_key}".encode("utf-8")).hexdigest()
        index = int(digest[:8], 16) % len(FOLLOWUP_TEMPLATES)
        return FOLLOWUP_TEMPLATES[index]

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

# Reforco templates for "Follow-up Reforco Maio 2026 - Prioritarios" (and similar names containing reforco/maio/priorit)
# These are more urgent/direct, focused on >2 absences in May + zero/isolated response, risk of dropout, clear call to action (reply NOW + call school).
# Selection logic below routes campaigns with those keywords exclusively to this sub-list (old campaigns remain on fup_01-10).
REFORCO_TEMPLATES = [
    FollowupTemplate(
        template_id="fup_reforco_01",
        text="URGENTE: {parent_name}, {student_name} (turma {class_name}) acumula MAIS DE 2 FALTAS em maio sem retorno ou justificativa. Isso coloca o aluno em risco de evasao. Favor responder AGORA com o motivo e ligar para a escola.",
    ),
    FollowupTemplate(
        template_id="fup_reforco_02",
        text="Atencao {parent_name}: ausencia recorrente de {student_name} em maio (sem justificativa desde o inicio). Ja enviamos contatos anteriores sem retorno. Necessitamos comunicacao imediata para regularizar a frequencia.",
    ),
    FollowupTemplate(
        template_id="fup_reforco_03",
        text="Prioridade alta - {school_name}: {student_name} faltou repetidamente em maio. Sem retorno da familia ate agora. Solicitamos justificativa + contato por telefone hoje para evitar agravamento.",
    ),
    FollowupTemplate(
        template_id="fup_reforco_04",
        text="{parent_name}, {student_name} ( {class_name} ) tem mais de 2 faltas em maio e apenas retorno isolado ou nenhum. O risco de evasao e real. Responda esta mensagem com o motivo e ligue para a escola AGORA.",
    ),
    FollowupTemplate(
        template_id="fup_reforco_05",
        text="A escola precisa de retorno URGENTE sobre {student_name}. Acumulo de faltas em maio sem justificativa adequada. Favor informar o motivo por esta mensagem ou telefone hoje para regularizar.",
    ),
    FollowupTemplate(
        template_id="fup_reforco_06",
        text="Reforco de contato: {student_name} ausente em multiplos dias de maio sem resposta da familia. Ja enviamos avisos anteriores. Por favor, justifique e confirme presenca ou ligue para secretaria imediatamente.",
    ),
    FollowupTemplate(
        template_id="fup_reforco_07",
        text="Atencao prioritaria - {school_name}: as faltas de {student_name} em maio estao sem regularizacao. Sem retorno, o aluno entra em protocolo de risco. Envie justificativa agora e ligue para a escola.",
    ),
    FollowupTemplate(
        template_id="fup_reforco_08",
        text="{parent_name}, precisamos de acao imediata. {student_name} (turma {class_name}) tem faltas recorrentes em maio sem justificativa valida. Responda com o motivo + ligue hoje para evitarmos medidas adicionais.",
    ),
    FollowupTemplate(
        template_id="fup_reforco_09",
        text="Comunicacao obrigatoria: {student_name} acumula faltas em maio sem retorno previo. Risco de evasao identificado. Favor retornar AGORA informando o motivo e providenciar ligacao para a direcao/escola.",
    ),
    FollowupTemplate(
        template_id="fup_reforco_10",
        text="Ultimo reforco antes de escalada: {student_name} ( {class_name} ) - mais de 2 faltas maio, sem retorno familiar. Responda esta mensagem com justificativa e ligue para a escola sem falta hoje. Protocolo de acompanhamento sera ativado.",
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
        campaign_name: str = "",
    ) -> tuple[str, str]:
        template = self._choose_template(
            campaign_id=campaign_id, unique_key=unique_key, campaign_name=campaign_name
        )
        message = template.text.format(
            parent_name=(parent_name or "Responsavel").strip(),
            student_name=(student_name or "Aluno(a)").strip(),
            class_name=(class_name or "nao informada").strip(),
            absence_days=(absence_days or "27/04/2026").strip(),
            school_name=self.school_name,
        )
        return template.template_id, message

    @staticmethod
    def _choose_template(
        *, campaign_id: str, unique_key: str, campaign_name: str = ""
    ) -> FollowupTemplate:
        digest = hashlib.sha256(f"{campaign_id}|{unique_key}".encode("utf-8")).hexdigest()
        normalized = (campaign_name or "").strip().lower()
        use_reforco = any(k in normalized for k in ["reforco", "reforço", "maio", "priorit"])
        templates = REFORCO_TEMPLATES if use_reforco else FOLLOWUP_TEMPLATES
        index = int(digest[:8], 16) % len(templates)
        return templates[index]

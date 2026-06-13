import hashlib
from dataclasses import dataclass


@dataclass(frozen=True)
class MessageTemplate:
    template_id: str
    text: str


OBMEP_TEMPLATES = [
    MessageTemplate(
        template_id="obmep_01",
        text="Olá {parent_name}, tudo bem? Amanhã (terça, 09/06) acontece a 1ª Fase da OBMEP 2026. A presença de {student_name} ({class_name}) é de extrema importância! A prova tem 20 questões e duração de 2h30, realizada na própria escola. Contamos com o seu apoio para garantir a presença dele(a)!"
    ),
    MessageTemplate(
        template_id="obmep_02",
        text="Prezado(a) {parent_name}, a {school_name} informa que amanhã, 9 de junho, será aplicada a 1ª Fase da OBMEP 2026. Pedimos que incentive o(a) aluno(a) {student_name} a comparecer e dar o seu melhor. A prova dura 2h30 e é realizada na própria escola. A presença é fundamental!"
    ),
    MessageTemplate(
        template_id="obmep_03",
        text="Olá, {parent_name}. Gostaríamos de lembrar que amanhã (terça, 09/06) teremos a 1ª Fase da OBMEP 2026 na {school_name}. É muito importante que o(a) {student_name} da turma {class_name} compareça para realizar a avaliação. A prova dura 2h30 e acontece no horário de aula."
    ),
    MessageTemplate(
        template_id="obmep_04",
        text="Atenção, {parent_name}: amanhã (09/06) é dia de OBMEP na {school_name}. O(a) estudante {student_name} fará a prova da 1ª fase (20 questões objetivas, 2h30 de duração) no próprio prédio escolar. Por favor, garanta que ele(a) não falte. A presença dele(a) é indispensável!"
    ),
    MessageTemplate(
        template_id="obmep_05",
        text="Olá {parent_name}, esperamos que esteja bem. Amanhã, 9 de junho, será realizada a 1ª Fase da OBMEP 2026. A participação de {student_name} (turma {class_name}) é essencial para o desenvolvimento escolar dele(a). A prova dura 2h30 na própria escola. Contamos com a presença dele(a)!"
    ),
    MessageTemplate(
        template_id="obmep_06",
        text="Responsável {parent_name}, reforçamos a importância da presença de {student_name} amanhã, terça-feira (09/06), para a realização da 1ª Fase da OBMEP 2026 na {school_name}. A prova tem duração de 2h30 e será aplicada no próprio horário de aula. Contamos com sua colaboração!"
    ),
]


class ObmepMessageCatalog:
    def __init__(self, school_name: str = "Escola Décia") -> None:
        self.school_name = (school_name or "Escola Décia").strip() or "Escola Décia"

    def build_message(
        self,
        *,
        parent_name: str,
        student_name: str,
        class_name: str,
        campaign_id: str,
        unique_key: str,
    ) -> tuple[str, str]:
        template = self._choose_template(campaign_id=campaign_id, unique_key=unique_key)
        return template.template_id, template.text.format(
            parent_name=(parent_name or "Responsável").strip(),
            school_name=self.school_name,
            student_name=(student_name or "Aluno(a)").strip(),
            class_name=self._normalize_class_name_short(class_name),
        )

    def _choose_template(self, *, campaign_id: str, unique_key: str) -> MessageTemplate:
        digest = hashlib.sha256(f"{campaign_id}|{unique_key}".encode("utf-8")).hexdigest()
        return OBMEP_TEMPLATES[int(digest[:8], 16) % len(OBMEP_TEMPLATES)]

    @staticmethod
    def _normalize_class_name_short(value: str) -> str:
        import re
        text = str(value or "").strip().upper()
        if not text:
            return "não informada"
        text = re.sub(r"^\s*TURMA\s+", "", text)
        match = re.search(r"\b([6-9])\s*ANO\b.*?\b(?:[6-9]\s*)?([A-Z])\b", text)
        if match:
            return f"{match.group(1)}º ano {match.group(2)}"
        match_short = re.search(r"\b([6-9])\s*ANO\s+([A-Z])\b", text)
        if match_short:
            return f"{match_short.group(1)}º ano {match_short.group(2)}"
        return text or "não informada"

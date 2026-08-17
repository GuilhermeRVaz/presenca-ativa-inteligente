"""
scripts/ingest_reuniao_pais_faq.py

Script para popular o FAQ estruturado da Reunião de Pais na tabela `busca_ativa_v2.school_knowledge`
da escola EE PEI Profa Décia (ID: aac99735-32cb-4615-b2cb-0be315f18374).
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

SCHOOL_ID = "aac99735-32cb-4615-b2cb-0be315f18374"

FAQ_ITEMS = [
    {
        "category": "LOGISTICA",
        "question": "Qual é a data, o horário de início e a duração prevista da reunião?",
        "answer": "A Reunião de Pais será realizada no dia 5 de agosto (quarta-feira), com início às 18h00 e término previsto entre 18h30 e 20h30."
    },
    {
        "category": "LOGISTICA",
        "question": "Como será o formato da reunião (presencial, híbrido ou totalmente online)?",
        "answer": "A reunião é 100% presencial, sendo fundamental a participação dos pais ou responsáveis no espaço da escola."
    },
    {
        "category": "LOGISTICA",
        "question": "Onde será a recepção e para qual espaço da escola os pais devem se dirigir ao chegar?",
        "answer": "A reunião será na EE PEI Professora Décia Lourdes Machado dos Santos, localizada na Rua Flósculo Franco do Amaral, nº 260, bairro Núcleo Habitacional Monsenhor Pasetto, Lins - SP. Haverá recepção no portão central com direcionamento até o refeitório."
    },
    {
        "category": "LOGISTICA",
        "question": "É necessário confirmar presença antecipadamente (e qual o prazo/canal para isso)?",
        "answer": "Sim. É muito importante confirmar a presença (responda 1) ou justificar a ausência (responda 2 ou informe o motivo com o nome do representante) por este canal de WhatsApp ou junto à secretaria."
    },
    {
        "category": "LOGISTICA",
        "question": "Haverá tolerância de horário para quem chegar atrasado devido ao trânsito ou trabalho?",
        "answer": "Contamos com a pontualidade de todos, mas haverá uma tolerância máxima de atraso de 15 minutos para não prejudicar o início da pauta."
    },
    {
        "category": "LOGISTICA",
        "question": "Posso levar meus filhos (alunos ou irmãos menores) comigo para a reunião?",
        "answer": "Não é recomendado trazer os estudantes ou irmãos menores. Contudo, se não tiver com quem deixá-los, a entrada será permitida desde que permaneçam acompanhados pelos responsáveis."
    },
    {
        "category": "LOGISTICA",
        "question": "A escola disponibilizará declaração ou atestado de comparecimento para o trabalho?",
        "answer": "Sim. Para os pais que comparecerem e precisarem justificar a ausência no trabalho, a escola fornecerá uma declaração de comparecimento no final da reunião."
    },
    {
        "category": "PEDAGOGICO",
        "question": "Qual será a pauta principal ou os temas centrais abordados neste encontro?",
        "answer": "Abordaremos: 1. Resultados e notas do 2º bimestre; 2. Comportamento, convivência e frequência; 3. Atualizações pedagógicas e currículo; 4. Acompanhamento de tarefas e uniforme; 5. Resultado da Copa da Escola, Eletivas, Clubes e Recuperação."
    },
    {
        "category": "PEDAGOGICO",
        "question": "Como os pais podem acompanhar o desempenho escolar e as notas dos alunos no dia a dia?",
        "answer": "Por meio do aplicativo/plataforma oficial da Secretaria da Educação, acompanhando o boletim e a frequência online."
    },
    {
        "category": "ATENDIMENTO",
        "question": "Qual é o canal oficial de comunicação entre a escola e a família para avisos e ocorrências?",
        "answer": "Os números de WhatsApp oficiais da escola, atendimento telefônico e recepção presencial na secretaria escolar."
    },
    {
        "category": "PEDAGOGICO",
        "question": "Como proceder caso o aluno precise faltar por motivos de saúde ou viagem?",
        "answer": "A comunicação antecipada é primordial. Em casos de problemas de saúde, é obrigatória a apresentação do atestado médico na secretaria."
    },
    {
        "category": "REGRAS",
        "question": "Quais são as diretrizes da escola em relação ao uso de celulares durante as aulas?",
        "answer": "De acordo com a legislação vigente, é expressamente proibido o uso de celulares e aparelhos eletrônicos nas dependências de ensino durante as aulas."
    },
    {
        "category": "PEDAGOGICO",
        "question": "Como funciona o suporte pedagógico e as tarefas de casa?",
        "answer": "Os pais devem acompanhar diariamente as tarefas. A escola disponibiliza ferramentas online como Sala do Futuro, Alura, Speak e outras plataformas de reforço."
    },
    {
        "category": "ATENDIMENTO",
        "question": "Como e quando os pais podem agendar um atendimento individual com os professores ou coordenação?",
        "answer": "A escola está sempre aberta, mas sugerimos o agendamento prévio com a secretaria para otimizar o atendimento com a gestão/coordenação."
    },
    {
        "category": "COMUNIDADE",
        "question": "De que forma a família pode se envolver mais ativamente nos projetos e eventos da escola?",
        "answer": "Participando das reuniões pedagógicas, eventos festivos, acompanhando as tarefas diárias e integrando a Associação de Pais e Mestres (APM) e órgãos colegiados."
    }
]


def run_ingestion():
    print(f"🚀 Iniciando ingestão de {len(FAQ_ITEMS)} itens de FAQ para a escola {SCHOOL_ID}...")
    repo = SupabaseRepository(timeout=30.0, attempts=3)
    client = repo.client

    try:
        rows_to_insert = [
            {
                "school_id": SCHOOL_ID,
                "category": item["category"],
                "question": item["question"],
                "answer": item["answer"],
                "is_active": True,
            }
            for item in FAQ_ITEMS
        ]

        # Inserir novos itens
        res = client.schema("busca_ativa_v2").table("school_knowledge").insert(rows_to_insert).execute()
        print(f"✅ Inseridos {len(res.data or [])} registros com sucesso em busca_ativa_v2.school_knowledge!")
        return True
    except Exception as exc:
        print(f"❌ Erro ao ingerir FAQ: {exc}")
        return False


if __name__ == "__main__":
    run_ingestion()

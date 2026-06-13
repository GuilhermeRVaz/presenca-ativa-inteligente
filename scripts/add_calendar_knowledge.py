import os
import sys
from dotenv import load_dotenv

# Ensure UTF-8 output
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

load_dotenv()

# We can reuse the Supabase library configuration from the app
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app.infrastructure.supabase.repositories import SupabaseRepository

SCHOOL_ID = "aac99735-32cb-4615-b2cb-0be315f18374"

calendar_items = [
    {
        "category": "schedules",
        "question": "Quando começam e terminam as férias de julho de 2026?",
        "answer": "As férias/recesso escolar de julho de 2026 para os estudantes começam no dia 07/07/2026 e vão até o dia 21/07/2026. Os dias 22 e 23 de julho são destinados ao planejamento escolar dos docentes (sem aulas para alunos). As aulas retornam oficialmente no dia 24/07/2026 com o início do 3º bimestre."
    },
    {
        "category": "schedules",
        "question": "Quando começa e termina o ano letivo de 2026?",
        "answer": "O ano letivo de 2026 da Escola Décia começou no dia 02/02/2026 e as aulas encerram-se no dia 18/12/2026 (com conselho de classe e formatura), totalizando os 200 dias letivos obrigatórios."
    },
    {
        "category": "schedules",
        "question": "Quais são as datas de início e fim de cada bimestre letivo em 2026?",
        "answer": "As datas dos bimestres para o ano letivo de 2026 são as seguintes:\n• 1º Bimestre: de 02/02/2026 a 22/04/2026 (50 dias letivos)\n• 2º Bimestre: de 23/04/2026 a 06/07/2026 (50 dias letivos)\n• 3º Bimestre: de 24/07/2026 a 02/10/2026 (50 dias letivos)\n• 4º Bimestre: de 05/10/2026 a 18/12/2026 (50 dias letivos)"
    },
    {
        "category": "schedules",
        "question": "Quando acontecem as reuniões de pais e responsáveis em 2026?",
        "answer": "As Reuniões de Pais e Responsáveis (RPR) ocorrem bimestralmente ao longo do ano letivo. As principais datas programadas incluem 25/02/2026 (início do ano) e 06/05/2026. Para confirmação da data de cada bimestre ou reuniões específicas de turma, recomenda-se contatar diretamente a coordenação pedagógica da escola."
    },
    {
        "category": "schedules",
        "question": "Quais são os feriados e recessos escolares em 2026?",
        "answer": "Os principais feriados e recessos sem aula em 2026 na escola são:\n• 01/01: Feriado Nacional (Confraternização Universal)\n• 16/02 a 20/02: Recesso de Carnaval e Planejamento Escolar\n• 03/04: Sexta-feira Santa\n• 21/04: Tiradentes\n• 01/05: Dia do Trabalho\n• 04/06 e 05/06: Corpus Christi e Ponto Facultativo\n• 09/07 e 10/07: Revolução Constitucionalista e Ponto Facultativo (emenda com o recesso)\n• 07/07 a 21/07: Recesso Escolar (Férias de Julho)\n• 07/09: Independência do Brasil\n• 12/10: Nossa Senhora Aparecida\n• 15/10 e 16/10: Dia do Professor e Recesso\n• 02/11: Finados\n• 15/11 e 20/11: Proclamação da República e Dia da Consciência Negra\n• A partir de 21/12: Recesso de final de ano"
    }
]

repository = SupabaseRepository(timeout=30.0, attempts=3)
client = repository.client

try:
    print(f"Adding {len(calendar_items)} calendar FAQ items to Supabase...")
    rows_to_insert = []
    for item in calendar_items:
        # Check if the question already exists to prevent duplication
        existing = client.schema("busca_ativa_v2").table("school_knowledge").select("id").eq("school_id", SCHOOL_ID).eq("question", item["question"]).execute()
        if existing.data:
            print(f"Skipping duplicate question: '{item['question']}'")
            continue
            
        rows_to_insert.append({
            "school_id": SCHOOL_ID,
            "category": item["category"],
            "question": item["question"],
            "answer": item["answer"],
            "is_active": True
        })
        
    if rows_to_insert:
        result = client.schema("busca_ativa_v2").table("school_knowledge").insert(rows_to_insert).execute()
        print(f"Successfully added {len(result.data)} calendar items.")
    else:
        print("No new items to add.")
except Exception as e:
    print(f"Error occurred: {e}", file=sys.stderr)
    sys.exit(1)

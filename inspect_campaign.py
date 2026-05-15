from app.infrastructure.supabase.repositories import SupabaseRepository
r = SupabaseRepository()

# Buscar campanha 29/04
c = r.client.schema('busca_ativa_v2').table('campaigns').select('*').eq('absence_days','29/04/2026').execute()
if c.data:
    camp = c.data[0]
    print(f'Campanha: {camp["name"]} (ID: {camp["id"]})')
    cid = camp['id']
else:
    print('Campanha não encontrada')
    cid = None

# Totais
s = r.client.schema('busca_ativa_v2').table('students').select('count', count='exact').execute()
print(f'Total students: {s.count}')
g = r.client.schema('busca_ativa_v2').table('guardians').select('count', count='exact').execute()
print(f'Total guardians: {g.count}')
sg = r.client.schema('busca_ativa_v2').table('student_guardians').select('count', count='exact').execute()
print(f'Total student_guardians (links): {sg.count}')

# Mensagens da campanha
if cid:
    msgs = r.client.schema('busca_ativa_v2').table('messages').select('*').eq('campaign_id', cid).limit(10).execute()
    print(f'\nMensagens na campanha (primeiras 10): {len(msgs.data)}')
    for m in msgs.data:
        print(f'  ID: {m["id"][:8]}... status={m["status"]} wa_jid={m["wa_jid"]}')

# Verificar alunos SEM guardian vinculado
if cid:
    from app.application.followup_campaign_v2 import get_students_for_campaign
    students = get_students_for_campaign(r, cid)
    print(f'\nAlunos elegíveis para campanha (função get_students_for_campaign): {len(students)}')
    for s in students[:5]:
        print(f'  RA={s.ra} nome={s.name} turma={s.class_name}')

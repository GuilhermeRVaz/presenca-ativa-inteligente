from app.infrastructure.supabase.repositories import SupabaseRepository
r = SupabaseRepository()

# Alunos no Excel que deveriam ter guardian
import openpyxl
from pathlib import Path
from app.core.config import settings

excel_path = Path(settings.project_root) / settings.consolidated_report_path
wb = openpyxl.load_workbook(excel_path, read_only=True, data_only=True)
ws = wb.active

# RA's do Excel
excel_ras = set()
for row in ws.iter_rows(min_row=2, values_only=True):
    ra_raw = str(row[3] or "").strip()
    if ra_raw:
        import re
        digits = re.sub(r"[^0-9]", "", ra_raw).lstrip("0")
        if len(digits) > 9: digits = digits[:-1]
        excel_ras.add(digits)

print(f'RAs no Excel: {len(excel_ras)}')

# Verificar quantos students têm guardians
students_with_guardians = r.client.schema('busca_ativa_v2').table('student_guardians').select('student_id', count='exact').execute()
print(f'Links student_guardians: {students_with_guardians.count}')

# Verificar guardians distintos
guardians = r.client.schema('busca_ativa_v2').table('guardians').select('id, phone_e164').execute()
print(f'Guardians distintos: {len(guardians.data)}')

wb.close()

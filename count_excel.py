import openpyxl
from pathlib import Path
from app.core.config import settings

excel_path = Path(settings.project_root) / settings.consolidated_report_path
wb = openpyxl.load_workbook(excel_path, read_only=True, data_only=True)
ws = wb.active
total = sum(1 for row in ws.iter_rows(min_row=2, values_only=True) if row[3])  # com RA
print(f'Total de linhas com RA: {total}')
wb.close()

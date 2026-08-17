"""
scripts/export_unconfirmed_markdown.py

Gera arquivo Markdown com o Diagnóstico Consolidado e as Tabelas de Busca Ativa.
"""
import json
import sys
from pathlib import Path

import io
if sys.platform.startswith("win"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

json_path = ROOT / "scripts" / "unconfirmed_report.json"
if not json_path.exists():
    print("❌ Arquivo unconfirmed_report.json não encontrado.")
    sys.exit(1)

with open(json_path, "r", encoding="utf-8") as f:
    records = json.load(f)

print(f"📌 Carregados {len(records)} registros de alunos não confirmados/justificados.")

justified = [r for r in records if r["intent"] == "JUSTIFICADO_AUSENTE"]
unconfirmed = [r for r in records if r["intent"] != "JUSTIFICADO_AUSENTE"]

print(f"• Justificados (Opção 2): {len(justified)}")
print(f"• Não Confirmados / Busca Ativa: {len(unconfirmed)}")

# Criar a saída formatada em Markdown
out_md = []
out_md.append("# 📊 Diagnóstico Consolidado e Tabelas de Busca Ativa — Reunião de Pais (5 de Agosto)\n")
out_md.append("Este relatório reúne os **resultados consolidados de todas as 7 turmas da escola** (6º A, 6º B, 7º A, 7º B, 8º A, 8º B e 9º A com deduplicação), acompanhados das tabelas nominais com **Telefones 1 e 2** para a equipe pedagógica realizar a busca ativa.\n")

# Tabela 1: Justificativas de Ausência (Opção 2)
out_md.append("## ⚠️ Tabela 1: Responsáveis que Justificaram Ausência (Opção 2)\n")
out_md.append("Alunos cujos responsáveis responderam com a **Opção 2** ou informaram motivos de impossibilidade (trabalho, viagem, saúde):\n\n")
out_md.append("| Nº | Nome do Aluno | Turma | Responsável | Telefone 1 | Telefone 2 | Motivo / Resposta do Pai |\n")
out_md.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |\n")

for idx, r in enumerate(justified, 1):
    t1 = r['tel1'] or "-"
    t2 = r['tel2'] or "-"
    body = r['body'].replace('\n', ' ') if r['body'] else "Informou Opção 2"
    out_md.append(f"| {idx} | **{r['student_name']}** | {r['class_name']} | {r['guardian_name']} | `{t1}` | `{t2}` | {body} |\n")

# Tabela 2: Sem Confirmação de Presença (Busca Ativa)
out_md.append("\n## 🔍 Tabela 2: Responsáveis Sem Confirmação de Presença (Busca Ativa Pendente)\n")
out_md.append("Alunos que receberam a convocação mas **ainda não responderam com o número 1** (inclui pendentes de resposta, dúvidas de secretaria e falhas no envio):\n\n")
out_md.append("| Nº | Nome do Aluno | Turma | Responsável | Telefone 1 | Telefone 2 | Status Atual |\n")
out_md.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |\n")

for idx, r in enumerate(unconfirmed, 1):
    t1 = r['tel1'] or "-"
    t2 = r['tel2'] or "-"
    status_label = "Aguardando Resposta (Enviado)"
    if r["intent"] == "DUVIDA_OUTROS":
        status_label = "Dúvida / Atendimento SAC"
    elif r["intent"] == "FALHA_ENVIO":
        status_label = "Falha no Envio (Número Inválido)"
    elif r["send_status"] == "pending":
        status_label = "Pendente de Envio"

    out_md.append(f"| {idx} | **{r['student_name']}** | {r['class_name']} | {r['guardian_name']} | `{t1}` | `{t2}` | {status_label} |\n")

report_text = "".join(out_md)

with open(ROOT / "scripts" / "relatorio_busca_ativa_completo.md", "w", encoding="utf-8") as f:
    f.write(report_text)

print("✅ Arquivo relatorio_busca_ativa_completo.md gerado com sucesso!")

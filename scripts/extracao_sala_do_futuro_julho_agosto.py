import argparse
import asyncio
import os
import sys
import glob
from datetime import datetime
from pathlib import Path
import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT_DIR = Path(__file__).resolve().parent.parent

def unificar_relatorios_julho_agosto():
    path = ROOT_DIR / "relatorios"
    arquivos = glob.glob(os.path.join(path, "Faltas_*.xlsx"))
    
    if not arquivos:
        print("\n⚠️ Nenhum arquivo de faltas encontrado para unificar.")
        return

    print("\n📊 Consolidador Sala do Futuro — Julho & Agosto/2026...")
    lista_df = []

    for arquivo in arquivos:
        nome_turma = os.path.basename(arquivo).replace("Faltas_", "").replace(".xlsx", "").replace("_", " ")
        try:
            raw_df = pd.read_excel(arquivo, header=None)
            header_idx = 0
            for index, row in raw_df.iterrows():
                valores = [str(v).strip().upper() for v in row.values if pd.notna(v)]
                if "NOME" in valores and "RA" in valores:
                    header_idx = index
                    break
            
            df = pd.read_excel(arquivo, header=header_idx)
            if not df.empty:
                df.insert(0, 'Turma', nome_turma)
                lista_df.append(df)
        except Exception as e:
            print(f"❌ Erro ao ler {nome_turma}: {e}")

    if lista_df:
        df_final = pd.concat(lista_df, ignore_index=True)
        nome_saida = os.path.join(path, "Relatorio_Consolidado_Julho_Agosto.xlsx")
        df_final.to_excel(nome_saida, index=False)
        print(f"✨ Arquivo consolidado criado com sucesso: {nome_saida}")
    else:
        print("⚠️ Não havia dados válidos para consolidar.")

async def run_extraction(months=[7, 8]):
    out_dir = ROOT_DIR / "relatorios"
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("⚠️ Playwright não instalado. Executando consolidação dos arquivos existentes...")
        unificar_relatorios_julho_agosto()
        return

    async with async_playwright() as p:
        print("Conectando ao Chrome na porta 9222...")
        try:
            browser = await p.chromium.connect_over_cdp("http://127.0.0.1:9222")
            page = browser.contexts[0].pages[0]
            await page.bring_to_front()
        except Exception as e:
            print(f"⚠️ Não foi possível conectar ao Chrome no 9222: {e}")
            print("Executando unificação dos arquivos de faltas existentes na pasta relatorios/...")
            unificar_relatorios_julho_agosto()
            return

        print("\nNavegando na SEDUC / Sala do Futuro para Julho e Agosto...")
        turmas = [
            "6° ANO 6A INTEGRAL 9H ANUAL", "6° ANO 6B INTEGRAL 9H ANUAL",
            "7° ANO 7A INTEGRAL 9H ANUAL", "7° ANO 7B INTEGRAL 9H ANUAL",
            "8° ANO 8A INTEGRAL 9H ANUAL", "8° ANO 8B INTEGRAL 9H ANUAL",
            "9° ANO 9A INTEGRAL 9H ANUAL"
        ]

        for mes in months:
            print(f"\n================ EXTRAINDO MÊS {mes:02d} ================")
            for turma_nome in turmas:
                print(f"--- Processando Mês {mes} | Turma: {turma_nome} ---")
                try:
                    await page.locator("#slMes").select_option(str(mes))
                    await asyncio.sleep(0.5)
                    await page.locator("#slTpConsulta").select_option("0")
                    await page.locator("button.botao-filtro").click()
                    await asyncio.sleep(4)

                    async with page.expect_download(timeout=30000) as download_info:
                        await page.locator("button.btn-downloads-mapao").filter(has=page.locator("img[src*='xls']")).click()

                    download = await download_info.value
                    nome_limpo = turma_nome.replace(" ", "_").replace("°", "")
                    caminho = out_dir / f"Faltas_Mes_{mes:02d}_{nome_limpo}.xlsx"
                    await download.save_as(caminho)
                    print(f"  -> Salvo: {caminho}")

                    await page.locator("button.btn-icon").filter(has_text="OK").click()
                    await asyncio.sleep(1)
                except Exception as err:
                    print(f"  -> Aviso/Erro no Mês {mes} ({turma_nome}): {err}")

        unificar_relatorios_julho_agosto()

def main():
    parser = argparse.ArgumentParser(description="Extração e consolidação Sala do Futuro (Julho/Agosto).")
    parser.add_argument("--months", nargs="+", type=int, default=[7, 8], help="Meses para extração (ex: --months 7 8)")
    args = parser.parse_args()
    asyncio.run(run_extraction(months=args.months))

if __name__ == "__main__":
    main()

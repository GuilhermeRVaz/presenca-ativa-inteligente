import argparse
import asyncio
import os
import glob
from datetime import datetime

import pandas as pd
from playwright.async_api import async_playwright

# --- FUNÇÃO PARA UNIFICAR OS ARQUIVOS (O CONSOLIDADO) ---
def unificar_relatorios():
    path = "relatorios"
    arquivos = glob.glob(os.path.join(path, "Faltas_*.xlsx"))
    
    if not arquivos:
        print("\n⚠️ Nenhum arquivo encontrado para unificar.")
        return

    print("\n📊 Gerando Relatório Consolidado e limpando cabeçalhos da SEDUC...")
    lista_df = []

    for arquivo in arquivos:
        nome_turma = os.path.basename(arquivo).replace("Faltas_", "").replace(".xlsx", "").replace("_", " ")
        try:
            # 1. Lê o arquivo "cru" para descobrir onde os dados realmente começam
            raw_df = pd.read_excel(arquivo, header=None)
            
            header_idx = 0
            # Procura a linha que contém "RA" e "NOME"
            for index, row in raw_df.iterrows():
                valores = [str(v).strip().upper() for v in row.values if pd.notna(v)]
                if "NOME" in valores and "RA" in valores:
                    header_idx = index
                    break
            
            # 2. Lê o arquivo novamente, mas agora informando a linha correta do cabeçalho
            df = pd.read_excel(arquivo, header=header_idx)

            # Só adiciona se o arquivo não estiver vazio
            if not df.empty:
                df.insert(0, 'Turma', nome_turma)
                lista_df.append(df)
        except Exception as e:
            print(f"❌ Erro ao ler {nome_turma}: {e}")

    if lista_df:
        df_final = pd.concat(lista_df, ignore_index=True)
        nome_saida = os.path.join(path, "Relatorio_Consolidado_BuscaAtiva.xlsx")
        df_final.to_excel(nome_saida, index=False)
        print(f"✨ PERFEITO! Arquivo consolidado e limpo criado: {nome_saida}")
    else:
        print("⚠️ Não havia dados válidos para consolidar.")

# --- FUNÇÃO PRINCIPAL DO ROBÔ ---
async def run(selected_month: int | None = None):
    if not os.path.exists("relatorios"):
        os.makedirs("relatorios")

    target_month = selected_month or datetime.now().month
    if target_month < 1 or target_month > 12:
        raise ValueError("O mes precisa estar entre 1 e 12.")

    async with async_playwright() as p:
        print("Conectando ao Chrome...")
        try:
            browser = await p.chromium.connect_over_cdp("http://127.0.0.1:9222")
            page = browser.contexts[0].pages[0]
            await page.bring_to_front()
        except Exception as e:
            print("❌ Erro ao conectar ao Chrome. Verifica se o CMD com a porta 9222 está aberto.")
            return

        print("\nIniciando navegação a partir da Home...")
        
        # Passos iniciais a partir do Home
        print("Clicando no Diário de Classe...")
        await page.locator("a.diario-classe-home").click()
        await asyncio.sleep(2)
        
        print("Clicando em Consulta...")
        await page.locator("a[href='/diario-classe__frequencia___consulta']").click()
        await asyncio.sleep(2)

        turmas = [
            "6° ANO 6A INTEGRAL 9H ANUAL", "6° ANO 6B INTEGRAL 9H ANUAL",
            "7° ANO 7A INTEGRAL 9H ANUAL", "7° ANO 7B INTEGRAL 9H ANUAL",
            "8° ANO 8A INTEGRAL 9H ANUAL", "8° ANO 8B INTEGRAL 9H ANUAL",
            "9° ANO 9A INTEGRAL 9H ANUAL"
        ]

        for turma_nome in turmas:
            print(f"\n--- Processando: {turma_nome} ---")
            try:
                # Selecionar Ensino (usando a ordem física estável dos inputs de dropdown)
                await page.locator("div.dropdown-input-container input").first.click()
                await page.get_by_text("ENSINO FUNDAMENTAL DE 9 ANOS", exact=True).click()
                await asyncio.sleep(1)

                # Selecionar Turma (usando a ordem física estável dos inputs de dropdown)
                await page.locator("div.dropdown-input-container input").nth(1).click()
                await asyncio.sleep(1)
                texto_busca = "°" + turma_nome.split("°")[1]
                await page.get_by_text(texto_busca, exact=False).click()
                await asyncio.sleep(1)

                # Abrir página da Turma
                await page.locator("a.item").filter(has_text=turma_nome.title()).first.click()
                await asyncio.sleep(2)

                # Seleciona o mes desejado e o tipo de consulta "Faltas".
                await page.locator("#slMes").select_option(str(target_month))
                await asyncio.sleep(0.5)
                await page.locator("#slTpConsulta").select_option("0")
                
                # Filtrar
                await page.locator("button.botao-filtro").click()
                await asyncio.sleep(5)

                # Download Excel
                print("Baixando Excel...")
                async with page.expect_download(timeout=60000) as download_info:
                    # Resolve strict mode clicando especificamente no botão que tem a imagem do Excel
                    await page.locator("button.btn-downloads-mapao").filter(has=page.locator("img[src*='xls']")).click()

                download = await download_info.value
                nome_limpo = turma_nome.replace(" ", "_").replace("°", "")
                caminho = f"relatorios/Faltas_{nome_limpo}.xlsx"
                await download.save_as(caminho)
                
                # Fechar popup e voltar
                await page.locator("button.btn-icon").filter(has_text="OK").click()
                await asyncio.sleep(1)
                await page.locator("button.botao-voltar").click()
                await asyncio.sleep(2)

            except Exception as e:
                print(f"⚠️ Erro na turma {turma_nome}: {e}")
                import traceback
                traceback.print_exc()

                try:
                    await page.locator("button.botao-voltar").click(timeout=3000)
                except:
                    await page.reload() # Se tudo falhar, dá refresh
                    await asyncio.sleep(3)

        print("\n✅ Todos os downloads concluídos!")
        
        # --- A MÁGICA FINAL: UNIFICAR TUDO ---
        unificar_relatorios()

def main():
    parser = argparse.ArgumentParser(
        description="Baixa relatorios de faltas da SEDUC e gera o consolidado.",
    )
    parser.add_argument(
        "--month",
        type=int,
        default=datetime.now().month,
        help="Mes numerico para selecionar na SEDUC (1-12). Padrao: mes atual.",
    )
    args = parser.parse_args()
    asyncio.run(run(selected_month=args.month))


if __name__ == "__main__":
    main()

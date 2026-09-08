"""
Script de verificação rápida do ambiente Playwright.
Testa a execução assíncrona do Chromium em modo headless.
"""
import asyncio
from playwright.async_api import async_playwright

async def verify_playwright():
    print("Iniciando verificação do Playwright...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto("https://example.com")
        title = await page.title()
        print(f"Sucesso! Pagina carregada com titulo: '{title}'")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(verify_playwright())

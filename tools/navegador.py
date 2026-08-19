"""Percorre o app no navegador de verdade e diz o que viu.

Existe porque o ``AppTest`` do Streamlit não alcança tudo. Ele executa a tela em
processo e pega exceção, widget que não monta e tipo que o Arrow recusa — mas
não vê o que só existe depois do render: markdown cru, rótulo cortado, tabela
que estoura a largura, unidade repetida em cada célula. Os dois últimos foram
achados aqui, e nenhum teste os teria pego.

Uso::

    python -m streamlit run app/main.py --server.port 8578 --server.headless true
    python tools/navegador.py 8578

Importa a WEG pela própria interface, percorre as doze telas e sai com código 1
se achou problema. As imagens ficam em ``tools/telas/``.
"""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

SAIDA = Path(__file__).parent / "telas"
problemas: list[str] = []

# Marcas de markdown que, aparecendo no texto renderizado, significam que alguém
# passou markdown a um widget que não o interpreta.
MARCAS_CRUAS = ("**", "###", "<div", "<span")


def esperar(pg, ms: int = 2500) -> None:
    """Espera o Streamlit terminar de desenhar, e não um tempo fixo."""
    pg.wait_for_selector("[data-testid='stAppViewContainer']", timeout=60000)
    try:
        pg.wait_for_selector(
            "[data-testid='stStatusWidget']", state="detached", timeout=120000
        )
    except Exception:
        pass
    pg.wait_for_timeout(ms)


def conferir(pg, nome: str) -> str:
    """O que dá para afirmar sobre uma tela desenhada, sem olhar para ela."""
    corpo = pg.locator("[data-testid='stAppViewContainer']").inner_text()

    excecoes = pg.locator("[data-testid='stException']")
    if excecoes.count():
        problemas.append(f"[{nome}] EXCEÇÃO: " + excecoes.first.inner_text()[:200])

    for marca in MARCAS_CRUAS:
        if marca in corpo:
            i = corpo.index(marca)
            problemas.append(
                f"[{nome}] markdown cru {marca!r}: ...{corpo[max(0, i - 70): i + 70].strip()}..."
            )

    if pg.evaluate(
        "() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 2"
    ):
        problemas.append(f"[{nome}] a página rola na horizontal")

    seguro = "".join(c if c.isalnum() else "_" for c in nome).strip("_")
    SAIDA.mkdir(exist_ok=True)
    pg.screenshot(path=str(SAIDA / f"{seguro}.png"))
    return corpo


def percorrer(porta: str) -> int:
    url = f"http://localhost:{porta}"
    with sync_playwright() as p:
        navegador = p.chromium.launch()
        pg = navegador.new_page(viewport={"width": 1600, "height": 1400})

        erros_js: list[str] = []
        pg.on("pageerror", lambda e: erros_js.append(str(e)))
        pg.on(
            "console",
            lambda m: erros_js.append(m.text) if m.type == "error" else None,
        )

        pg.goto(f"{url}/dados", wait_until="domcontentloaded", timeout=60000)
        esperar(pg, 7000)

        # Importa pela própria interface: driblar a tela e escrever no estado
        # testaria o motor, que já tem teste, e não a ligação entre os dois.
        pg.locator("[data-testid='stTab']", has_text="Buscar na CVM").click()
        pg.wait_for_timeout(2000)
        campo = pg.locator("input[aria-label='Empresa']").first
        campo.click()
        campo.fill("WEG")
        pg.wait_for_timeout(2500)
        pg.keyboard.press("Enter")
        esperar(pg, 4000)
        pg.locator("button", has_text="Importar da CVM").first.click()
        esperar(pg, 18000)

        conferir(pg, "Dados")

        # A navegação é pelo menu, e **não** por goto: recarregar a página abre
        # outra sessão do Streamlit e o histórico importado se perde. Uma
        # primeira versão deste script navegava por URL e achava toda tela vazia.
        itens = pg.locator("[data-testid='stSidebarNav'] a")
        telas = [
            " ".join(itens.nth(i).inner_text().split()[1:])
            for i in range(itens.count())
        ]
        print(f"telas ({len(telas)}): {', '.join(telas)}\n")

        for indice, nome in enumerate(telas):
            pg.locator("[data-testid='stSidebarNav'] a").nth(indice).click()
            esperar(pg, 4000)
            corpo = conferir(pg, nome)

            abas = pg.locator("[data-testid='stTab']")
            for i in range(abas.count()):
                rotulo = abas.nth(i).inner_text().strip()
                abas.nth(i).click()
                pg.wait_for_timeout(1200)
                conferir(pg, f"{nome} - {rotulo}")

            grades = pg.locator('[data-testid="stDataFrame"]').count()
            print(f"  {nome:24s} {len(corpo):6d} caracteres, {grades:2d} tabelas")

        navegador.close()

    unicos = sorted({e for e in erros_js if "favicon" not in e.lower()})
    if unicos:
        print(f"\nerros de JS/console ({len(unicos)}):")
        for e in unicos[:10]:
            print(f"   {e[:160]}")

    if problemas:
        print(f"\nPROBLEMAS ({len(problemas)}):")
        for pr in problemas:
            print(f"   {pr}")
        return 1
    print("\nnenhum problema nas telas percorridas")
    return 0


if __name__ == "__main__":
    raise SystemExit(percorrer(sys.argv[1] if len(sys.argv) > 1 else "8501"))

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
# Prefixo das imagens, para uma passada nao sobrescrever a outra.
PREFIXO = ""
problemas: list[str] = []

# Marcas de markdown que, aparecendo no texto renderizado, significam que alguém
# passou markdown a um widget que não o interpreta.
MARCAS_CRUAS = ("**", "###", "<div", "<span")


def esperar(pg, ms: int = 2500, onde: str = "") -> None:
    """Espera o Streamlit terminar de desenhar, e não um tempo fixo.

    **O `except` daqui engolia o caso que mais importa.** Quando o app nao
    termina dentro do prazo, a varredura seguia adiante e lia telas em meio a
    renderizacao -- devolvendo contagens que parecem perda de conteudo e nao
    sao. Visto na passada do ano movel: Qualitativo saiu com **1.065**
    caracteres numa execucao e **3.883** na seguinte, com o mesmo codigo e os
    mesmos dados, so porque a primeira pegou o app ainda desenhando.

    Contagem que depende da velocidade da maquina e pior que contagem nenhuma:
    ela manda procurar defeito onde nao ha, e treina quem le a ignorar a
    variacao -- inclusive a verdadeira. Agora vira problema declarado.
    """
    pg.wait_for_selector("[data-testid='stAppViewContainer']", timeout=60000)
    try:
        pg.wait_for_selector(
            "[data-testid='stStatusWidget']", state="detached", timeout=120000
        )
    except Exception:
        problemas.append(
            f"[{onde or 'app'}] o Streamlit nao terminou de desenhar em 120s -- "
            "as contagens abaixo descrevem uma tela pela metade"
        )
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

    # **Tabela com cabeçalho e sem número.** A árvore publicada saía assim numa
    # série trimestral -- 34 linhas, zero colunas -- e nada acusava: o script
    # contava caracteres, e o rótulo das contas já enche a tela. Uma tabela de
    # demonstração com uma coluna só (a do rótulo) é sempre defeito: ou a leitura
    # perdeu os períodos, ou a tela os filtrou fora.
    vazias = pg.evaluate(
        """() => Array.from(document.querySelectorAll('.df-publicada table'))
                .filter(t => t.querySelectorAll('thead th').length < 2).length"""
    )
    if vazias:
        problemas.append(f"[{nome}] {vazias} tabela(s) de demonstração sem coluna de período")

    seguro = "".join(c if c.isalnum() else "_" for c in nome).strip("_")
    SAIDA.mkdir(exist_ok=True)
    pg.screenshot(path=str(SAIDA / f"{PREFIXO}{seguro}.png"))
    return corpo


# As tres leituras do tempo, e o rotulo de cada uma no radio da tela de Dados.
# `None` e a anual: ela e o padrao e nao pede clique nenhum.
VISOES = {
    "anual": None,
    "trimestral": "Trimestral (isolado)",
    "movel": "Ano móvel rolante",
}


def percorrer(porta: str, trimestral: bool = False, visao: str = "anual") -> int:
    global PREFIXO
    # `trimestral=True` continua funcionando: ele e a forma antiga de pedir a
    # mesma coisa, e ha chamada dele no workflow.
    if trimestral:
        visao = "trimestral"
    if visao not in VISOES:
        print(f"visao desconhecida: {visao!r}. Use uma de {sorted(VISOES)}.")
        return 2
    PREFIXO = f"{visao}_" if visao != "anual" else ""
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
        # "Failed to load resource: 404" sem dizer **qual** recurso nao dirige
        # atencao nenhuma -- e a mesma queixa que este projeto tem de "nao fecha"
        # sem tamanho. O status e a URL vem junto.
        pg.on(
            "response",
            lambda r: erros_js.append(f"HTTP {r.status} em {r.url}")
            if r.status >= 400
            else None,
        )

        # Entra pela **raiz**, e nao por `/dados`: com a URL numa subpagina o
        # navegador resolve `_stcore/host-config` e `_stcore/health` relativos a
        # ela e recebe 404 nos dois. Nao quebra nada, mas enche a lista de erros
        # de console com um falso positivo permanente -- e lista de alarme que
        # sempre tem alarme treina quem le a ignorar.
        pg.goto(url, wait_until="domcontentloaded", timeout=60000)
        esperar(pg, 7000)
        pg.locator("[data-testid='stSidebarNav'] a", has_text="Dados").first.click()
        esperar(pg, 4000)

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
        rotulo_da_visao = VISOES[visao]
        if rotulo_da_visao is not None:
            # A serie trimestral tem colunas **propositalmente vazias** -- caixa
            # e balanco do exercicio anterior nao existem no ITR --, e e
            # exatamente esse tipo de coisa que se le errado na tela sem
            # ninguem olhar. Ate aqui ela so fora conferida por medicao.
            #
            # E o **ano movel** e a leitura que o app recomenda quando recusa a
            # de cima -- era a unica das tres que nunca tinha sido percorrida na
            # tela, e mandar o usuario para uma leitura nao percorrida e o pior
            # dos tres casos.
            pg.get_by_text(rotulo_da_visao, exact=True).first.click()
            pg.wait_for_timeout(1500)

        pg.locator("button", has_text="Importar da CVM").first.click()
        # O ano movel monta uma coluna por trimestre de **tres ITRs**, cada uma
        # por `importar_ltm`: e de longe a leitura mais cara das tres.
        esperar(pg, 60000 if visao == "movel" else 25000, onde=f"importar {visao}")

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
    # `--trimestral` e `--movel` percorrem as duas series do ITR em vez da DFP
    # anual. Sao passadas separadas e nao uma opcao dentro do mesmo laco:
    # importar troca o estado da sessao inteira, e conferir duas na mesma
    # sessao esconderia qual delas produziu a tela.
    argumentos = [a for a in sys.argv[1:] if not a.startswith("--")]
    escolhida = "anual"
    if "--trimestral" in sys.argv:
        escolhida = "trimestral"
    elif "--movel" in sys.argv:
        escolhida = "movel"
    raise SystemExit(
        percorrer(argumentos[0] if argumentos else "8501", visao=escolhida)
    )

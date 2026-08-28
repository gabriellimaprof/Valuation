"""Mede o contraste real dos componentes da tela de Qualitativo, no modo escuro.

**Contraste e propriedade de renderizacao**, e nao de paleta: o teste de cor
passa porque as cores sao "as da paleta", e mesmo assim o par frente/fundo pode
reprovar. O revamp ja pagou isso uma vez -- tres pares abaixo de 4,5:1 que so
apareceram medindo no navegador.

A tela de Qualitativo estreia dois componentes que o revamp nunca mediu: o
**expander** (o cabecalho de cada pergunta) e o **text_area** (o campo de
resposta, com placeholder). Eles vem do Streamlit e usam tokens do tema, entao
nao passam pelo CSS do app -- razao a mais para medir em vez de supor.

Uso, com o app rodando em modo escuro::

    python -m streamlit run app/main.py --server.port 8700 \\
        --server.headless true --theme.base dark
    python tools/contraste_no_escuro.py 8700
"""

from __future__ import annotations

import sys

from playwright.sync_api import sync_playwright

# WCAG AA para texto normal. A tela usa corpos de 0,875rem a 1rem, entao vale
# este limite e nao o de texto grande.
MINIMO = 4.5


def _canal(v: float) -> float:
    v = v / 255
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


def _luminancia(rgb: tuple[float, float, float]) -> float:
    r, g, b = (_canal(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contraste(frente: tuple, fundo: tuple) -> float:
    a, b = _luminancia(frente), _luminancia(fundo)
    claro, escuro = max(a, b), min(a, b)
    return (claro + 0.05) / (escuro + 0.05)


def _rgb(texto: str) -> tuple[float, float, float] | None:
    """Converte ``rgb(r, g, b)`` ou ``rgba(...)`` do getComputedStyle."""
    if not texto or "rgb" not in texto:
        return None
    numeros = texto[texto.index("(") + 1 : texto.index(")")].split(",")
    try:
        valores = [float(n.strip()) for n in numeros[:3]]
    except ValueError:
        return None
    # Alfa zero e "transparente": o fundo de verdade e o do elemento atras.
    if len(numeros) > 3 and float(numeros[3].strip()) == 0:
        return None
    return tuple(valores)


def _fundo_efetivo(pg, seletor: str) -> tuple | None:
    """Sobe a arvore ate achar um fundo opaco -- o que o olho de fato ve."""
    return pg.evaluate(
        """(sel) => {
            let no = document.querySelector(sel);
            while (no) {
                const cor = getComputedStyle(no).backgroundColor;
                if (cor && !cor.includes('rgba(0, 0, 0, 0)')) return cor;
                no = no.parentElement;
            }
            return getComputedStyle(document.body).backgroundColor;
        }""",
        seletor,
    )


def medir(porta: str, esquema: str = "dark") -> int:
    url = f"http://localhost:{porta}"
    problemas: list[str] = []

    with sync_playwright() as p:
        navegador = p.chromium.launch()
        # `color_scheme` alem do `--theme.base dark`: sem ele o Chromium anuncia
        # preferencia clara e componente que resolve por `prefers-color-scheme`
        # renderiza no tema errado -- que e justamente o que se quer medir.
        # O esquema do navegador tem de acompanhar o `--theme.base` do servidor.
        # Deixa-lo fixo em `dark` fazia a passada "clara" devolver os mesmos
        # numeros da escura -- um teste que nao testava, e que so apareceu porque
        # os dois resultados sairam identicos ate o centesimo.
        pg = navegador.new_page(
            viewport={"width": 1600, "height": 1400}, color_scheme=esquema
        )
        pg.goto(f"{url}/dados", wait_until="domcontentloaded", timeout=60000)
        pg.wait_for_selector("[data-testid='stAppViewContainer']", timeout=60000)
        pg.wait_for_timeout(7000)

        # **Importa pela interface e navega pelo menu**, nunca por `goto`:
        # recarregar a pagina abre outra sessao do Streamlit, o historico se
        # perde e a tela de Qualitativo devolve o aviso de "importe primeiro" --
        # sem expander e sem campo, que foi exatamente o que aconteceu na
        # primeira versao deste script.
        pg.locator("[data-testid='stTab']", has_text="Buscar na CVM").click()
        pg.wait_for_timeout(2000)
        campo = pg.locator("input[aria-label='Empresa']").first
        campo.click()
        campo.fill("WEG")
        pg.wait_for_timeout(2500)
        pg.keyboard.press("Enter")
        pg.wait_for_timeout(4000)
        pg.locator("button", has_text="Importar da CVM").first.click()
        pg.wait_for_timeout(20000)

        pg.locator("[data-testid='stSidebarNav'] a", has_text="Qualitativo").click()
        pg.wait_for_timeout(6000)

        # Os alvos incluem os **dois elementos de menor contraste por desenho** —
        # o placeholder do campo e o texto da legenda. Medir só o corpo do texto
        # daria a resposta fácil: ele é branco puro e passa em qualquer fundo.
        alvos = [
            ("cabeçalho do expander", "[data-testid='stExpander'] summary"),
            ("texto do bloco", "[data-testid='stExpander'] li"),
            ("campo de resposta", "textarea"),
            # **Este numero nao e confiavel, e fica declarado.**
            # `getComputedStyle(el, '::placeholder')` devolveu a cor herdada
            # (branco puro) em vez da regra que o Streamlit aplica, e a
            # opacidade veio 1 -- ou seja, a atenuacao que se ve na tela vem de
            # algum lugar que esta leitura nao alcanca. Medir o placeholder de
            # verdade pede amostragem de pixel na imagem, que este script nao
            # faz. Fica na lista para nao sumir da vista.
            ("placeholder do campo (nao confiavel)", "textarea::placeholder"),
            ("legenda (caption)", "[data-testid='stCaptionContainer'] p"),
        ]
        print(f"{'elemento':26s} {'frente':18s} {'fundo':18s} {'contraste':>10s}")
        print("-" * 78)
        for nome, seletor in alvos:
            # `::placeholder` e pseudo-elemento: `locator` nao o enxerga, e a cor
            # so sai passando o pseudo para o `getComputedStyle`.
            base, _, pseudo = seletor.partition("::")
            if pg.locator(base).count() == 0:
                print(f"{nome:26s} nao encontrado")
                continue
            estilo = pg.evaluate(
                """([s, p]) => {
                    const e = getComputedStyle(document.querySelector(s), p || null);
                    return {cor: e.color, opacidade: e.opacity};
                }""",
                [base, pseudo or None],
            )
            frente = _rgb(estilo["cor"])
            fundo = _rgb(_fundo_efetivo(pg, base))
            # **Opacidade e o que atenua o placeholder**, e nao a cor: ele sai
            # branco puro no `color` e cinza na tela. Medir sem compor daria um
            # contraste que ninguem ve -- exatamente o erro que este script
            # existe para nao cometer.
            if frente is not None and fundo is not None:
                try:
                    alfa = float(estilo["opacidade"])
                except (TypeError, ValueError):
                    alfa = 1.0
                if alfa < 1:
                    frente = tuple(
                        f * alfa + b * (1 - alfa) for f, b in zip(frente, fundo)
                    )
            if frente is None or fundo is None:
                print(f"{nome:26s} cor nao legivel")
                continue
            razao = contraste(frente, fundo)
            marca = "" if razao >= MINIMO else "  <-- REPROVA"
            print(
                f"{nome:26s} {str(tuple(int(c) for c in frente)):18s} "
                f"{str(tuple(int(c) for c in fundo)):18s} {razao:>9.2f}{marca}"
            )
            if razao < MINIMO and "nao confiavel" not in nome:
                problemas.append(f"{nome}: {razao:.2f} contra o mínimo de {MINIMO}")

        pg.screenshot(path=f"tools/telas/qualitativo_{esquema}.png", full_page=False)
        navegador.close()

    print()
    if problemas:
        print(f"REPROVAM ({len(problemas)}):")
        for x in problemas:
            print(f"   {x}")
        return 1
    print(f"todos os pares acima de {MINIMO}:1")
    return 0


if __name__ == "__main__":
    argumentos = [a for a in sys.argv[1:] if not a.startswith("--")]
    raise SystemExit(
        medir(
            argumentos[0] if argumentos else "8501",
            "light" if "--claro" in sys.argv else "dark",
        )
    )

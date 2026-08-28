"""Mede o contraste real dos componentes do app, nos dois modos.

**Contraste e propriedade de renderizacao**, e nao de paleta: o teste de cor
passa porque as cores sao "as da paleta", e mesmo assim o par frente/fundo pode
reprovar. O revamp ja pagou isso uma vez -- tres pares abaixo de 4,5:1 que so
apareceram medindo no navegador.

Os alvos sao os componentes do Streamlit que **nao passam pelo CSS do app** e
por isso escapam da validacao da paleta: expander, `text_area`, legenda e o
placeholder. Eles aparecem em varias telas, entao o script percorre as telas e
guarda o **pior par de cada elemento** -- e o que reprova que importa.

Uso, com o app rodando::

    python -m streamlit run app/main.py --server.port 8700 \\
        --server.headless true --theme.base dark
    python tools/contraste.py 8700            # escuro
    python tools/contraste.py 8700 --claro    # claro (com --theme.base light)

Tres armadilhas viraram comentario aqui, porque nenhuma delas da erro: `goto`
abre sessao nova, o esquema do navegador tem de acompanhar o `--theme.base`, e o
placeholder **nao se le por `getComputedStyle`**.
"""

from __future__ import annotations

import io
import sys
from collections import Counter

from playwright.sync_api import sync_playwright

# WCAG AA para texto normal. As telas usam corpos de 0,74rem a 1rem, entao vale
# este limite e nao o de texto grande.
MINIMO = 4.5
# Acima do minimo mas perto dele. **Nao reprova** -- reprovar aqui seria pinar um
# numero, e o padrao e o AA. Serve para a estreiteza aparecer: medido, o
# placeholder fica em 4,99 e a legenda em 5,12 no modo claro, e um passo mais
# claro no tema derruba os dois sem nada acusar.
ESTREITO = 5.5

# Telas percorridas. Sao as que trazem os componentes de risco; percorrer as
# treze custaria minutos para repetir os mesmos pares.
TELAS = ("Dados", "Histórico", "Premissas", "Valor", "Qualitativo")

# Os alvos incluem os elementos de **menor contraste por desenho** -- legenda e
# placeholder. Medir so o corpo do texto daria a resposta facil: ele e branco
# puro (ou preto puro) e passa em qualquer fundo.
# `pixel=True` so onde o metodo foi **validado**: texto simples, sem borda,
# fundo chapado. Generalizar a amostragem para qualquer elemento produziu falso
# positivo duas vezes seguidas, e as duas ficaram registradas em
# `_cores_do_elemento` -- num cabecalho com borda a cor "mais distante do fundo"
# e a **borda**, e o par sai em 1,4 como se o texto tivesse sumido. Onde nao ha
# validacao, vale a leitura por estilo, que erra para o lado de superestimar.
ALVOS = (
    ("cabeçalho do expander", "[data-testid='stExpander'] summary", False),
    ("texto do expander", "[data-testid='stExpander'] li", False),
    ("campo de texto", "textarea", False),
    ("legenda (caption)", "[data-testid='stCaptionContainer'] p", True),
    # **A tabela publicada usa o CSS do app**, e os testes dela leem a paleta --
    # nao o pixel. Sao os pares que o revamp ja reprovou uma vez: o cabecalho
    # (branco sobre azul), o nivel 5 (o mais fraco da arvore) e o negativo sobre
    # a tinta do subtotal. Se algum voltar a cair, cai aqui.
    ("tabela: cabeçalho", ".df-publicada th", False),
    ("tabela: nível 5", ".df-publicada tr.n5 td", False),
    ("tabela: negativo", ".df-publicada td.negativo", False),
    ("tabela: subtotal (n2)", ".df-publicada tr.n2 td", False),
)


def _canal(v: float) -> float:
    v = v / 255
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


def _luminancia(rgb) -> float:
    r, g, b = (_canal(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contraste(frente, fundo) -> float:
    a, b = _luminancia(frente), _luminancia(fundo)
    claro, escuro = max(a, b), min(a, b)
    return (claro + 0.05) / (escuro + 0.05)


def _rgb(texto: str):
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


def _fundo_efetivo(pg, seletor: str):
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


def _cores_do_elemento(locator):
    """Fundo e frente de um elemento, **pela imagem**.

    Vale para qualquer elemento de texto simples, e nao so para o placeholder:
    a leitura por `getComputedStyle` devolve a cor declarada, e o que o olho ve
    e o pixel depois de opacidade, mistura e antialiasing. No placeholder a
    diferenca foi de 15,73 para 6,39 -- razao suficiente para desconfiar dos
    demais em vez de supor que so ele mentia.

    O **fundo** e a cor mais frequente (o elemento e quase todo fundo) e a
    **frente** e a mais distante dele em luminancia entre as que aparecem o
    bastante para nao ser transicao de traco.
    """
    try:
        from PIL import Image
    except ImportError:
        return None
    # **Sem texto visivel nao ha o que amostrar**, e ignorar isso produz falso
    # positivo: numa celula quase vazia a cor "mais distante do fundo" e a
    # **borda**, e o par sai em 1,48 como se o negativo tivesse sumido. Foi o
    # que aconteceu na primeira medicao da tabela publicada -- o mesmo seletor
    # media 6,27 noutra tela, onde a celula tinha numero dentro.
    try:
        if not (locator.inner_text() or "").strip():
            return None
        bruto = locator.screenshot()
    except Exception:  # noqa: BLE001 -- elemento fora de vista ou sem caixa
        return None

    imagem = Image.open(io.BytesIO(bruto)).convert("RGB")
    dados = imagem.tobytes()
    cores = Counter(
        (dados[i], dados[i + 1], dados[i + 2]) for i in range(0, len(dados), 3)
    )
    if len(cores) < 2:
        return None
    fundo = cores.most_common(1)[0][0]
    # 30 pixels: acima do respingo de antialiasing e abaixo do traco de letra
    # numa caixa de texto simples. **Tentei torna-lo proporcional a area e
    # piorou** -- em elemento grande, meio por cento da area e mais do que o
    # miolo da letra ocupa, e a escolha caia na borda. O limiar fixo funciona no
    # caso para o qual este metodo esta validado, e por isso `ALVOS` declara
    # onde ele vale.
    candidatos = [c for c, n in cores.items() if n >= 30 and c != fundo]
    if not candidatos:
        return None
    frente = max(candidatos, key=lambda c: abs(_luminancia(c) - _luminancia(fundo)))
    return contraste(frente, fundo), frente, fundo


def _placeholder_por_pixel(pg):
    """O contraste do placeholder, **amostrando a imagem**.

    `getComputedStyle(el, '::placeholder')` devolve a cor herdada -- branco puro
    no escuro -- e opacidade 1, entao a atenuacao que se ve na tela vem de onde
    essa leitura nao alcanca. O jeito de medir o que o olho ve e olhar o pixel.

    O metodo: foto do proprio `textarea` vazio, contagem de cores, e duas
    escolhas. O **fundo** e a cor mais frequente, porque o campo e quase todo
    fundo. A **frente** e a cor mais distante dele em luminancia entre as que
    aparecem o bastante para nao ser antialiasing -- o miolo da letra. Cores com
    contagem minuscula sao borda arredondada e transicao de traco, e entrariam
    como ruido.

    Devolve ``None`` quando nao ha campo vazio na tela: com texto digitado o que
    se mede e o texto, e nao o placeholder.
    """
    try:
        from PIL import Image
    except ImportError:
        return None

    campos = pg.locator("textarea")
    for i in range(min(campos.count(), 4)):
        campo = campos.nth(i)
        try:
            if campo.input_value().strip():
                continue  # tem texto: nao e placeholder
            bruto = campo.screenshot()
        except Exception:  # noqa: BLE001 -- campo fora de vista
            continue

        imagem = Image.open(io.BytesIO(bruto)).convert("RGB")
        cores = Counter(imagem.convert('RGB').tobytes()[i:i+3]
                        for i in range(0, len(imagem.tobytes()), 3))
        cores = Counter({tuple(k): v for k, v in cores.items()})
        if len(cores) < 2:
            continue
        fundo = cores.most_common(1)[0][0]
        # 30 pixels: acima do respingo de antialiasing e abaixo de qualquer
        # traco de letra numa caixa desse tamanho.
        candidatos = [c for c, n in cores.items() if n >= 30 and c != fundo]
        if not candidatos:
            continue
        frente = max(
            candidatos, key=lambda c: abs(_luminancia(c) - _luminancia(fundo))
        )
        return contraste(frente, fundo), frente, fundo
    return None


def _com_mais_texto(pg, seletor: str):
    """O elemento com mais texto entre os que casam o seletor.

    `.first` pega o primeiro da pagina, que numa tabela costuma ser a celula
    mais curta -- e celula curta da pouco pixel de letra para amostrar. O que se
    quer medir e o caso tipico, e nao o primeiro que aparece.
    """
    itens = pg.locator(seletor)
    melhor, tamanho = itens.first, -1
    for i in range(min(itens.count(), 12)):
        try:
            texto = (itens.nth(i).inner_text() or "").strip()
        except Exception:  # noqa: BLE001
            continue
        if len(texto) > tamanho:
            melhor, tamanho = itens.nth(i), len(texto)
    return melhor


def _medir_a_tela(pg) -> list[tuple]:
    """Os pares frente/fundo desta tela, para os componentes de risco."""
    resultados = []
    # **Estes numeros leem a cor computada, e ela pode superestimar.** O
    # placeholder e a prova: `getComputedStyle` dizia 15,73 e o pixel diz 6,39 --
    # a atenuacao vinha de onde a leitura de estilo nao alcanca. Onde o valor
    # importar de verdade, amostre o pixel, como `_placeholder_por_pixel` faz.
    for nome, seletor, por_pixel in ALVOS:
        if pg.locator(seletor).count() == 0:
            continue
        estilo = pg.evaluate(
            """(s) => {
                const e = getComputedStyle(document.querySelector(s));
                return {cor: e.color, opacidade: e.opacity};
            }""",
            seletor,
        )
        frente = _rgb(estilo["cor"])
        fundo = _rgb(_fundo_efetivo(pg, seletor))
        if frente is None or fundo is None:
            continue
        # Opacidade compoe a cor: texto branco a 60% num fundo escuro e cinza, e
        # medir sem compor daria um contraste que ninguem ve.
        try:
            alfa = float(estilo["opacidade"])
        except (TypeError, ValueError):
            alfa = 1.0
        if alfa < 1:
            frente = tuple(f * alfa + b * (1 - alfa) for f, b in zip(frente, fundo))

        # **O pixel manda quando os dois discordam.** Ele e o que o olho ve; o
        # estilo e o que o CSS declara. Onde nao da para fotografar (elemento
        # sem caixa, fora de vista), fica o estilo -- com o valor de antes, e
        # nao com nenhum.
        por_estilo = contraste(frente, fundo)
        amostra = (
            _cores_do_elemento(_com_mais_texto(pg, seletor)) if por_pixel else None
        )
        if amostra is not None:
            razao, frente, fundo = amostra
        else:
            razao = por_estilo
        # A discordancia vai numa coluna, e **nao no nome**: mudar o rotulo
        # criava duas entradas para o mesmo elemento -- uma por tela que
        # discordava --, e o "pior par de cada elemento" deixava de ser um.
        resultados.append((nome, razao, frente, fundo, por_estilo))

    amostra = _placeholder_por_pixel(pg)
    if amostra is not None:
        razao, frente, fundo = amostra
        resultados.append(("placeholder", razao, frente, fundo, float("nan")))
    return resultados


def medir(porta: str, esquema: str = "dark") -> int:
    url = f"http://localhost:{porta}"
    problemas: list[str] = []

    with sync_playwright() as p:
        navegador = p.chromium.launch()
        # O esquema do navegador tem de acompanhar o `--theme.base` do servidor.
        # Deixa-lo fixo em `dark` fazia a passada "clara" devolver os mesmos
        # numeros da escura -- um teste que nao testava, e que so apareceu
        # porque os dois resultados sairam identicos ate o centesimo.
        pg = navegador.new_page(
            viewport={"width": 1600, "height": 1400}, color_scheme=esquema
        )
        pg.goto(f"{url}/dados", wait_until="domcontentloaded", timeout=60000)
        pg.wait_for_selector("[data-testid='stAppViewContainer']", timeout=60000)
        pg.wait_for_timeout(7000)

        # **Importa pela interface e navega pelo menu**, nunca por `goto`:
        # recarregar a pagina abre outra sessao do Streamlit, o historico se
        # perde e as telas devolvem o aviso de "importe primeiro" -- sem
        # expander e sem campo, que foi o que aconteceu na primeira versao.
        pg.locator("[data-testid='stTab']", has_text="Buscar na CVM").click()
        pg.wait_for_timeout(2000)
        campo = pg.locator("input[aria-label='Empresa']").first
        campo.click()
        campo.fill("WEG")
        pg.wait_for_timeout(2500)
        pg.keyboard.press("Enter")
        pg.wait_for_timeout(4000)
        pg.locator("button", has_text="Importar da CVM").first.click()
        pg.wait_for_timeout(22000)

        # O pior par de cada elemento, entre as telas: o mesmo componente
        # aparece em varias, e o que reprova e o que importa.
        piores: dict[str, tuple] = {}
        for tela in TELAS:
            alvo = pg.locator("[data-testid='stSidebarNav'] a", has_text=tela)
            if alvo.count() == 0:
                continue
            alvo.first.click()
            pg.wait_for_timeout(5000)
            for nome, razao, frente, fundo, por_estilo in _medir_a_tela(pg):
                if nome not in piores or razao < piores[nome][0]:
                    piores[nome] = (razao, frente, fundo, tela, por_estilo)

        print(
            f"{'elemento':24s} {'tela':13s} {'frente':17s} {'fundo':17s} "
            f"{'razão':>7s} {'estilo':>8s}"
        )
        print("-" * 92)
        for nome, (razao, frente, fundo, tela, por_estilo) in sorted(
            piores.items(), key=lambda kv: kv[1][0]
        ):
            if razao < MINIMO:
                marca = "  <-- REPROVA"
            elif razao < ESTREITO:
                marca = "  <-- margem estreita"
            else:
                marca = ""
            estilo = (
                f"{por_estilo:>8.2f}"
                if por_estilo == por_estilo and abs(por_estilo - razao) >= 1.0
                else " " * 8
            )
            print(
                f"{nome:24s} {tela:13s} "
                f"{str(tuple(int(c) for c in frente)):17s} "
                f"{str(tuple(int(c) for c in fundo)):17s} "
                f"{razao:>6.2f} {estilo}{marca}"
            )
            if razao < MINIMO:
                problemas.append(
                    f"{nome} em {tela}: {razao:.2f} contra o mínimo de {MINIMO}"
                )

        pg.screenshot(path=f"tools/telas/contraste_{esquema}.png", full_page=False)
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

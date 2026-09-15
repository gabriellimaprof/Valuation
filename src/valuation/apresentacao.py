"""O material do comite: o mesmo valuation, na forma de quem vai defende-lo.

`relatorio.py` produz markdown, e a escolha e deliberada: rodar de novo em tres
meses e comparar com um diff mostra o que **mudou no raciocinio**. Isso serve ao
analista, e nao serve a uma sala -- ninguem projeta um diff.

Este modulo produz a outra forma: **uma pagina HTML, autossuficiente e feita para
imprimir**. Mesmos numeros, mesma origem, outra densidade -- menos prosa, mais
estrutura, e os graficos que a tela ja mostra.

Tres decisoes de engenharia, e as tres tem o mesmo motivo
---------------------------------------------------------

**Os graficos sao SVG escrito a mao, e nao Plotly.** Plotly e dependencia
opcional (`app`, `dev`), e o motor nao pode exigi-la -- mas a razao principal e
outra: o HTML exportado do Plotly carrega ~3 MB de JavaScript e **nao imprime
bem**, porque o layout e calculado no navegador. SVG inline imprime igual em
qualquer lugar, tem tamanho de arquivo de texto e nao depende de rede.

**Nada e buscado de fora.** Sem CDN, sem fonte remota, sem `<script>`. Um arquivo
que precisa de rede para se desenhar e um arquivo que falha na sala de reuniao.

**Os numeros vem das mesmas funcoes que a tela usa.** Este modulo formata; ele
nao calcula nada. Duas implementacoes do mesmo numero divergem no dia em que uma
delas muda, e a divergencia apareceria entre o que o comite ve e o que o app
mostra -- que e o pior lugar possivel para ela.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass

import numpy as np

from . import formato
from .formulas import rotulo_do_indicador
import pandas as pd

# Paleta fixa, e nao a do tema. Documento impresso tem um modo so, e o papel e
# branco: as cores sao escolhidas para tinta, e nao para tela escura.
TINTA = "#1f2933"
TINTA_FRACA = "#52606d"
GRADE = "#e4e7eb"
AZUL = "#2f5d8c"
AZUL_CLARO = "#7ea3c4"
VERDE = "#2f6f4e"
VERMELHO = "#9c3b3b"
AREIA = "#faf9f7"


def _pct(valor, casas: int = 1) -> str:
    return formato.pct(valor, casas, "—")


# **Comite le grandeza, e nao digito.** "R$ 63.902.487.991,2" e um numero que
# ninguem processa numa sala; "R$ 63,9 bi" e. A escala e escolhida **uma vez para
# o documento inteiro**, pelo maior numero que ele mostra, e declarada no rotulo
# -- trocar de escala entre linhas da mesma tabela e o jeito mais rapido de fazer
# alguem comparar bilhao com milhao sem perceber.
def escala_do_documento(valores) -> tuple[float, str]:
    """O divisor e o sufixo que cabem no maior numero do material."""
    finitos = [abs(float(v)) for v in valores if v is not None and np.isfinite(float(v))]
    maior = max(finitos) if finitos else 0.0
    if maior >= 1e9:
        return 1e9, "bi"
    if maior >= 1e6:
        return 1e6, "mi"
    if maior >= 1e3:
        return 1e3, "mil"
    return 1.0, ""


# O expoente de cada escala, nos dois vocabularios: o da unidade da empresa
# ("R$ milhoes") e o do sufixo do documento ("mi").
_EXPOENTE_DA_UNIDADE = (
    ("trilh", 12),
    ("bilh", 9),
    ("milh", 6),
    ("mil", 3),
)
_EXPOENTE_DO_SUFIXO = {"": 0, "mil": 3, "mi": 6, "bi": 9}
_ESCALA_POR_EXPOENTE = {0: "", 3: "mil", 6: "milhões", 9: "bilhões", 12: "trilhões"}


def unidade_na_escala(unidade: str, sufixo: str) -> str:
    """A unidade da empresa **composta** com a escala do documento.

    A unidade ja traz escala -- "R$ milhoes" e o padrao do app --, e o documento
    aplica outra por cima. Colar as duas produzia **"R$ milhoes mil"**, rotulo
    que ninguem le, sob um equity de R$ 3,5 bilhoes escrito como "3,5". Aqui as
    duas escalas somam: milhoes (10^6) com mil (10^3) viram bilhoes.

    Unidade que nao declara escala conhecida volta ao comportamento antigo, de
    justapor -- inventar uma composicao para texto livre seria pior.
    """
    unidade = (unidade or "").strip()
    sufixo = (sufixo or "").strip()
    if not sufixo:
        return unidade
    if not unidade:
        return _ESCALA_POR_EXPOENTE.get(_EXPOENTE_DO_SUFIXO.get(sufixo, 0), sufixo)

    minuscula = unidade.lower()
    for marca, expoente in _EXPOENTE_DA_UNIDADE:
        if marca in minuscula:
            total = expoente + _EXPOENTE_DO_SUFIXO.get(sufixo, 0)
            nome = _ESCALA_POR_EXPOENTE.get(total)
            if nome is None:
                return f"{unidade} {sufixo}"
            # Tira a escala antiga do rotulo e poe a nova: "R$ milhoes" -> "R$".
            corte = minuscula.index(marca)
            moeda = unidade[:corte].strip()
            return " ".join(parte for parte in (moeda, nome) if parte)
    nome = _ESCALA_POR_EXPOENTE.get(_EXPOENTE_DO_SUFIXO.get(sufixo, 0), sufixo)
    return " ".join(parte for parte in (unidade, nome) if parte)


def _num(valor, casas: int = 1) -> str:
    return formato.num(valor, casas, "—")


def _e(texto) -> str:
    return html.escape(str(texto))


def _negrito(texto) -> str:
    """Escapa o texto e converte o ``**negrito**`` que vem do motor.

    Os achados do diagnostico sao escritos em markdown -- eles alimentam a tela,
    o relatorio e esta pagina --, e aqui saiam com os asteriscos a vista:
    "**para sempre**", "**nunca erode**". Escapar primeiro e converter depois
    mantem a pagina imune ao que vem de fora.
    """
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", _e(texto))


# ---------------------------------------------------------------------------
# Graficos em SVG
# ---------------------------------------------------------------------------


def _svg(conteudo: str, largura: int, altura: int, titulo: str = "") -> str:
    """Envelope comum: viewBox para escalar na impressao, e titulo acessivel."""
    rotulo = f"<title>{_e(titulo)}</title>" if titulo else ""
    return (
        f'<svg viewBox="0 0 {largura} {altura}" role="img" '
        f'style="width:100%;height:auto;max-width:{largura}px">{rotulo}{conteudo}</svg>'
    )


def barras_horizontais(
    itens, unidade: str = "", titulo: str = "", divisor: float = 1.0
) -> str:
    """Composicao em barras, com o rotulo dentro e o valor fora.

    Serve a pergunta "de que e feito o total", que num comite aparece duas vezes:
    quanto do valor esta na perpetuidade e como a ponte chega ao acionista.
    """
    itens = [(n, float(v)) for n, v in itens if np.isfinite(float(v))]
    if not itens:
        return ""

    alto, espaco, margem_esq, largura = 26, 10, 210, 760
    altura = len(itens) * (alto + espaco) + 30
    maior = max(abs(v) for _, v in itens) or 1.0
    # **Espaco para o rotulo do valor, e nao so para a barra.** A primeira versao
    # reservava 90px e o numero saia cortado -- "63.196.776.991," --, que e pior
    # que numero nenhum: parece um valor e nao e. Com a escala do documento o
    # texto encolhe, e a folga passa a caber.
    util = largura - margem_esq - 120

    partes = []
    for i, (nome, valor) in enumerate(itens):
        y = i * (alto + espaco) + 10
        comprimento = abs(valor) / maior * util
        cor = AZUL if valor >= 0 else VERMELHO
        partes.append(
            f'<text x="{margem_esq - 10}" y="{y + alto * 0.7}" text-anchor="end" '
            f'font-size="13" fill="{TINTA}">{_e(nome)}</text>'
        )
        partes.append(
            f'<rect x="{margem_esq}" y="{y}" width="{comprimento:.1f}" height="{alto}" '
            f'fill="{cor}" rx="2"/>'
        )
        partes.append(
            f'<text x="{margem_esq + comprimento + 8:.1f}" y="{y + alto * 0.7}" '
            f'font-size="13" fill="{TINTA_FRACA}">{_e(_num(valor / divisor))}</text>'
        )
    if unidade:
        partes.append(
            f'<text x="{margem_esq}" y="{altura - 4}" font-size="11" '
            f'fill="{TINTA_FRACA}">em {_e(unidade)}</text>'
        )
    return _svg("".join(partes), largura, altura, titulo)


def linhas_no_tempo(series: dict, titulo: str = "", percentual: bool = True) -> str:
    """Series ao longo do tempo, no mesmo eixo.

    Todas tem de estar na mesma unidade -- e a mesma regra do app: series
    diferentes so dividem uma escala quando a escala quer dizer o mesmo nas duas.
    """
    series = {
        nome: pd.Series(s).replace([np.inf, -np.inf], np.nan).dropna()
        for nome, s in series.items()
    }
    series = {n: s for n, s in series.items() if len(s) >= 2}
    if not series:
        return ""

    largura, altura = 760, 260
    # A direita cabe o rotulo direto de cada serie, que dispensa legenda. 150px
    # nao bastavam para "Crescimento da receita 7,4%" e o texto vazava.
    esq, dir_, topo, base = 50, 205, 20, 40
    colunas = list(next(iter(series.values())).index)
    valores = [v for s in series.values() for v in s.to_numpy()]
    alto_max, alto_min = max(valores), min(valores)
    if alto_max == alto_min:
        alto_max, alto_min = alto_max + 0.01, alto_min - 0.01
    folga = (alto_max - alto_min) * 0.12
    alto_max, alto_min = alto_max + folga, alto_min - folga

    def px(i):
        return esq + (largura - esq - dir_) * (i / max(len(colunas) - 1, 1))

    def py(v):
        return topo + (altura - topo - base) * (1 - (v - alto_min) / (alto_max - alto_min))

    partes = [
        f'<line x1="{esq}" y1="{py(alto_min)}" x2="{largura - dir_}" '
        f'y2="{py(alto_min)}" stroke="{GRADE}"/>'
    ]
    if alto_min < 0 < alto_max:
        partes.append(
            f'<line x1="{esq}" y1="{py(0):.1f}" x2="{largura - dir_}" '
            f'y2="{py(0):.1f}" stroke="{GRADE}" stroke-dasharray="3 3"/>'
        )
    for i, coluna in enumerate(colunas):
        partes.append(
            f'<text x="{px(i):.1f}" y="{altura - 18}" text-anchor="middle" '
            f'font-size="12" fill="{TINTA_FRACA}">{_e(coluna)}</text>'
        )

    cores = (AZUL, VERDE, AZUL_CLARO, VERMELHO)
    for k, (nome, serie) in enumerate(series.items()):
        cor = cores[k % len(cores)]
        pontos = []
        for i, coluna in enumerate(colunas):
            if coluna not in serie.index:
                continue
            pontos.append((px(i), py(float(serie[coluna]))))
        if len(pontos) < 2:
            continue
        caminho = " ".join(
            f"{'M' if j == 0 else 'L'}{x:.1f},{y:.1f}" for j, (x, y) in enumerate(pontos)
        )
        partes.append(f'<path d="{caminho}" fill="none" stroke="{cor}" stroke-width="2.2"/>')
        for x, y in pontos:
            partes.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="{cor}"/>')
        ultimo = float(serie.iloc[-1])
        partes.append(
            f'<text x="{pontos[-1][0] + 10:.1f}" y="{pontos[-1][1] + 4:.1f}" '
            f'font-size="12" fill="{cor}">{_e(nome)} '
            f'{_e(_pct(ultimo) if percentual else _num(ultimo))}</text>'
        )
    return _svg("".join(partes), largura, altura, titulo)


def barras_agrupadas(
    quadro,
    titulo: str = "",
    unidade: str = "",
    divisor: float = 1.0,
    projetado_a_partir_de=None,
) -> str:
    """Series por periodo, em barras lado a lado, com o corte da projecao marcado.

    O corte existe porque **entregue e projetado nao sao a mesma coisa**, e num
    grafico continuo eles se leem como uma serie so: quem olha de longe ve a
    curva subir e nao ve onde acaba o que a companhia fez e comeca o que o
    analista assumiu.
    """
    if quadro is None or getattr(quadro, "empty", True):
        return ""
    colunas = list(quadro.columns)
    periodos = [str(i) for i in quadro.index]
    valores = quadro.to_numpy(dtype=float) / divisor
    if not np.isfinite(valores).any():
        return ""

    largura, altura = 760, 280
    esq, dir_, topo, base = 56, 16, 24, 46
    util = largura - esq - dir_
    passo = util / max(len(periodos), 1)
    grupo = passo * 0.72
    alto = grupo / max(len(colunas), 1)
    maior = float(np.nanmax(np.abs(valores))) or 1.0
    piso = min(0.0, float(np.nanmin(valores)))
    teto = max(0.0, float(np.nanmax(valores)))
    faixa = (teto - piso) or maior

    def py(v):
        return topo + (altura - topo - base) * (1 - (v - piso) / faixa)

    partes = [
        f'<line x1="{esq}" y1="{py(piso):.1f}" x2="{largura - dir_}" '
        f'y2="{py(piso):.1f}" stroke="{GRADE}"/>'
    ]
    cores = (AZUL, VERDE, AZUL_CLARO, VERMELHO)
    for i, periodo in enumerate(periodos):
        x0 = esq + i * passo + (passo - grupo) / 2
        for k, coluna in enumerate(colunas):
            valor = valores[i, k]
            if not np.isfinite(valor):
                continue
            y = py(max(valor, 0.0))
            altura_barra = abs(py(valor) - py(0.0))
            partes.append(
                f'<rect x="{x0 + k * alto:.1f}" y="{y:.1f}" width="{alto * 0.86:.1f}" '
                f'height="{max(altura_barra, 0.6):.1f}" fill="{cores[k % len(cores)]}" rx="1"/>'
            )
        partes.append(
            f'<text x="{esq + i * passo + passo / 2:.1f}" y="{altura - 26}" '
            f'text-anchor="middle" font-size="11" fill="{TINTA_FRACA}">{_e(periodo)}</text>'
        )
        if projetado_a_partir_de is not None and str(projetado_a_partir_de) == periodo:
            x = esq + i * passo
            partes.append(
                f'<line x1="{x:.1f}" y1="{topo}" x2="{x:.1f}" y2="{py(piso):.1f}" '
                f'stroke="{TINTA_FRACA}" stroke-dasharray="4 3"/>'
            )
            partes.append(
                f'<text x="{x + 5:.1f}" y="{topo + 10}" font-size="10.5" '
                f'fill="{TINTA_FRACA}">projetado</text>'
            )
    legenda = " ".join(
        f'<tspan fill="{cores[k % len(cores)]}">■</tspan> {_e(str(c))}'
        for k, c in enumerate(colunas)
    )
    partes.append(
        f'<text x="{esq}" y="{altura - 8}" font-size="11.5" fill="{TINTA_FRACA}">{legenda}</text>'
    )
    if unidade:
        partes.append(
            f'<text x="{largura - dir_}" y="{altura - 8}" text-anchor="end" '
            f'font-size="11" fill="{TINTA_FRACA}">em {_e(unidade)}</text>'
        )
    return _svg("".join(partes), largura, altura, titulo)


def tornado(itens, base: float, unidade: str = "", divisor: float = 1.0, titulo: str = "") -> str:
    """Quanto cada premissa move o valor, com o mesmo deslocamento nas duas pontas.

    A comparacao entre premissas so vale se todas andarem o mesmo tanto -- e e
    por isso que o tornado responde a pergunta que a tabela de sensibilidade nao
    responde: **qual delas decide o numero**.
    """
    itens = [
        (nome, float(baixo), float(alto))
        for nome, baixo, alto in itens
        if np.isfinite(float(baixo)) and np.isfinite(float(alto))
    ]
    if not itens or not np.isfinite(base):
        return ""

    alto_barra, espaco, margem_esq, largura = 24, 12, 210, 760
    altura = len(itens) * (alto_barra + espaco) + 34
    centro = margem_esq + (largura - margem_esq - 90) / 2
    extremos = [abs(v - base) for _, b, a in itens for v in (b, a)]
    maior = max(extremos) or 1.0
    escala = (largura - margem_esq - 110) / 2 / maior

    partes = [
        f'<line x1="{centro:.1f}" y1="6" x2="{centro:.1f}" y2="{altura - 26}" '
        f'stroke="{TINTA_FRACA}" stroke-dasharray="3 3"/>'
    ]
    for i, (nome, baixo, alto) in enumerate(itens):
        y = i * (alto_barra + espaco) + 10
        for valor, cor in ((baixo, AZUL_CLARO), (alto, AZUL)):
            x = centro + min(valor - base, 0.0) * escala
            comprimento = abs(valor - base) * escala
            partes.append(
                f'<rect x="{x:.1f}" y="{y}" width="{max(comprimento, 0.6):.1f}" '
                f'height="{alto_barra}" fill="{cor}" rx="2"/>'
            )
        partes.append(
            f'<text x="{margem_esq - 10}" y="{y + alto_barra * 0.7}" text-anchor="end" '
            f'font-size="12.5" fill="{TINTA}">{_e(nome)}</text>'
        )
        extremo = max(baixo, alto)
        partes.append(
            f'<text x="{centro + abs(extremo - base) * escala + 8:.1f}" '
            f'y="{y + alto_barra * 0.7}" font-size="11.5" fill="{TINTA_FRACA}">'
            f'{_e(_num((extremo - base) / divisor))}</text>'
        )
    partes.append(
        f'<text x="{centro:.1f}" y="{altura - 8}" text-anchor="middle" font-size="11" '
        f'fill="{TINTA_FRACA}">caso base: {_e(_num(base / divisor))}'
        + (f" {_e(unidade)}" if unidade else "")
        + "</text>"
    )
    return _svg("".join(partes), largura, altura, titulo)


def histograma(valores, titulo: str = "", unidade: str = "", divisor: float = 1.0,
               referencia=None) -> str:
    """Distribuicao simulada do valor, com o caso base marcado."""
    valores = np.asarray([v for v in np.asarray(valores, dtype=float) if np.isfinite(v)])
    if valores.size < 2:
        return ""
    contagens, bordas = np.histogram(valores / divisor, bins=28)
    largura, altura = 760, 240
    esq, dir_, topo, base_y = 40, 16, 20, 40
    util = largura - esq - dir_
    passo = util / len(contagens)
    maior = contagens.max() or 1

    partes = []
    for i, contagem in enumerate(contagens):
        alto = (altura - topo - base_y) * (contagem / maior)
        partes.append(
            f'<rect x="{esq + i * passo:.1f}" y="{altura - base_y - alto:.1f}" '
            f'width="{passo * 0.9:.1f}" height="{alto:.1f}" fill="{AZUL_CLARO}"/>'
        )
    partes.append(
        f'<line x1="{esq}" y1="{altura - base_y}" x2="{largura - dir_}" '
        f'y2="{altura - base_y}" stroke="{GRADE}"/>'
    )
    for fracao in (0.0, 0.5, 1.0):
        x = esq + util * fracao
        valor = bordas[0] + (bordas[-1] - bordas[0]) * fracao
        partes.append(
            f'<text x="{x:.1f}" y="{altura - 20}" text-anchor="middle" font-size="11" '
            f'fill="{TINTA_FRACA}">{_e(_num(valor))}</text>'
        )
    if referencia is not None and np.isfinite(float(referencia)):
        alvo = float(referencia) / divisor
        if bordas[0] <= alvo <= bordas[-1]:
            x = esq + util * (alvo - bordas[0]) / (bordas[-1] - bordas[0])
            partes.append(
                f'<line x1="{x:.1f}" y1="{topo}" x2="{x:.1f}" y2="{altura - base_y}" '
                f'stroke="{VERMELHO}" stroke-width="1.5"/>'
            )
            partes.append(
                f'<text x="{x + 5:.1f}" y="{topo + 10}" font-size="10.5" '
                f'fill="{VERMELHO}">caso base</text>'
            )
    if unidade:
        partes.append(
            f'<text x="{largura - dir_}" y="{altura - 6}" text-anchor="end" '
            f'font-size="11" fill="{TINTA_FRACA}">em {_e(unidade)}</text>'
        )
    return _svg("".join(partes), largura, altura, titulo)


def _cor_do_mapa(fracao: float) -> str:
    """Do vermelho claro ao verde claro, passando pelo areia -- tinta de papel."""
    fracao = min(max(fracao, 0.0), 1.0)
    if fracao < 0.5:
        t = fracao / 0.5
        inicio, fim = (247, 221, 221), (250, 249, 247)
    else:
        t = (fracao - 0.5) / 0.5
        inicio, fim = (250, 249, 247), (219, 236, 226)
    canais = [round(a + (b - a) * t) for a, b in zip(inicio, fim)]
    return "#%02x%02x%02x" % tuple(canais)


def _tabela_mapa_de_calor(tabela, divisor: float = 1.0, casas: int = 1) -> str:
    """Tabela numerica com o fundo graduado, para a faixa se ler de relance."""
    if tabela is None or tabela.empty:
        return ""
    valores = tabela.to_numpy(dtype=float)
    finitos = valores[np.isfinite(valores)]
    if finitos.size == 0:
        return ""
    menor, maior = float(finitos.min()), float(finitos.max())
    amplitude = (maior - menor) or 1.0

    cabecalho = "".join(f"<th>{_e(c)}</th>" for c in tabela.columns)
    linhas = []
    for indice, linha in tabela.iterrows():
        celulas = [f"<td>{_e(indice)}</td>"]
        for valor in linha:
            valor = float(valor)
            if not np.isfinite(valor):
                celulas.append('<td class="nota">—</td>')
                continue
            cor = _cor_do_mapa((valor - menor) / amplitude)
            celulas.append(
                f'<td style="background:{cor}">{_e(_num(valor / divisor, casas))}</td>'
            )
        linhas.append(f"<tr>{''.join(celulas)}</tr>")
    nome = tabela.index.name or ""
    return (
        f'<table><thead><tr><th>{_e(nome)}</th>{cabecalho}</tr></thead>'
        f"<tbody>{''.join(linhas)}</tbody></table>"
    )


# ---------------------------------------------------------------------------
# As secoes detalhadas: premissas, contas e faixa
# ---------------------------------------------------------------------------


def _premissas_operacionais(empresa, analise) -> str:
    """Cada direcionador por ano, com a mediana que a companhia entregou ao lado.

    A premissa sozinha nao se julga: 26% de margem e muito ou pouco depende do
    que a empresa fez. A coluna da mediana poe a pergunta e a resposta na mesma
    linha, que e o que a tela ja faz com o balizador.
    """
    op = empresa.operacionais
    if op is None:
        return ""
    anos = [str(op.ano_base + i + 1) if op.ano_base else f"Ano {i + 1}"
            for i in range(op.horizonte)]
    linhas = {
        "Crescimento da receita": (list(op.crescimento_receita), "Crescimento da receita"),
        "Margem EBITDA": (list(op.margem_ebitda), "Margem EBITDA"),
        "Depreciação / receita": (list(op.depreciacao_pct_receita), "Depreciacao / Receita"),
        "Capex / receita": (list(op.capex_pct_receita), "Capex / Receita"),
        "Capital de giro / receita": (
            list(op.capital_giro_pct_receita), "Capital de giro / Receita"
        ),
    }
    if op.arrendamento_pct_receita is not None:
        linhas["Arrendamento / receita (saldo)"] = (list(op.arrendamento_pct_receita), None)
    if op.arrendamento_renovacao_pct_receita is not None:
        linhas["Renovação de arrendamento / receita"] = (
            list(op.arrendamento_renovacao_pct_receita), None
        )

    dados = {}
    for rotulo, (valores, indicador) in linhas.items():
        registro = dict(zip(anos, valores))
        entregue = float("nan")
        if analise is not None and indicador and indicador in analise.indicadores.index:
            entregue = float(analise.mediana(indicador))
        registro["Mediana entregue"] = entregue
        dados[rotulo] = registro
    quadro = pd.DataFrame(dados).T
    quadro.index.name = "Direcionador"
    return _tabela(quadro, formatos={c: _pct for c in quadro.columns})


def _custo_de_capital(resultado) -> str:
    """A montagem do WACC linha a linha, na construcao que foi usada.

    Escrever sempre a soma em dolar seria descrever uma conta que o modelo nao
    fez -- o mesmo defeito que o relatorio ja corrigiu.
    """
    cc = resultado.custo_capital
    p = resultado.empresa.custo_capital
    macro = resultado.empresa.macro
    linhas = []
    if p.metodo == "local":
        linhas += [
            ("Taxa livre de risco (BRL)", _pct(cc.rf_brl, 2),
             "NTN-B real nominalizada pelo IPCA de " + _pct(macro.inflacao_brl)),
            ("Prêmio de risco local (ERP)", _pct(p.erp_local, 2),
             "premissa do analista — é o número que mais move o Ke"),
        ]
    else:
        linhas += [
            ("Taxa livre de risco (USD)", _pct(p.rf_usd, 2), "título soberano do mercado maduro"),
            ("Prêmio de mercado maduro", _pct(p.erp_maduro, 2), "ERP do mercado de referência"),
            ("Risco-país", _pct(p.lambda_pais * p.risco_pais, 2),
             "spread soberano × lambda de exposição"),
        ]
    linhas += [
        ("Beta desalavancado", _num(cc.beta_desalavancado, 2), "do setor, sem estrutura de capital"),
        ("D/E alvo", _num(p.divida_pl_alvo, 2), "estrutura-alvo, não a de hoje"),
        ("Beta realavancado", _num(cc.beta_realavancado, 2), "Hamada, com a alíquota de IR"),
    ]
    if p.metodo != "local":
        linhas.append(("Ke (USD nominal)", _pct(cc.ke_usd, 2), "rf + beta × ERP + risco-país"))
        linhas.append(
            ("Ke (BRL nominal)", _pct(cc.ke_brl, 2),
             "convertido pelo diferencial de inflação (" + _pct(macro.inflacao_brl)
             + " contra " + _pct(macro.inflacao_usd) + ")")
        )
    else:
        linhas.append(("Ke (BRL nominal)", _pct(cc.ke_brl, 2), "rf + beta × ERP local"))
    linhas += [
        ("Kd bruto", _pct(cc.kd_bruto_brl, 2),
         "informado" if p.custo_divida_brl is not None else "sintético: rf + spread de crédito"),
        ("Kd após IR", _pct(cc.kd_liquido_brl, 2), "com alíquota de " + _pct(cc.aliquota_ir)),
        ("Peso do capital próprio", _pct(cc.peso_equity), "1 / (1 + D/E)"),
        ("Peso da dívida", _pct(cc.peso_divida), "D/E / (1 + D/E)"),
        ("WACC (BRL nominal)", _pct(cc.wacc_brl, 2), "Ke × peso do equity + Kd após IR × peso da dívida"),
    ]
    quadro = pd.DataFrame(
        {"Valor": [v for _, v, _ in linhas], "De onde sai": [o for _, _, o in linhas]},
        index=[r for r, _, _ in linhas],
    )
    quadro.index.name = "Etapa"
    return _tabela(quadro)


def _perpetuidade(resultado, divisor: float, unidade: str) -> str:
    """O valor terminal com a conta aberta, e nao so o numero.

    E a maior parcela do valor na maioria dos modelos; no material impresso ela
    e a primeira coisa que a mesa pergunta.
    """
    empresa = resultado.empresa
    perp = empresa.perpetuidade
    dcf = resultado.dcf
    macro = empresa.macro
    itens = []
    if perp.metodo == "gordon":
        origem = {
            "livre": "informado à mão",
            "ipca": "ancorado no IPCA",
            "pib_nominal": "ancorado no PIB nominal",
        }[perp.ancora]
        itens.append(
            f"<li><strong>Crescimento perpétuo</strong>: {_e(_pct(perp.crescimento_perpetuo, 2))}, "
            f"{_e(origem)}. Teto da economia: {_e(_pct(macro.pib_nominal, 2))}.</li>"
        )
        if perp.roic_perpetuidade is None:
            itens.append(
                "<li><strong>Reinvestimento</strong>: não normalizado — o valor terminal "
                "cresce o fluxo do último ano projetado, com o capex e o giro que ele tiver."
                "</li>"
            )
            itens.append(
                "<li><strong>Conta</strong>: FCFF do último ano × (1 + g) ÷ (WACC − g) = "
                f"{_e(_num(dcf.valor_terminal / divisor))} {_e(unidade)}, no fim do ano "
                f"{len(dcf.anos)}.</li>"
            )
        else:
            reinveste = perp.crescimento_perpetuo / perp.roic_perpetuidade
            itens.append(
                f"<li><strong>Reinvestimento normalizado</strong>: ROIC de "
                f"{_e(_pct(perp.roic_perpetuidade, 1))} exige reter {_e(_pct(reinveste))} do "
                "NOPAT perpétuo, para sempre.</li>"
            )
            itens.append(
                "<li><strong>Conta</strong>: NOPAT do último ano × (1 + g) × (1 − g ÷ ROIC) "
                f"÷ (WACC − g) = {_e(_num(dcf.valor_terminal / divisor))} {_e(unidade)}, no "
                f"fim do ano {len(dcf.anos)}.</li>"
            )
    else:
        conta = "EBITDA" if perp.base_do_multiplo == "ebitda" else "lucro líquido"
        itens.append(
            f"<li><strong>Múltiplo de saída</strong>: {_e(_num(perp.multiplo_saida, 1))}× o "
            f"{conta} do último ano projetado, o que dá "
            f"{_e(_num(dcf.valor_terminal / divisor))} {_e(unidade)}.</li>"
        )
    itens.append(
        f"<li><strong>Trazido a valor presente</strong>: "
        f"{_e(_num(dcf.valor_presente_terminal / divisor))} {_e(unidade)}, "
        f"{_e(_pct(dcf.peso_perpetuidade))} do Enterprise Value.</li>"
    )
    return "<ul>" + "".join(itens) + "</ul>"


def _contas_do_modelo(resultado, divisor: float, unidade: str) -> list[str]:
    """A projecao inteira e o desconto ano a ano -- o caminho do numero.

    Sem isto o material mostra o resultado e esconde a conta, que e exatamente o
    que o comite pede para ver quando discorda do valor.
    """
    proj = resultado.projecao
    dcf = resultado.dcf
    partes = ["<h2>As contas, ano a ano</h2>"]

    tabela = proj.tabela() / divisor
    tabela.index.name = f"Linha ({unidade})"
    partes.append(_tabela(tabela))

    indicadores = proj.indicadores()
    indicadores.index.name = "Indicador da projeção"
    partes.append(
        '<p class="nota">As margens e razões que a projeção implica — é onde se vê '
        "se o modelo assume uma empresa diferente da que existe.</p>"
    )
    partes.append(_tabela(indicadores, formatos={c: _pct for c in indicadores.columns}))

    fluxos = dcf.tabela_fluxos().T
    fluxos.index.name = "Ano"
    fluxos["Fluxo"] = fluxos["Fluxo"] / divisor
    fluxos["Fluxo descontado"] = fluxos["Fluxo descontado"] / divisor
    partes.append("<h3>Do fluxo ao valor presente</h3>")
    partes.append(
        _tabela(
            fluxos,
            formatos={"Fator de desconto": lambda v: _num(v, 4)},
        )
    )
    convencao = (
        "meio de ano (t − 0,5)" if dcf.meio_de_ano else "fim de ano (t)"
    )
    partes.append(
        f'<p class="nota">Convenção de desconto: {_e(convencao)}. Valores em '
        f"{_e(unidade)}.</p>"
    )
    return partes


def _faixa_do_valor(
    pacote, simulacao, divisor: float, unidade: str, base_simulada=None
) -> list[str]:
    """A sensibilidade, o tornado, os cenarios e a simulacao -- a faixa, e nao o ponto.

    O valuation nao e um numero; o material que entrega so o ponto convida a
    discussao errada, sobre a segunda casa decimal em vez de sobre a premissa.
    """
    if pacote is None and simulacao is None:
        return []
    partes = ["<h2>Quanto o valor se mexe</h2>"]
    if pacote is not None:
        if pacote.wacc_x_g is not None:
            partes.append("<h3>WACC contra crescimento perpétuo</h3>")
            partes.append(_tabela_mapa_de_calor(pacote.wacc_x_g, divisor))
            partes.append(
                f'<p class="nota">Equity value em {_e(unidade)}. A célula do meio é o '
                "caso base; células vazias são combinações impossíveis, com crescimento "
                "perpétuo acima da taxa de desconto.</p>"
            )
        if pacote.margem_x_crescimento is not None:
            partes.append("<h3>Margem EBITDA contra crescimento da receita</h3>")
            partes.append(_tabela_mapa_de_calor(pacote.margem_x_crescimento, divisor))
        if pacote.tornado is not None and not pacote.tornado.empty:
            colunas = [c for c in pacote.tornado.columns if "p.p." in str(c)]
            if len(colunas) == 2:
                itens = [
                    (indice, linha[colunas[0]], linha[colunas[1]])
                    for indice, linha in pacote.tornado.iterrows()
                ]
                partes.append("<figure>")
                partes.append(
                    tornado(
                        itens,
                        pacote.base,
                        unidade=unidade,
                        divisor=divisor,
                        titulo="O que mais move o valor, a "
                        f"{_pct(pacote.deslocamento_do_tornado)} de deslocamento",
                    )
                )
                partes.append(
                    "<figcaption>Cada premissa anda o mesmo tanto para cima e para "
                    "baixo — é isso que permite compará-las entre si.</figcaption></figure>"
                )
        if pacote.cenarios is not None and "equity_value" in pacote.cenarios.index:
            linha = pacote.cenarios.loc["equity_value"]
            quadro = pd.DataFrame(
                {
                    f"Equity value ({unidade})": [float(v) / divisor for v in linha],
                    "Contra o caso base": [
                        float(v) / pacote.base - 1 if pacote.base else float("nan")
                        for v in linha
                    ],
                },
                index=list(pacote.cenarios.columns),
            )
            quadro.index.name = "Cenário"
            partes.append("<h3>Cenários coerentes</h3>")
            partes.append(_tabela(quadro, formatos={"Contra o caso base": _pct}))
            partes.append(
                '<p class="nota">As premissas não se movem sozinhas: se a demanda cede, '
                "a margem cede junto com o crescimento. O cenário base reproduz o número "
                "principal.</p>"
            )
    if simulacao is not None:
        partes.append("<h3>Monte Carlo</h3>")
        # **A escala e a do que foi simulado.** Valor por acao nao esta na escala
        # do documento: dividi-lo por milhoes deixaria o eixo em zeros, e a marca
        # do caso base cairia fora do grafico.
        por_acao = simulacao.metrica == "valor_por_acao"
        divisor_simulado = 1.0 if por_acao else divisor
        unidade_simulada = "R$ por ação" if por_acao else unidade
        # A referencia e o caso base **da mesma metrica**: marcar o equity dentro
        # de uma distribuicao de valor por acao seria uma linha no lugar errado.
        referencia = base_simulada
        if referencia is None and pacote is not None and pacote.metrica == simulacao.metrica:
            referencia = pacote.base
        partes.append(
            "<figure>"
            + histograma(
                simulacao.valores,
                titulo=f"Distribuição simulada — {simulacao.metrica}",
                unidade=unidade_simulada,
                divisor=divisor_simulado,
                referencia=referencia,
            )
            + "<figcaption>"
            + _e(
                f"{simulacao.simulacoes:,} rodadas, {simulacao.descartadas:,} descartadas "
                "por inviabilidade econômica."
            ).replace(",", ".")
            + "</figcaption></figure>"
        )
        percentis = simulacao.percentis()
        quadro = pd.DataFrame({f"Valor ({unidade_simulada})": percentis / divisor_simulado})
        quadro.index.name = "Percentil"
        partes.append(_tabela(quadro))
    return partes


# ---------------------------------------------------------------------------
# O documento
# ---------------------------------------------------------------------------

CSS = f"""
@page {{ size: A4; margin: 18mm 16mm; }}
* {{ box-sizing: border-box; }}
body {{
  margin: 0; background: #fff; color: {TINTA};
  font-family: -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  font-size: 13px; line-height: 1.55;
  font-variant-numeric: tabular-nums;
}}
.folha {{ max-width: 820px; margin: 0 auto; padding: 32px 28px 64px; }}
h1 {{ font-size: 26px; margin: 0 0 4px; letter-spacing: -0.01em; }}
h2 {{
  font-size: 16px; margin: 34px 0 12px; padding-bottom: 6px;
  border-bottom: 2px solid {GRADE}; page-break-after: avoid;
}}
h3 {{ font-size: 13px; margin: 20px 0 8px; color: {TINTA_FRACA}; page-break-after: avoid; }}
.subtitulo {{ color: {TINTA_FRACA}; margin: 0 0 24px; font-size: 13px; }}
.cartoes {{ display: flex; gap: 12px; flex-wrap: wrap; margin: 16px 0 8px; }}
.cartao {{
  /* `max-width` porque um cartao sozinho na segunda linha esticava pela largura
     inteira, e um numero pequeno num quadro largo se le como um erro de layout. */
  flex: 1 1 150px; max-width: 230px;
  border: 1px solid {GRADE}; border-radius: 6px;
  padding: 12px 14px; background: {AREIA};
}}
.cartao .rotulo {{ font-size: 11px; color: {TINTA_FRACA}; text-transform: uppercase;
  letter-spacing: 0.04em; }}
.cartao .valor {{ font-size: 21px; font-weight: 600; margin-top: 3px; }}
table {{ width: 100%; border-collapse: collapse; margin: 12px 0; font-size: 12.5px; }}
th, td {{ padding: 6px 9px; border-bottom: 1px solid {GRADE}; text-align: right; }}
th:first-child, td:first-child {{ text-align: left; }}
thead th {{
  background: {AZUL}; color: #fff; border-bottom: none;
  font-weight: 600; font-size: 11.5px;
}}
/* Tabela que atravessa a pagina **repete o cabecalho**: sem isto, a segunda
   metade chega ao leitor como uma coluna de numeros sem nome. E linha nao se
   parte no meio -- meia linha nos dois lados da folha nao se le em nenhum. */
thead {{ display: table-header-group; }}
tbody tr {{ page-break-inside: avoid; }}
tbody tr:nth-child(even) {{ background: {AREIA}; }}
td.negativo {{ color: {VERMELHO}; }}
figure {{ margin: 16px 0; page-break-inside: avoid; }}
figcaption {{ font-size: 11.5px; color: {TINTA_FRACA}; margin-top: 6px; }}
.aviso {{
  border-left: 3px solid {VERMELHO}; background: #fdf6f6;
  padding: 10px 14px; margin: 10px 0; page-break-inside: avoid;
}}
.aviso.atencao {{ border-left-color: #a9761f; background: #fdfaf2; }}
.aviso .titulo {{ font-weight: 600; }}
.aviso .detalhe {{ color: {TINTA_FRACA}; font-size: 12.5px; margin-top: 3px; }}
.nota {{ color: {TINTA_FRACA}; font-size: 12px; }}
.secao {{ page-break-inside: avoid; }}
footer {{
  margin-top: 40px; padding-top: 12px; border-top: 1px solid {GRADE};
  color: {TINTA_FRACA}; font-size: 11.5px;
}}
@media print {{ .folha {{ padding: 0; }} }}
"""


@dataclass(frozen=True)
class Cartao:
    rotulo: str
    valor: str


def _cartoes(itens) -> str:
    blocos = "".join(
        f'<div class="cartao"><div class="rotulo">{_e(c.rotulo)}</div>'
        f'<div class="valor">{_e(c.valor)}</div></div>'
        for c in itens
    )
    return f'<div class="cartoes">{blocos}</div>'


def _tabela(tabela: pd.DataFrame, formatos=None) -> str:
    """DataFrame -> HTML, com negativo em vermelho e numero a direita."""
    if tabela is None or tabela.empty:
        return ""
    formatos = formatos or {}
    cabecalho = "".join(f"<th>{_e(c)}</th>" for c in tabela.columns)
    linhas = []
    for indice, linha in tabela.iterrows():
        celulas = [f"<td>{_e(indice)}</td>"]
        for coluna, valor in linha.items():
            classe = ""
            if isinstance(valor, (int, float, np.floating)) and np.isfinite(valor):
                classe = ' class="negativo"' if valor < 0 else ""
                texto = formatos.get(coluna, _num)(valor)
            else:
                texto = "—" if valor is None or (isinstance(valor, float)) else str(valor)
            celulas.append(f"<td{classe}>{_e(texto)}</td>")
        linhas.append(f"<tr>{''.join(celulas)}</tr>")
    return (
        f'<table><thead><tr><th>{_e(tabela.index.name or "")}</th>{cabecalho}</tr></thead>'
        f"<tbody>{''.join(linhas)}</tbody></table>"
    )


def _avisos(diagnostico) -> str:
    """Os achados do diagnostico, do mais grave para o menos.

    **Vao no documento e nao num anexo.** O relatorio existe para ser defendido
    numa sala, e a pergunta que vem da mesa e exatamente a que o diagnostico
    antecipa -- esconde-la nao a faz sumir, so faz o analista ser pego por ela.
    """
    if diagnostico is None or not getattr(diagnostico, "achados", None):
        return (
            '<p class="nota"><strong>Diagnóstico não executado.</strong> '
            "O modelo não passou pela crítica automática — a ausência está "
            "declarada porque “sem achados” e “não verificado” não são a mesma "
            "coisa.</p>"
        )
    ordem = {"erro": 0, "alerta": 1, "informacao": 2}
    achados = sorted(
        diagnostico.achados, key=lambda a: ordem.get(getattr(a, "severidade", ""), 3)
    )
    blocos = []
    # **O terceiro estado, e no papel ele importa mais.** A pagina e o que sobra
    # depois que a tela fecha: uma lista curta de achados numa serie trimestral
    # se le como modelo limpo, e o que houve foi o app deixar de verificar.
    omitidas = tuple(getattr(diagnostico, "omitidas", ()) or ())
    if omitidas:
        quais = ", ".join(rotulo_do_indicador(i) for i in omitidas)
        blocos.append(
            '<p class="nota"><strong>'
            f"{len(omitidas)} verificações não rodaram.</strong> A série "
            "importada é de trimestres isolados, e elas confrontam a premissa — "
            "que é de um exercício — com o histórico da companhia. Num "
            "trimestre, um indicador que mistura fluxo com estoque sai a um "
            "quarto, e o achado inverteria de sinal. Ficaram de fora: "
            f"{_e(quais)}.</p>"
        )
    for a in achados:
        severidade = getattr(a, "severidade", "")
        classe = "aviso" if severidade == "erro" else "aviso atencao"
        blocos.append(
            f'<div class="{classe}"><div class="titulo">{_negrito(a.titulo)}</div>'
            f'<div class="detalhe">{_negrito(a.detalhe)}</div></div>'
        )
    return "".join(blocos)


def _onde_cai_na_base(analise, quantos: int = 8) -> str:
    """Onde a companhia e incomum, contra as companhias brasileiras medidas.

    E o tipo de ancora que um comite pede: "margem de 22%" nao diz se e boa, e
    "no percentil 47 de 413 companhias" diz. Nao cabem as 22 linhas da tela --
    num material impresso a tabela longa vira pagina virada --, entao entram as
    **mais incomuns**, que sao as que a mesa vai perguntar.

    Recusa a serie trimestral inteira: a base e medida em exercicios, e parte dos
    indicadores nao atravessa a frequencia. Meia tabela com percentil e meia sem
    seria pior no papel do que na tela, onde ha espaco para explicar cada linha.
    """
    from . import referencias

    if getattr(analise.demonstracoes, "periodicidade", "anual") == "trimestral":
        return (
            '<h2>Onde a companhia cai na base brasileira</h2><p class="nota">'
            "<strong>Não incluído:</strong> a série importada é trimestral, e a "
            "base de referência é medida em exercícios. Parte dos indicadores "
            "não atravessa a frequência — ROIC e dívida sobre EBITDA saem a um "
            "quarto num trimestre —, e uma tabela meio comparável no papel "
            "engana mais do que ajuda.</p>"
        )

    linhas = []
    for indicador, (n, _) in referencias.BASE.items():
        if indicador not in analise.indicadores.index:
            continue
        medida = analise.mediana(indicador)
        posicao = referencias.posicao(indicador, medida)
        if not np.isfinite(posicao):
            continue
        linhas.append((abs(posicao - 0.5), indicador, medida, posicao, n))
    if not linhas:
        return ""

    linhas.sort(reverse=True)
    quadro = pd.DataFrame(
        [
            {
                "Esta companhia": referencias.formatar(ind, valor),
                "Mediana da base": referencias.formatar(
                    ind, referencias.BASE[ind][1][3]
                ),
                "Percentil": f"{pos * 100:.0f}".replace(".", ","),
            }
            for _, ind, valor, pos, n in linhas[:quantos]
        ],
        index=[l[1] for l in linhas[:quantos]],
    )
    quadro.index.name = "Indicador"

    safra = referencias.safra()
    contexto = (
        f" Percentis de {safra.ano_medido}, medidos em {safra.companhias} companhias."
        if safra is not None
        else ""
    )
    return (
        "<h2>Onde a companhia cai na base brasileira</h2>"
        + _tabela(quadro)
        + '<p class="nota">As oito linhas em que ela mais se afasta da mediana '
        "brasileira." + contexto + " Bancos e seguradoras ficam fora da base de "
        "propósito: margem EBITDA e capex sobre receita não querem dizer neles o "
        "que querem dizer no resto.</p>"
    )


def montar_html_da_mesa(carteira, data: str = "") -> str:
    """O material de **varios modelos**, para um comite que ve tres companhias.

    A pagina de um valuation responde "quanto vale esta". Um comite que tem tres
    na mesa faz outra pergunta -- "em qual delas estamos sendo otimistas?" --, e
    a resposta dela e a **distancia de cada premissa para o proprio historico**,
    que e o que atravessa negocios diferentes.

    Nao repete o material individual: quem quer o detalhe de uma companhia gera a
    pagina dela. Aqui cabe o que so existe na comparacao.
    """
    legiveis = carteira.legiveis
    if len(legiveis) < 2:
        raise ValueError(
            "Comparacao precisa de dois modelos legiveis; com um so, toda frase "
            "desta pagina seria sobre nada."
        )

    resumo = carteira.resumo()
    divisor, sufixo = escala_do_documento(resumo.get("Equity value", []))
    unidades = {m.unidade for m in legiveis if m.unidade}
    base = next(iter(unidades)) if len(unidades) == 1 else ""
    rotulo_valor = unidade_na_escala(base, sufixo) or "valor"

    partes = [
        "<h1>Modelos lado a lado</h1>",
        f'<p class="subtitulo">{len(legiveis)} companhias · material de apoio à '
        f'decisão · gerado em {_e(data or "—")}</p>',
        "<p>O que se compara entre negócios diferentes <strong>não é o nível da "
        "premissa</strong> — margem de 22% numa varejista e de 31% numa geradora "
        "não dizem qual projeção é mais agressiva. É a <strong>distância</strong> "
        "entre o que se projetou e o que aquela companhia entregou: essa "
        "atravessa setores.</p>",
    ]

    for frase in carteira.leitura():
        # As frases vem em markdown leve (`**`), que aqui vira `<strong>`:
        # elas sao escritas uma vez, no motor, e cada consumidor as
        # renderiza no proprio formato.
        pedacos = _e(frase).split("**")
        montado = "".join(
            p if i % 2 == 0 else f"<strong>{p}</strong>" for i, p in enumerate(pedacos)
        )
        partes.append(f'<p class="nota">{montado}</p>')

    partes.append("<h2>A distância de cada premissa para o histórico</h2>")
    distancias = carteira.distancias()
    if not distancias.empty:
        distancias.index.name = "Premissa"
        partes.append(_tabela(distancias, formatos={c: _pct for c in distancias.columns}))
        partes.append(
            '<p class="nota">Positivo significa que a projeção pede melhora sobre '
            "o que a companhia entregou — e isso pode ter todo motivo. O número "
            "diz onde olhar, e não o que concluir.</p>"
        )

    proximidade = carteira.proximidade()
    if not proximidade.empty:
        partes.append("<h2>Estes modelos são comparáveis entre si?</h2>")
        proximidade.index.name = "Distância de perfil"
        partes.append(_tabela(proximidade, formatos={c: (lambda v: _num(v, 2)) for c in proximidade.columns}))
        partes.append(
            '<p class="nota">Distância de perfil econômico — risco, crescimento e '
            "fluxo de caixa. Na base brasileira a mediana entre companhias "
            "quaisquer é <strong>1,3</strong>; acima de <strong>5,0</strong> "
            "estão os 10% mais dissimilares.</p>"
        )

    partes.append("<h2>O que cada modelo diz que a companhia vale</h2>")
    if "Equity value" in resumo.columns:
        resumo = resumo.copy()
        resumo["Equity value"] = resumo["Equity value"] / divisor
        resumo = resumo.rename(columns={"Equity value": f"Equity value ({rotulo_valor})"})
    # Coluna sem nenhum numero nao vira coluna: um travessao em toda linha nao
    # informa, e a legenda ja diz por que ela nao esta la.
    resumo = resumo.dropna(axis=1, how="all")
    resumo.index.name = "Modelo"
    formatos = {}
    for coluna in resumo.columns:
        if coluna in ("WACC", "g perpétuo", "Margem de segurança", "Conversão de caixa"):
            formatos[coluna] = _pct
    partes.append(_tabela(resumo, formatos=formatos))

    partes.append(
        "<footer>Comparação entre modelos salvos, e não entre companhias: cada "
        "linha é o que <em>este</em> valuation afirma. Duas versões da mesma "
        "companhia são tão comparáveis quanto duas companhias.</footer>"
    )
    corpo = "".join(partes)
    return (
        '<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">'
        "<title>Modelos lado a lado</title>"
        f"<style>{CSS}</style></head><body>"
        f'<div class="folha">{corpo}</div></body></html>'
    )


def _pagina_do_banco(empresa, lucro_residual, analise, qualidade, diagnostico, data):
    """O material de uma instituicao financeira, que **nao tem DCF**.

    Para uma industria a divida financia o ativo; para um banco ela **e o
    insumo**, e descontar um "fluxo para a firma" ao WACC soma o que ele ganha
    por tomar dinheiro e depois desconta por ele tomar dinheiro. A tela de Valor
    ja desvia antes de qualquer numero aparecer, e o relatorio markdown tambem --
    faltava a pagina do comite, que montaria Enterprise Value, ponte e WACC que
    ninguem calculou.

    Contradizer no papel o numero que a tela mostrou e o pior lugar possivel para
    uma divergencia: o material e o que sobra depois que a tela fecha.
    """
    unidade = empresa.unidade or ""
    v = lucro_residual
    divisor, sufixo = escala_do_documento(
        [v.equity_value, v.patrimonio_inicial, v.valor_presente_terminal]
    )
    unidade_escala = unidade_na_escala(unidade, sufixo)
    pvp = v.equity_value / v.patrimonio_inicial if v.patrimonio_inicial else float("nan")

    cartoes = [
        Cartao(f"Equity value ({unidade_escala})", _num(v.equity_value / divisor)),
        Cartao("P/VP", _num(pvp, 2) + "x"),
        Cartao("Ke", _pct(v.ke)),
        Cartao(
            f"Patrimônio de partida ({unidade_escala})",
            _num(v.patrimonio_inicial / divisor),
        ),
    ]

    partes = [
        f"<h1>{_e(empresa.nome)}</h1>",
        f'<p class="subtitulo">Material de apoio à decisão · instituição '
        f'financeira · gerado em {_e(data or "—")}</p>',
        _cartoes(cartoes),
        "<h2>Por que este modelo, e não um DCF</h2>",
        "<p>Para uma indústria a dívida financia o ativo; para um banco ela "
        "<strong>é o insumo</strong>. Descontar um fluxo para a firma ao WACC "
        "somaria o que a instituição ganha por tomar dinheiro e depois "
        "descontaria por ela tomar dinheiro. O valor aqui sai do "
        "<strong>lucro residual</strong>: patrimônio contábil mais o valor "
        "presente do lucro que excede o custo do capital sobre esse patrimônio.</p>",
        "<h2>De onde vem o valor</h2>",
        "<figure>"
        + barras_horizontais(
            [
                ("Patrimônio de partida", v.patrimonio_inicial),
                ("VP do lucro residual", v.valor_presente_residual),
                ("VP do valor terminal", v.valor_presente_terminal),
                ("= Equity value", v.equity_value),
            ],
            unidade=unidade_escala,
            divisor=divisor,
            titulo="Do patrimônio contábil ao valor do acionista",
        )
        + "<figcaption>A âncora contábil carrega a maior parte do valor — no DCF "
        "o terminal costuma valer de 60% a 80% do total, e aqui erro na "
        "perpetuidade custa menos.</figcaption></figure>",
    ]

    if v.anos:
        serie = pd.DataFrame(
            {
                "Patrimônio de abertura": np.asarray(v.patrimonio_abertura) / divisor,
                "Lucro": np.asarray(v.lucro) / divisor,
                "Lucro residual": np.asarray(v.lucro_residual) / divisor,
            },
            index=v.anos,
        ).T
        serie.index.name = f"Em {unidade_escala}"
        partes.append("<h2>O lucro acima do custo do capital</h2>")
        partes.append(_tabela(serie))
        partes.append(
            '<p class="nota">Lucro residual negativo significa que o resultado '
            "não cobre o custo do capital próprio: naquele ano a instituição "
            "destruiu valor contábil, ainda que tenha dado lucro.</p>"
        )

    partes.append("<h2>O que pode derrubar a tese</h2>")
    partes.append(_avisos(diagnostico))
    partes.append(
        '<div class="aviso atencao"><div class="titulo">O que não foi avaliado '
        "aqui</div><div class=\"detalhe\">Este material não traz os percentis da "
        "base de comparáveis nem o diagnóstico do DCF. O universo de referência "
        "<strong>exclui bancos e seguradoras de propósito</strong> — margem "
        "EBITDA e capex sobre receita não querem dizer neles o que querem dizer "
        "no resto —, e o diagnóstico verifica a coerência de um DCF que não foi "
        "usado. O modelo também não considera capital regulatório.</div></div>"
    )

    if qualidade is not None:
        partes.append("<h3>Qualidade dos lucros</h3>")
        partes.append(f'<p>{_e(getattr(qualidade, "resumo", ""))}</p>')

    partes.append(
        "<footer>Gerado pelo app de valuation a partir dos Dados Abertos da CVM. "
        "O valor sai do modelo de lucro residual (Ohlson), e não de fluxo "
        "descontado — as duas leituras não se somam.</footer>"
    )
    corpo = "".join(partes)
    return (
        '<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">'
        f"<title>{_e(empresa.nome)} — material de apoio</title>"
        f"<style>{CSS}</style></head><body>"
        f'<div class="folha">{corpo}</div></body></html>'
    )


def _historico_com_projecao(analise, resultado) -> str:
    """Receita e EBITDA entregues, e os projetados, no mesmo grafico.

    O corte entre os dois e marcado: num grafico continuo, entregue e projetado
    se leem como uma serie so.
    """
    d = analise.demonstracoes
    try:
        receita = d.serie("receita_liquida").dropna()
        ebitda = d.ebitda().dropna()
    except Exception:  # noqa: BLE001 - origem sem as contas nao ganha o grafico
        return ""
    if receita.empty:
        return ""

    proj = resultado.projecao
    historico = pd.DataFrame({"Receita": receita, "EBITDA": ebitda})
    historico.index = [str(i) for i in historico.index]
    projetado = pd.DataFrame(
        {"Receita": proj.receita, "EBITDA": proj.ebitda},
        index=[str(a) for a in proj.anos],
    )
    quadro = pd.concat([historico, projetado])
    divisor, sufixo = escala_do_documento(quadro.to_numpy(dtype=float).ravel().tolist())
    unidade = unidade_na_escala(resultado.empresa.unidade or "", sufixo)
    grafico = barras_agrupadas(
        quadro,
        titulo="Receita e EBITDA: entregue e projetado",
        unidade=unidade,
        divisor=divisor,
        projetado_a_partir_de=projetado.index[0],
    )
    if not grafico:
        return ""
    return (
        "<figure>"
        + grafico
        + "<figcaption>À esquerda do tracejado, o que a companhia publicou; à "
        "direita, o que o modelo assume.</figcaption></figure>"
    )


def _ifrs16_no_material(visao, divisor: float = 1.0, unidade: str = "") -> str:
    """As duas leituras do aluguel, lado a lado, sem misturar as bases.

    **Cada linha tem o seu formato**: margem e percentual, divida e moeda na
    escala do documento. Numa tabela so, o formato por coluna transformava 29,4%
    em "0,3" e deixava a divida em milhoes num documento em bilhoes.
    """
    try:
        aluguel = float(visao.aluguel.dropna().iloc[-1])
        reportada = float(visao.margem_ebitda_reportada.dropna().iloc[-1])
        ex = float(visao.margem_ebitda.dropna().iloc[-1])
        divida = float(visao.divida_bruta_reportada.dropna().iloc[-1])
        divida_ex = float(visao.divida_bruta.dropna().iloc[-1])
    except (AttributeError, IndexError, ValueError):
        return ""
    quadro = pd.DataFrame(
        {
            "Com IFRS 16 (reportado)": [_pct(reportada), _num(divida / divisor)],
            "Sem IFRS 16": [_pct(ex), _num(divida_ex / divisor)],
        },
        index=["Margem EBITDA", f"Dívida bruta ({unidade})" if unidade else "Dívida bruta"],
    )
    quadro.index.name = "Leitura"
    return (
        "<h2>O aluguel, dentro e fora do EBITDA</h2>"
        + _tabela(quadro)
        + '<p class="nota">O desembolso de aluguel do último exercício foi '
        + _e(_num(aluguel / divisor))
        + (f" {_e(unidade)}" if unidade else "")
        + ". As duas leituras não se misturam: ou dívida com arrendamento sobre EBITDA "
        "com aluguel dentro, ou dívida sem arrendamento sobre EBITDA sem ele.</p>"
    )


def montar_html(
    resultado=None,
    analise=None,
    qualidade=None,
    diagnostico=None,
    margem=None,
    investimento=None,
    lucro_residual=None,
    empresa=None,
    data: str = "",
    sensibilidades=None,
    simulacao=None,
    ifrs16=None,
    multiplos=None,
) -> str:
    """O material do comite, numa pagina HTML autossuficiente.

    Recebe o mesmo que `relatorio.montar` e nao recalcula nada: as duas formas
    tem de dizer o mesmo numero, e a unica maneira de garantir isso e as duas
    lerem da mesma fonte.

    ``lucro_residual`` **desvia a pagina inteira**: instituicao financeira nao
    tem DCF, e montar aqui um Enterprise Value que ninguem calculou contradiria
    no papel o que a tela mostrou. Nesse caminho ``resultado`` pode vir vazio --
    exigi-lo seria pedir justamente o numero que a pagina recusa --, e o nome e a
    unidade saem de ``empresa``.
    """
    if lucro_residual is not None:
        alvo = empresa if empresa is not None else resultado.empresa
        return _pagina_do_banco(
            alvo, lucro_residual, analise, qualidade, diagnostico, data
        )

    if resultado is None:
        raise ValueError(
            "Sem `resultado` nao ha DCF para descrever. Instituicao financeira "
            "passa `lucro_residual` e `empresa`."
        )
    empresa = resultado.empresa
    dcf = resultado.dcf
    unidade = empresa.unidade or ""

    # **A unidade vai no rotulo, e nao dentro do numero.** "63.902.487.991,2 R$"
    # quebrou o cartao em duas linhas na primeira versao -- exatamente o defeito
    # que este projeto ja tinha corrigido na tela e que eu repeti aqui. E a
    # convencao da propria demonstracao: unidade no cabecalho, uma vez.
    divisor, sufixo = escala_do_documento(
        [
            dcf.equity_value,
            dcf.enterprise_value,
            dcf.valor_presente_explicito,
            dcf.valor_presente_terminal,
        ]
    )
    unidade_escala = unidade_na_escala(unidade, sufixo)

    cartoes = [
        Cartao(f"Equity value ({unidade_escala})", _num(dcf.equity_value / divisor)),
        Cartao("WACC", _pct(resultado.custo_capital.wacc_brl)),
        Cartao("g perpétuo", _pct(empresa.perpetuidade.crescimento_perpetuo)),
        Cartao("Peso da perpetuidade", _pct(dcf.peso_perpetuidade)),
    ]
    if dcf.valor_por_acao is not None and np.isfinite(dcf.valor_por_acao):
        cartoes.append(Cartao("Valor por ação", f"R$ {_num(dcf.valor_por_acao, 2)}"))
    if margem is not None and np.isfinite(getattr(margem, "margem", float("nan"))):
        cartoes.append(Cartao("Margem de segurança", _pct(margem.margem)))

    partes = [
        f"<h1>{_e(empresa.nome)}</h1>",
        f'<p class="subtitulo">Material de apoio à decisão · gerado em {_e(data or "—")}</p>',
        _cartoes(cartoes),
        '<p class="nota">Este documento não é recomendação de investimento. '
        "Os números vêm do modelo montado no app, e as premissas que os produzem "
        "estão adiante — quem discorda do valor discorda de uma delas.</p>",
        "<h2>De onde vem o valor</h2>",
    ]

    partes.append(
        "<figure>"
        + barras_horizontais(
            [
                ("VP dos fluxos explícitos", dcf.valor_presente_explicito),
                ("VP do valor terminal", dcf.valor_presente_terminal),
                ("= Enterprise Value", dcf.enterprise_value),
                ("(−) Dívida líquida", -empresa.ponte.divida_liquida),
                ("= Equity value", dcf.equity_value),
            ],
            unidade=unidade_escala,
            divisor=divisor,
            titulo="Do fluxo descontado ao valor do acionista",
        )
        + "<figcaption>O peso da perpetuidade é "
        + _e(_pct(dcf.peso_perpetuidade))
        + " do Enterprise Value — quanto do valor depende do que acontece "
        "depois do horizonte projetado.</figcaption></figure>"
    )

    if analise is not None:
        indicadores = analise.indicadores
        disponiveis = {
            nome: indicadores.loc[nome]
            for nome in ("Margem EBITDA", "ROIC", "Crescimento da receita")
            if nome in indicadores.index
        }
        if disponiveis:
            partes.append("<h2>O que a companhia entregou</h2>")
            partes.append(
                "<figure>"
                + linhas_no_tempo(disponiveis, titulo="Margens e retorno no histórico")
                + "<figcaption>É contra estas séries que as premissas se "
                "comparam: projetar acima do entregue é uma afirmação sobre "
                "mudança, e ela precisa de motivo.</figcaption></figure>"
            )

    partes.append("<h2>As premissas que produzem o número</h2>")
    partes.append(_premissas_operacionais(empresa, analise))
    partes.append(
        '<p class="nota">A coluna da direita é a mediana que a companhia entregou no '
        "histórico importado. Projetar acima dela é uma afirmação sobre mudança, e ela "
        "precisa de motivo.</p>"
    )

    partes.append("<h3>Custo de capital</h3>")
    partes.append(_custo_de_capital(resultado))

    partes.append("<h3>Perpetuidade</h3>")
    partes.append(_perpetuidade(resultado, divisor, unidade_escala))

    partes.append("<h3>Do Enterprise Value ao acionista</h3>")
    ponte = resultado.tabela_ponte() / divisor
    ponte.index.name = f"Item ({unidade_escala})"
    partes.append(_tabela(ponte))

    macro = empresa.macro
    partes.append(
        '<p class="nota">Macro de longo prazo: IPCA de '
        + _e(_pct(macro.inflacao_brl))
        + ", PIB real de "
        + _e(_pct(macro.pib_real))
        + " (nominal de "
        + _e(_pct(macro.pib_nominal))
        + "), alíquota de IR/CSLL de "
        + _e(_pct(macro.aliquota_ir))
        + ".</p>"
    )

    partes += _contas_do_modelo(resultado, divisor, unidade_escala)

    if analise is not None and getattr(analise, "demonstracoes", None) is not None:
        historico_vs_projecao = _historico_com_projecao(analise, resultado)
        if historico_vs_projecao:
            partes.append(historico_vs_projecao)

    # O caso base da metrica simulada sai do proprio resultado -- a pagina le, nao
    # recalcula -- e fica `None` para metrica que ela nao conhece.
    base_simulada = None
    if simulacao is not None:
        base_simulada = {
            "equity_value": dcf.equity_value,
            "enterprise_value": dcf.enterprise_value,
            "valor_por_acao": dcf.valor_por_acao,
        }.get(simulacao.metrica)
    partes += _faixa_do_valor(
        sensibilidades, simulacao, divisor, unidade_escala, base_simulada
    )

    if ifrs16 is not None:
        partes.append(_ifrs16_no_material(ifrs16, divisor, unidade_escala))

    if multiplos is not None and not getattr(multiplos, "empty", True):
        partes.append("<h2>O que os comparáveis dizem</h2>")
        partes.append(_tabela(multiplos))
        partes.append(
            '<p class="nota">Múltiplos de EV passam pela ponte da dívida; múltiplos de '
            "equity já produzem o valor do acionista. Trocar os dois é o erro mais "
            "frequente da avaliação relativa.</p>"
        )

    if investimento is not None:
        partes.append("<h2>Onde foi o dinheiro do investimento</h2>")
        div_inv, suf_inv = escala_do_documento([v for _, v in investimento.linhas()])
        quadro = pd.DataFrame(
            {
                f"Valor ({' '.join(x for x in (unidade, suf_inv) if x)})": [
                    v / div_inv for _, v in investimento.linhas()
                ]
            },
            index=[r for r, _ in investimento.linhas()],
        )
        quadro.index.name = "Componente"
        partes.append(_tabela(quadro))
        partes.append(
            '<p class="nota">Nem tudo que passa pela seção de investimento é '
            "capex: aplicação e resgate de título não são investimento na "
            "operação, e aquisição de participação consome o mesmo caixa sem "
            "repor ativo.</p>"
        )

    if analise is not None:
        partes.append(_onde_cai_na_base(analise))

    partes.append("<h2>O que pode derrubar a tese</h2>")
    partes.append(_avisos(diagnostico))

    if qualidade is not None:
        partes.append("<h3>Qualidade dos lucros</h3>")
        partes.append(
            f'<p>{_e(getattr(qualidade, "resumo", ""))} '
            f"Conversão mediana de {_e(_pct(getattr(qualidade, 'conversao_mediana', float('nan'))))} "
            "do EBITDA em caixa.</p>"
        )

    partes.append(
        "<footer>Gerado pelo app de valuation a partir dos Dados Abertos da CVM. "
        "As premissas são do analista; os dados históricos são o que a companhia "
        "publicou. O material acompanha o modelo — mudou a premissa, refaça a "
        "página.</footer>"
    )

    corpo = "".join(partes)
    return (
        "<!doctype html><html lang=\"pt-BR\"><head><meta charset=\"utf-8\">"
        f"<title>{_e(empresa.nome)} — material de apoio</title>"
        f"<style>{CSS}</style></head><body>"
        f'<div class="folha">{corpo}</div></body></html>'
    )

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
from dataclasses import dataclass

import numpy as np

from . import formato
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


def _num(valor, casas: int = 1) -> str:
    return formato.num(valor, casas, "—")


def _e(texto) -> str:
    return html.escape(str(texto))


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
    for a in achados:
        severidade = getattr(a, "severidade", "")
        classe = "aviso" if severidade == "erro" else "aviso atencao"
        blocos.append(
            f'<div class="{classe}"><div class="titulo">{_e(a.titulo)}</div>'
            f'<div class="detalhe">{_e(a.detalhe)}</div></div>'
        )
    return "".join(blocos)


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
    rotulo_valor = " ".join(x for x in (base, sufixo) if x) or "valor"

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
    unidade_escala = " ".join(x for x in (unidade, sufixo) if x)
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
    unidade_escala = " ".join(x for x in (unidade, sufixo) if x)

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
    op = empresa.operacionais
    horizonte = len(op.crescimento_receita)
    anos = [f"Ano {i + 1}" for i in range(horizonte)]
    premissas = pd.DataFrame(
        {
            "Crescimento da receita": list(op.crescimento_receita),
            "Margem EBITDA": list(op.margem_ebitda),
            "Capex / Receita": list(op.capex_pct_receita),
            "Depreciação / Receita": list(op.depreciacao_pct_receita),
        },
        index=anos,
    ).T
    premissas.index.name = "Direcionador"
    partes.append(_tabela(premissas, formatos={c: _pct for c in premissas.columns}))

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

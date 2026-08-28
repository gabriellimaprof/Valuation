"""Graficos do app.

Regras seguidas em todos eles, vindas do guia de dataviz:

* **Um eixo por grafico.** Receita e margem nunca dividem o mesmo painel com
  duas escalas -- viram dois graficos. Eixo duplo e o erro mais comum em
  grafico financeiro, e faz duas series de grandezas diferentes parecerem
  comparaveis quando nao sao.
* **Cor por identidade, em ordem fixa.** A mesma serie tem a mesma cor em todas
  as telas; um filtro que reduz o numero de series nao repinta as que sobraram.
* **Marca fina, grade recessiva, rotulo direto quando sao poucas series.**
* **Sequencial de um tom so** para magnitude (mapa de calor da sensibilidade),
  nunca arco-iris.
* **Tabela de dados sempre disponivel** ao lado, o que satisfaz a regra do
  relevo para os tons de menor contraste no modo claro.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from .tema import layout_base, paleta

LARGURA_LINHA = 2
TAMANHO_MARCADOR = 8


def _formatar_moeda(valor: float, unidade: str = "") -> str:
    texto = f"{valor:,.1f}".replace(",", "@").replace(".", ",").replace("@", ".")
    return f"{texto} {unidade}".strip()


def _formatar_pct(valor: float, casas: int = 1) -> str:
    return f"{valor * 100:,.{casas}f}%".replace(".", ",")


def linhas_percentuais(
    dados: pd.DataFrame,
    titulo: str = "",
    altura: int = 330,
    rotular_ultimo: bool = True,
) -> go.Figure:
    """Series percentuais ao longo do tempo (margens, retornos, taxas).

    Todas as series compartilham o mesmo eixo porque todas sao percentuais --
    e o unico caso em que series diferentes podem dividir uma escala sem
    enganar quem le.
    """
    p = paleta()
    figura = go.Figure()

    for indice, (nome, serie) in enumerate(dados.iterrows()):
        cor = p.serie(indice)
        valores = serie.astype(float)
        figura.add_trace(
            go.Scatter(
                x=[str(c) for c in dados.columns],
                y=valores,
                name=str(nome),
                mode="lines+markers",
                line={"color": cor, "width": LARGURA_LINHA},
                marker={"size": TAMANHO_MARCADOR, "color": cor},
                connectgaps=False,
                hovertemplate=f"<b>{nome}</b>: %{{y:.1%}}<extra></extra>",
            )
        )
        # Rotulo direto: com poucas series, dispensa procurar na legenda.
        if rotular_ultimo and len(dados) <= 4:
            validos = valores.dropna()
            if not validos.empty:
                figura.add_annotation(
                    x=str(validos.index[-1]),
                    y=float(validos.iloc[-1]),
                    text=_formatar_pct(float(validos.iloc[-1])),
                    showarrow=False,
                    xshift=30,
                    font={"size": 11, "color": p.texto_secundario},
                )

    layout = layout_base(altura, titulo)
    layout["yaxis"]["tickformat"] = ".0%"
    layout["showlegend"] = len(dados) >= 2
    figura.update_layout(**layout)
    return figura


def barras_temporais(
    dados: pd.DataFrame,
    titulo: str = "",
    unidade: str = "",
    altura: int = 330,
) -> go.Figure:
    """Grandezas monetarias ao longo do tempo, em barras agrupadas.

    Todas as series precisam estar na mesma unidade. Um espaco de 2px separa
    barras vizinhas, para que blocos adjacentes nao se leiam como um so.
    """
    p = paleta()
    figura = go.Figure()

    for indice, (nome, serie) in enumerate(dados.iterrows()):
        cor = p.serie(indice)
        figura.add_trace(
            go.Bar(
                x=[str(c) for c in dados.columns],
                y=serie.astype(float),
                name=str(nome),
                marker={"color": cor, "line": {"width": 0}},
                hovertemplate=f"<b>{nome}</b>: %{{y:,.1f}} {unidade}<extra></extra>",
            )
        )

    layout = layout_base(altura, titulo)
    layout["barmode"] = "group"
    layout["bargap"] = 0.28
    layout["bargroupgap"] = 0.06
    layout["showlegend"] = len(dados) >= 2
    figura.update_layout(**layout)
    return figura


def roic_versus_wacc(
    roic: pd.Series, wacc: float, titulo: str = "ROIC histórico x custo de capital"
) -> go.Figure:
    """O grafico que responde se crescer cria ou destroi valor.

    ROIC acima do WACC significa que cada real reinvestido vale mais do que
    custou; abaixo, crescer destroi valor. A area entre as duas linhas e o
    spread economico -- por isso ela e sombreada.
    """
    p = paleta()
    anos = [str(a) for a in roic.index]
    figura = go.Figure()

    figura.add_trace(
        go.Scatter(
            x=anos,
            y=[wacc] * len(anos),
            name="WACC (custo de capital)",
            mode="lines",
            line={"color": p.serie(1), "width": LARGURA_LINHA, "dash": "dash"},
            hovertemplate=f"<b>WACC</b>: {_formatar_pct(wacc)}<extra></extra>",
        )
    )
    figura.add_trace(
        go.Scatter(
            x=anos,
            y=roic.astype(float),
            name="ROIC (retorno sobre o capital)",
            mode="lines+markers",
            line={"color": p.serie(0), "width": LARGURA_LINHA},
            marker={"size": TAMANHO_MARCADOR, "color": p.serie(0)},
            fill="tonexty",
            fillcolor="rgba(42,120,214,0.12)",
            connectgaps=False,
            hovertemplate="<b>ROIC</b>: %{y:.1%}<extra></extra>",
        )
    )

    layout = layout_base(340, titulo)
    layout["yaxis"]["tickformat"] = ".0%"
    figura.update_layout(**layout)
    return figura


def cascata_ponte(
    itens: list[tuple[str, float]],
    unidade: str = "",
    titulo: str = "Da empresa ao acionista",
    em_dias: bool = False,
) -> go.Figure:
    """Cascata de uma ponte: de um total a outro, item a item.

    A cascata e a forma certa aqui porque a pergunta e de composicao: quanto
    cada item tira ou acrescenta ao caminho entre os dois totais. Um grafico de
    barras soltas perderia justamente o encadeamento.

    ``em_dias`` troca a formatacao de moeda por dias -- a ponte do ciclo de caixa
    e a mesma figura sobre outra unidade, e duplicar a funcao para trocar o
    sufixo faria as duas divergirem na primeira mudanca de estilo.
    """
    p = paleta()
    rotulos = [nome for nome, _ in itens]
    valores = [valor for _, valor in itens]
    medidas = ["absolute"] + ["relative"] * (len(itens) - 2) + ["total"]

    figura = go.Figure(
        go.Waterfall(
            orientation="v",
            measure=medidas,
            x=rotulos,
            y=valores,
            text=(
                [f"{v:,.0f} d" for v in valores]
                if em_dias
                else [_formatar_moeda(v) for v in valores]
            ),
            textposition="outside",
            connector={"line": {"color": p.grade, "width": 1}},
            increasing={"marker": {"color": p.serie(2)}},
            decreasing={"marker": {"color": p.serie(1)}},
            totals={"marker": {"color": p.serie(0)}},
            hovertemplate=(
                "<b>%{x}</b>: %{y:,.0f} dias<extra></extra>"
                if em_dias
                else "<b>%{x}</b>: %{y:,.1f} " + unidade + "<extra></extra>"
            ),
        )
    )

    layout = layout_base(400, titulo)
    layout["hovermode"] = "closest"
    layout["showlegend"] = False
    layout["xaxis"]["tickangle"] = -30
    figura.update_layout(**layout)
    return figura


def composicao_do_valor(
    vp_explicito: float, vp_terminal: float, unidade: str = ""
) -> go.Figure:
    """Quanto do valor vem da projecao e quanto vem da perpetuidade.

    Uma barra empilhada unica, porque a pergunta e de proporcao entre duas
    partes de um todo. Os dois segmentos sao separados por 2px de superficie
    para nao se lerem como um bloco continuo.
    """
    p = paleta()
    total = vp_explicito + vp_terminal
    figura = go.Figure()

    for rotulo, valor, cor in (
        ("Projeção explícita", vp_explicito, p.serie(0)),
        ("Perpetuidade", vp_terminal, p.serie(3)),
    ):
        fracao = valor / total if total else 0
        figura.add_trace(
            go.Bar(
                y=["Enterprise Value"],
                x=[valor],
                name=rotulo,
                orientation="h",
                marker={"color": cor, "line": {"width": 2, "color": p.superficie}},
                text=f"{rotulo}<br>{_formatar_pct(fracao, 0)}",
                textposition="inside",
                insidetextanchor="middle",
                textfont={"color": "#ffffff", "size": 12},
                hovertemplate=(
                    f"<b>{rotulo}</b>: %{{x:,.1f}} {unidade} "
                    f"({_formatar_pct(fracao)})<extra></extra>"
                ),
            )
        )

    layout = layout_base(150, "De onde vem o valor")
    layout["barmode"] = "stack"
    layout["hovermode"] = "closest"
    layout["showlegend"] = False
    layout["xaxis"]["showticklabels"] = False
    layout["yaxis"]["showticklabels"] = False
    layout["yaxis"]["gridcolor"] = "rgba(0,0,0,0)"
    figura.update_layout(**layout)
    return figura


def fluxos_projetados(
    anos: list[int],
    fluxos: np.ndarray,
    descontados: np.ndarray,
    unidade: str = "",
) -> go.Figure:
    """Fluxo nominal contra fluxo trazido a valor presente.

    As duas series estao na mesma unidade e no mesmo eixo. A diferenca entre as
    barras e o custo do tempo -- visualmente, e quanto o dinheiro do futuro
    encolhe ao chegar em hoje.
    """
    dados = pd.DataFrame(
        {ano: [f, d] for ano, f, d in zip(anos, fluxos, descontados)},
        index=["FCFF nominal", "FCFF descontado"],
    )
    return barras_temporais(dados, "Fluxo de caixa projetado", unidade, altura=330)


def mapa_de_calor(
    tabela: pd.DataFrame, titulo: str = "", unidade: str = ""
) -> go.Figure:
    """Tabela de sensibilidade como mapa de calor.

    Escala sequencial de um unico tom, do claro ao escuro: a variavel e
    magnitude, nao categoria nem polaridade. Cada celula traz o numero escrito,
    porque a cor sozinha nao se le com precisao suficiente para um valuation.
    """
    p = paleta()
    valores = tabela.to_numpy(dtype=float)
    escala = [
        [i / (len(p.sequencial) - 1), cor] for i, cor in enumerate(p.sequencial)
    ]

    figura = go.Figure(
        go.Heatmap(
            z=valores,
            x=[str(c) for c in tabela.columns],
            y=[str(i) for i in tabela.index],
            colorscale=escala,
            texttemplate="%{text}",
            text=[[_formatar_moeda(v) for v in linha] for linha in valores],
            textfont={"size": 11},
            hovertemplate=(
                f"{tabela.index.name}: %{{y}}<br>{tabela.columns.name}: %{{x}}"
                f"<br><b>%{{z:,.1f}} {unidade}</b><extra></extra>"
            ),
            colorbar={
                "outlinewidth": 0,
                "tickfont": {"size": 10, "color": p.texto_secundario},
                "thickness": 10,
            },
            xgap=2,
            ygap=2,
        )
    )

    layout = layout_base(max(280, 80 + 44 * len(tabela)), titulo)
    layout["hovermode"] = "closest"
    layout["yaxis"]["autorange"] = "reversed"
    layout["yaxis"]["gridcolor"] = "rgba(0,0,0,0)"
    # Os rotulos dos eixos sao textos ja formatados ("11,50%"). Sem forcar o eixo
    # como categorico, o Plotly os reinterpreta como numeros e reescreve a escala,
    # trocando "11,50%" por "11.5" e destruindo a formatacao.
    layout["xaxis"]["type"] = "category"
    layout["yaxis"]["type"] = "category"
    figura.update_layout(**layout)
    return figura


def distribuicao_simulada(
    valores: np.ndarray,
    percentis: dict[str, float],
    caso_base: float | None = None,
    unidade: str = "",
) -> go.Figure:
    """Histograma do Monte Carlo com as marcas que se le de verdade.

    O histograma sozinho diz pouco; o que responde a pergunta do analista sao as
    linhas de referencia: onde esta a mediana, onde estao os extremos plausiveis
    e onde caiu o caso base.
    """
    p = paleta()
    figura = go.Figure(
        go.Histogram(
            x=valores,
            nbinsx=44,
            marker={"color": p.serie(0), "line": {"width": 0}},
            hovertemplate=f"%{{x:,.0f}} {unidade}<br>%{{y}} simulações<extra></extra>",
            name="Simulações",
        )
    )

    marcas = [
        ("P5", percentis.get("P5"), p.texto_suave, "dot"),
        ("Mediana", percentis.get("P50"), p.serie(1), "solid"),
        ("P95", percentis.get("P95"), p.texto_suave, "dot"),
    ]
    if caso_base is not None:
        marcas.append(("Caso base", caso_base, p.serie(2), "dash"))

    # Mediana e caso base costumam cair quase no mesmo ponto -- e esse e o
    # resultado desejavel, nao um acidente. As anotacoes sao escalonadas em
    # alturas diferentes para que os dois rotulos continuem legiveis quando isso
    # acontece.
    validas = [(r, v, c, t) for r, v, c, t in marcas if v is not None and np.isfinite(v)]
    ordenadas = sorted(range(len(validas)), key=lambda i: validas[i][1])
    altura_por_marca = {indice: 0 for indice in range(len(validas))}
    for posicao, indice in enumerate(ordenadas):
        altura_por_marca[indice] = (posicao % 2) * 30

    for indice, (rotulo, valor, cor, traco) in enumerate(validas):
        figura.add_vline(
            x=valor,
            line={"color": cor, "width": 2, "dash": traco},
            annotation_text=f"{rotulo}<br>{_formatar_moeda(valor)}",
            annotation_position="top",
            annotation_font={"size": 10, "color": cor},
            annotation_yshift=altura_por_marca[indice],
        )

    layout = layout_base(380, "Distribuição do valor simulado")
    layout["hovermode"] = "closest"
    layout["showlegend"] = False
    layout["bargap"] = 0.02
    figura.update_layout(**layout)
    return figura


def barras_de_faixa(
    rotulos: list[str],
    valores: list[float],
    referencia: float | None = None,
    rotulo_referencia: str = "DCF",
    titulo: str = "",
    unidade: str = "",
) -> go.Figure:
    """Valor implicito por metodo, com uma linha de referencia.

    Serve para cotejar o resultado do fluxo de caixa descontado com o que os
    multiplos de mercado sugerem. Quando os dois discordam muito, um dos dois
    esta contando uma historia que o outro nao aceita -- e isso e informacao.
    """
    p = paleta()
    finitos = [(r, v) for r, v in zip(rotulos, valores) if np.isfinite(v)]
    if not finitos:
        return go.Figure()
    rotulos, valores = zip(*finitos)

    figura = go.Figure(
        go.Bar(
            y=list(rotulos),
            x=list(valores),
            orientation="h",
            marker={"color": p.serie(0), "line": {"width": 0}},
            text=[_formatar_moeda(v) for v in valores],
            textposition="outside",
            textfont={"size": 11, "color": p.texto_secundario},
            hovertemplate=f"<b>%{{y}}</b>: %{{x:,.1f}} {unidade}<extra></extra>",
        )
    )

    if referencia is not None and np.isfinite(referencia):
        figura.add_vline(
            x=referencia,
            line={"color": p.serie(1), "width": 2, "dash": "dash"},
            annotation_text=f"{rotulo_referencia}: {_formatar_moeda(referencia)}",
            annotation_position="top",
            annotation_font={"size": 11, "color": p.serie(1)},
        )

    layout = layout_base(90 + 42 * len(rotulos), titulo)
    layout["hovermode"] = "closest"
    layout["showlegend"] = False
    layout["yaxis"]["gridcolor"] = "rgba(0,0,0,0)"
    figura.update_layout(**layout)
    return figura


def pequenos_multiplos(
    dados: pd.DataFrame, formatos: dict[str, str], altura_linha: int = 150
) -> list[tuple[str, go.Figure]]:
    """Um grafico por indicador, cada um com sua propria escala.

    E a resposta correta para a decomposicao de DuPont: margem, giro e
    alavancagem tem grandezas incompativeis (percentual, multiplo, multiplo).
    Coloca-los no mesmo eixo achataria dois deles; usar dois eixos seria pior
    ainda. Pequenos multiplos preservam a leitura de cada um.
    """
    p = paleta()
    figuras = []
    for indice, (nome, serie) in enumerate(dados.iterrows()):
        cor = p.serie(indice)
        formato = formatos.get(str(nome), ",.2f")
        figura = go.Figure(
            go.Scatter(
                x=[str(c) for c in dados.columns],
                y=serie.astype(float),
                mode="lines+markers",
                line={"color": cor, "width": LARGURA_LINHA},
                marker={"size": TAMANHO_MARCADOR, "color": cor},
                connectgaps=False,
                hovertemplate=f"<b>{nome}</b>: %{{y:{formato}}}<extra></extra>",
                showlegend=False,
            )
        )
        layout = layout_base(altura_linha, str(nome))
        layout["yaxis"]["tickformat"] = formato
        layout["margin"] = {"l": 8, "r": 8, "t": 38, "b": 8}
        layout["title"]["font"] = {"size": 12, "color": p.texto_secundario}
        figura.update_layout(**layout)
        figuras.append((str(nome), figura))
    return figuras


def cascata_tsr(
    contribuicoes: list[tuple[str, float]], total: float, titulo: str = ""
) -> go.Figure:
    """Cascata das fontes do retorno esperado, em pontos de retorno anual.

    A cascata e a forma certa porque a pergunta e de composicao: cada fonte
    soma ou subtrai pontos ao retorno, e o encadeamento termina no TSR. As
    parcelas somam o total exatamente, entao a barra final nao e um arredondamento.
    """
    p = paleta()
    rotulos = [nome for nome, _ in contribuicoes] + ["TSR esperado"]
    valores = [valor for _, valor in contribuicoes] + [total]
    medidas = ["relative"] * len(contribuicoes) + ["total"]

    figura = go.Figure(
        go.Waterfall(
            orientation="v",
            measure=medidas,
            x=rotulos,
            y=valores,
            text=[_formatar_pct(v) for v in valores],
            textposition="outside",
            connector={"line": {"color": p.grade, "width": 1}},
            increasing={"marker": {"color": p.serie(2)}},
            decreasing={"marker": {"color": p.serie(1)}},
            totals={"marker": {"color": p.serie(0)}},
            hovertemplate="<b>%{x}</b>: %{y:.2%}<extra></extra>",
        )
    )

    layout = layout_base(400, titulo)
    layout["hovermode"] = "closest"
    layout["showlegend"] = False
    layout["yaxis"]["tickformat"] = ".1%"
    layout["xaxis"]["tickangle"] = -20
    figura.update_layout(**layout)
    return figura


def tsr_por_preco(
    precos: list[float],
    retornos: list[float],
    preco_atual: float,
    retorno_exigido: float | None = None,
    unidade: str = "",
) -> go.Figure:
    """Retorno esperado em funcao do preco pago.

    Deixa visivel a unica variavel que o investidor de fato controla. A linha do
    retorno exigido cruza a curva exatamente no preco maximo que faz sentido
    pagar.
    """
    p = paleta()
    figura = go.Figure(
        go.Scatter(
            x=precos,
            y=retornos,
            mode="lines+markers",
            line={"color": p.serie(0), "width": LARGURA_LINHA},
            marker={"size": TAMANHO_MARCADOR, "color": p.serie(0)},
            name="TSR esperado",
            hovertemplate=(
                f"Preço: %{{x:,.1f}} {unidade}<br><b>TSR: %{{y:.2%}}</b><extra></extra>"
            ),
        )
    )

    figura.add_vline(
        x=preco_atual,
        line={"color": p.texto_suave, "width": 2, "dash": "dot"},
        annotation_text="preço atual",
        annotation_position="top",
        annotation_font={"size": 10, "color": p.texto_secundario},
    )
    if retorno_exigido is not None and np.isfinite(retorno_exigido):
        figura.add_hline(
            y=retorno_exigido,
            line={"color": p.serie(1), "width": 2, "dash": "dash"},
            annotation_text=f"retorno exigido {_formatar_pct(retorno_exigido)}",
            annotation_position="right",
            annotation_font={"size": 10, "color": p.serie(1)},
        )

    layout = layout_base(340, "Retorno esperado por preço de entrada")
    layout["hovermode"] = "x"
    layout["showlegend"] = False
    layout["yaxis"]["tickformat"] = ".0%"
    figura.update_layout(**layout)
    return figura


def linhas_em_dias(
    dados: pd.DataFrame,
    titulo: str = "",
    altura: int = 340,
    total: str | None = None,
) -> go.Figure:
    """Prazos e ciclo ao longo do tempo, em dias.

    Irma de :func:`linhas_percentuais`, e separada dela pelo mesmo motivo que a
    justifica: series so podem dividir um eixo quando estao na mesma unidade.
    Dia e dia -- as tres pernas e o ciclo somam entre si e se leem juntas.

    O **total vem em linha grossa e as parcelas mais finas**: as tres pernas
    explicam a quarta serie, e desenhar as quatro com o mesmo peso faz o leitor
    procurar qual delas e a soma. ``total`` diz **qual** e ela pelo nome, e nao
    por pedaco de texto: reconhecer o total por substring quebraria calado no dia
    em que o rotulo mudasse -- e ele mudou, quando a tela passou a acentua-lo.
    Sem ``total``, a ultima linha e a soma, que e a ordem em que se monta a
    tabela.
    """
    p = paleta()
    figura = go.Figure()
    nome_do_total = total if total is not None else (
        str(dados.index[-1]) if len(dados) else ""
    )

    for indice, (nome, serie) in enumerate(dados.iterrows()):
        e_total = str(nome) == nome_do_total
        cor = p.texto_primario if e_total else p.serie(indice)
        valores = serie.astype(float)
        figura.add_trace(
            go.Scatter(
                x=[str(c) for c in dados.columns],
                y=valores,
                name=str(nome),
                mode="lines+markers",
                line={
                    "color": cor,
                    "width": LARGURA_LINHA + 1 if e_total else LARGURA_LINHA,
                    "dash": "solid" if e_total else "dot",
                },
                marker={"size": TAMANHO_MARCADOR, "color": cor},
                connectgaps=False,
                hovertemplate=f"<b>{nome}</b>: %{{y:,.0f}} dias<extra></extra>",
            )
        )
        validos = valores.dropna()
        if e_total and not validos.empty:
            figura.add_annotation(
                x=str(validos.index[-1]),
                y=float(validos.iloc[-1]),
                text=f"{float(validos.iloc[-1]):,.0f} d",
                showarrow=False,
                xshift=28,
                font={"size": 11, "color": p.texto_secundario},
            )

    layout = layout_base(altura, titulo)
    layout["yaxis"]["ticksuffix"] = " d"
    layout["showlegend"] = True
    figura.update_layout(**layout)
    return figura

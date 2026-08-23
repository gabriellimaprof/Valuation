"""Paleta e template visual unicos do app.

A paleta e a instancia de referencia validada do guia de dataviz: as cores nao
foram escolhidas por gosto, e sim verificadas para banda de luminosidade, piso
de croma, separacao sob daltonismo e contraste contra a superficie -- em modo
claro e escuro. As cores categoricas sao atribuidas **sempre na mesma ordem**,
nunca cicladas, para que uma serie mantenha a mesma cor entre graficos e entre
telas.

Em modo claro, tres dos tons ficam abaixo de 3:1 de contraste com o fundo. Isso
obriga a *regra do relevo*: todo grafico que os usa acompanha rotulo visivel ou
tabela de dados. E por isso que cada grafico do app vem com um expansor
"ver dados" ao lado -- nao e enfeite, e requisito de acessibilidade.
"""

from __future__ import annotations

from dataclasses import dataclass

import streamlit as st


@dataclass(frozen=True)
class Paleta:
    """Cores de um modo (claro ou escuro)."""

    superficie: str
    grade: str
    texto_primario: str
    texto_secundario: str
    texto_suave: str
    series: tuple[str, ...]
    sequencial: tuple[str, ...]
    bom: str
    atencao: str
    grave: str
    critico: str

    def serie(self, indice: int) -> str:
        """Cor da n-esima serie, em ordem fixa.

        Passar de oito series nao gera cor nova: o guia manda agrupar em
        "Outros" ou separar em pequenos multiplos. Por isso o indice satura no
        ultimo tom em vez de reciclar o primeiro.
        """
        return self.series[min(indice, len(self.series) - 1)]


CLARO = Paleta(
    superficie="#fcfcfb",
    grade="#e8e7e3",
    texto_primario="#0b0b0b",
    texto_secundario="#52514e",
    texto_suave="#84837d",
    series=(
        "#2a78d6",  # azul
        "#eb6834",  # laranja
        "#1baf7a",  # agua
        "#eda100",  # amarelo
        "#e87ba4",  # magenta
        "#008300",  # verde
        "#4a3aa7",  # violeta
        "#e34948",  # vermelho
    ),
    sequencial=(
        "#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5",
        "#2a78d6", "#256abf", "#184f95", "#0d366b",
    ),
    bom="#008300",
    atencao="#eda100",
    grave="#eb6834",
    critico="#e34948",
)

ESCURO = Paleta(
    superficie="#1a1a19",
    grade="#383835",
    texto_primario="#ffffff",
    texto_secundario="#c3c2b7",
    texto_suave="#8f8e86",
    series=(
        "#3987e5",
        "#d95926",
        "#199e70",
        "#c98500",
        "#d55181",
        "#008300",
        "#9085e9",
        "#e66767",
    ),
    sequencial=(
        "#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5",
        "#2a78d6", "#256abf", "#184f95", "#0d366b",
    ),
    bom="#008300",
    atencao="#c98500",
    grave="#d95926",
    critico="#e66767",
)


def modo_escuro() -> bool:
    """O usuario esta no tema escuro?"""
    try:
        contexto = st.context.theme
        return bool(contexto and contexto.type == "dark")
    except Exception:  # noqa: BLE001 - versoes antigas nao expoem o contexto
        return False


def paleta() -> Paleta:
    """Paleta do modo em vigor. A escura tem tons proprios, nao e um espelho."""
    return ESCURO if modo_escuro() else CLARO


def layout_base(altura: int = 320, titulo: str = "") -> dict:
    """Layout comum a todos os graficos: grade recessiva, sem moldura, hover ativo."""
    p = paleta()
    return {
        "height": altura,
        # O titulo e ancorado ao topo do container e a legenda ao topo da area de
        # plotagem. Sem essa separacao os dois disputam a mesma faixa vertical e
        # se sobrepoem assim que o titulo passa de poucas palavras.
        "title": {
            "text": titulo,
            "font": {"size": 15, "color": p.texto_primario},
            "x": 0,
            "xanchor": "left",
            "y": 1,
            "yanchor": "top",
            "yref": "container",
            "pad": {"t": 4, "b": 8},
        },
        "paper_bgcolor": "rgba(0,0,0,0)",
        "plot_bgcolor": "rgba(0,0,0,0)",
        "font": {"color": p.texto_secundario, "size": 12},
        "margin": {"l": 8, "r": 8, "t": 74 if titulo else 34, "b": 8},
        "hovermode": "x unified",
        "hoverlabel": {
            "bgcolor": p.superficie,
            "font": {"color": p.texto_primario, "size": 12},
            "bordercolor": p.grade,
        },
        "legend": {
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.02,
            "xanchor": "left",
            "x": 0,
            "font": {"size": 11, "color": p.texto_secundario},
            "bgcolor": "rgba(0,0,0,0)",
        },
        "xaxis": {
            "showgrid": False,
            "zeroline": False,
            "linecolor": p.grade,
            "tickfont": {"size": 11, "color": p.texto_secundario},
        },
        "yaxis": {
            "gridcolor": p.grade,
            "zeroline": True,
            "zerolinecolor": p.grade,
            "showline": False,
            "tickfont": {"size": 11, "color": p.texto_secundario},
        },
    }


# A maior parte da identidade visual vem dos **tokens nativos** em
# `.streamlit/config.toml` -- tipografia, raio, borda, cor primaria, cores de
# grafico. O Streamlit 1.61 expoe um sistema de design completo, e usa-lo e
# melhor que empilhar CSS por cima: o token atravessa todo componente, inclusive
# os que este arquivo nao alcanca.
#
# Sobra para o CSS o que token nenhum resolve: medida de linha, os blocos
# proprios do app e o ajuste fino de densidade.
CSS = """
<style>
  /* A linha longa demais e o defeito de legibilidade mais comum em app de
     dado: numa tela de 2.150px o texto corria 150 caracteres por linha, mais
     que o dobro do que se le sem perder o comeco da linha seguinte. A tabela e
     o grafico continuam largos; o texto e que para. */
  /* 1.600px, e nao 1.440: o balanco lado a lado poe sete anos em cada metade,
     e a 1.440 cada lado ficava 32px curto e as duas tabelas rolavam na
     horizontal -- justamente o que a leitura em T existe para evitar. A medida
     de linha do texto nao depende disto: ela e travada em 88ch logo abaixo. */
  .stMainBlockContainer { max-width: 1600px; }
  .stMainBlockContainer [data-testid="stMarkdownContainer"] p,
  .stMainBlockContainer [data-testid="stCaptionContainer"] p { max-width: 88ch; }

  .bloco-conceito {
    border-left: 3px solid var(--st-primary-color, #2a78d6);
    padding: 0.7rem 1rem;
    margin: 0.4rem 0 1rem 0;
    background: var(--st-blue-background-color, rgba(42, 120, 214, 0.06));
    border-radius: 0 8px 8px 0;
    font-size: 0.92rem;
    line-height: 1.55;
  }
  .bloco-conceito strong { font-weight: 600; }
  .bloco-conceito p:last-child { margin-bottom: 0; }

  .rotulo-etapa {
    text-transform: uppercase;
    letter-spacing: 0.08em;
    font-size: 0.72rem;
    font-weight: 600;
    opacity: 0.6;
    margin-bottom: 0.2rem;
  }

  /* Um titulo de secao tinha tres aparencias diferentes pelo app. Agora tem uma,
     e ela nao e um heading do markdown: h3 traz margem e escala de documento,
     e aqui o que se quer e uma marca de bloco dentro de uma tela. */
  .titulo-secao {
    font-size: 1.05rem;
    font-weight: 600;
    letter-spacing: -0.01em;
    margin: 0.4rem 0 0.15rem 0;
  }

  /* Numero em cartao e numero em tabela alinham por algarismo tabular. Sem isto
     o "1" ocupa menos largura que o "8" e a coluna serrilha. */
  [data-testid="stMetricValue"],
  [data-testid="stMetric"] { font-variant-numeric: tabular-nums; }
  [data-testid="stMetricLabel"] { opacity: 0.75; font-size: 0.82rem; }

  /* Densidade: o padrao respira demais para uma tela com doze indicadores. */
  [data-testid="stMetric"] { padding: 0.7rem 0.9rem; }
  hr { margin: 1.1rem 0; }

  /* O numero da etapa no Inicio. Recessivo de proposito: ele ordena a lista,
     mas quem se le e o nome da etapa. */
  .numero-do-passo {
    font-size: 1.15rem;
    font-weight: 600;
    font-variant-numeric: tabular-nums;
    opacity: 0.35;
    text-align: right;
  }

  /* O link de pagina vira alvo de clique de linha inteira nas listas. */
  [data-testid="stPageLink"] a { padding: 0.15rem 0; }

  /* A barra lateral e um trilho de resumo, e nao a tela principal: o numero de
     tamanho heroico nao cabe na largura dela e sai truncado ("11,…"). Truncado
     e pior que pequeno, porque parece um numero inteiro. */
  [data-testid="stSidebar"] [data-testid="stMetricValue"] { font-size: 1.15rem; }
  [data-testid="stSidebar"] [data-testid="stMetric"] { padding: 0.5rem 0.65rem; }
  [data-testid="stSidebar"] [data-testid="stMetricLabel"] { font-size: 0.78rem; }
</style>
"""


# A demonstracao publicada nao e uma tabela qualquer: ela e uma **arvore**, e o
# nivel de cada linha e informacao contabil, nao enfeite. "Ativo Total" e
# "JSCP a receber" ocupavam o mesmo peso visual, entao o olho tinha de ler os
# 210 rotulos para achar os totais.
#
# O peso vai no texto e a cor de fundo so nos dois primeiros niveis. Os niveis
# fracos sao feitos com **opacidade sobre a cor do tema**, e nao com um cinza
# fixo: cinza escolhido para o modo claro vira ilegivel no escuro, e a mesma
# regra tem de servir aos dois.
TABELA_CSS = """
<style>
  .df-publicada {{
    max-height: 74vh;
    overflow: auto;
    border: 1px solid {grade};
    border-radius: 8px;
  }}
  .df-publicada table {{
    border-collapse: separate;
    border-spacing: 0;
    width: 100%;
    font-size: 0.85rem;
    font-variant-numeric: tabular-nums;
  }}
  .df-publicada thead th {{
    position: sticky;
    top: 0;
    z-index: 3;
    background: {cabecalho};
    color: #ffffff;
    font-weight: 600;
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    text-align: right;
    padding: 0.55rem 0.75rem;
    white-space: nowrap;
  }}
  .df-publicada thead th.conta {{
    text-align: left;
    left: 0;
    z-index: 4;
  }}
  .df-publicada td {{
    padding: 0.3rem 0.75rem;
    border-top: 1px solid {grade};
    text-align: right;
    white-space: nowrap;
  }}
  .df-publicada td.conta {{
    position: sticky;
    left: 0;
    z-index: 2;
    text-align: left;
    background: inherit;
    min-width: 20rem;
    white-space: normal;
  }}

  /* O balanco lado a lado poe sete anos em meia largura, duas vezes. A coluna
     de rotulo tem de encolher, senao a tabela rola na horizontal em ambos os
     lados e a leitura em T -- que e o motivo de estar lado a lado -- se perde. */
  .df-publicada.compacta table {{ font-size: 0.78rem; }}
  .df-publicada.compacta td.conta {{ min-width: 8.5rem; max-width: 13rem; }}
  .df-publicada.compacta td,
  .df-publicada.compacta thead th {{ padding-left: 0.3rem; padding-right: 0.3rem; }}
  .df-publicada.compacta thead th {{ font-size: 0.66rem; letter-spacing: 0.02em; }}
  .df-publicada.compacta tr.n1 {{ font-size: 0.85rem; }}
  .df-publicada.compacta tr.n4 {{ font-size: 0.76rem; }}
  .df-publicada.compacta tr.n5 {{ font-size: 0.74rem; }}
  .df-publicada tr {{ background: {superficie}; color: {texto}; }}
  .df-publicada tr.n1 {{
    background: {tinta_forte};
    font-weight: 700;
    font-size: 0.9rem;
  }}
  .df-publicada tr.n1 td {{ border-top: 2px solid {cabecalho}; }}
  .df-publicada tr.n2 {{ background: {tinta_fraca}; font-weight: 600; }}
  .df-publicada tr.n3 {{ font-weight: 500; }}
  .df-publicada tr.n4 {{ font-weight: 400; color: {texto_fraco}; font-size: 0.8rem; }}
  .df-publicada tr.n5 {{ font-weight: 400; color: {texto_suave}; font-size: 0.78rem; }}
  .df-publicada tr:hover {{ background: {realce}; }}
  .df-publicada td.negativo {{ color: {negativo}; }}
  .df-publicada td.nulo {{ color: {texto_suave}; }}
  /* Celula de texto numa tabela de numeros: a direita ela nao se le. */
  .df-publicada td.texto {{ text-align: left; white-space: normal; }}
  .df-publicada .unidade {{
    margin-left: 0.45rem;
    padding: 0.05rem 0.35rem;
    border: 1px solid {grade};
    border-radius: 4px;
    font-size: 0.68rem;
    font-weight: 500;
    color: {texto_suave};
    white-space: nowrap;
  }}
</style>
"""

# Fundos **opacos**, e nao tinta translucida. A primeira coluna e grudada
# (``position: sticky``) para o rotulo nao sumir ao rolar os anos de lado, e ela
# herda o fundo da propria linha: com fundo semitransparente os numeros passariam
# por tras do rotulo durante a rolagem. Sao a superficie do tema misturada ao
# azul da paleta a 14% e a 6%, ja compostas.
FUNDOS = {
    "claro": {"n1": "#dfeaf6", "n2": "#eff4f9", "realce": "#faefd8"},
    "escuro": {"n1": "#203042", "n2": "#1d242b", "realce": "#3a2d15"},
}

# Passos mais escuros da rampa sequencial, escolhidos por contraste medido e nao
# por gosto: o cabecalho e texto branco pequeno em caixa alta.
CABECALHO_DA_TABELA = {"claro": "#256abf", "escuro": "#184f95"}

# O vermelho do negativo e **reforco** do sinal de menos, nao a unica pista --
# mas 3,57:1 sobre a tinta do subtotal e ilegivel, nao discreto. Estes dao
# 5,09:1 no claro e 6,27:1 no escuro sobre os fundos das linhas.
NEGATIVO_NA_TABELA = {"claro": "#c1302f", "escuro": "#f08585"}


def tabela_css() -> str:
    """CSS da demonstracao publicada, com as cores do modo em vigor."""
    p = paleta()
    fundos = FUNDOS["escuro" if p is ESCURO else "claro"]
    return TABELA_CSS.format(
        grade=p.grade,
        superficie=p.superficie,
        texto=p.texto_primario,
        texto_fraco=p.texto_secundario,
        texto_suave=p.texto_secundario,
        # Nao e `serie(0)`: branco sobre ele da 4,42:1, abaixo do minimo para
        # texto pequeno. Um passo mais escuro da propria rampa sequencial da
        # 5,39:1 (claro) e 8,10:1 (escuro). Medido no navegador, e nao no token.
        cabecalho=CABECALHO_DA_TABELA["escuro" if p is ESCURO else "claro"],
        tinta_forte=fundos["n1"],
        tinta_fraca=fundos["n2"],
        realce=fundos["realce"],
        negativo=NEGATIVO_NA_TABELA["escuro" if p is ESCURO else "claro"],
    )


def aplicar_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)
    st.markdown(tabela_css(), unsafe_allow_html=True)

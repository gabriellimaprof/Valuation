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


CSS = """
<style>
  .bloco-conceito {
    border-left: 3px solid var(--primary-color, #2a78d6);
    padding: 0.6rem 0.9rem;
    margin: 0.4rem 0 1rem 0;
    background: rgba(42, 120, 214, 0.06);
    border-radius: 0 6px 6px 0;
    font-size: 0.92rem;
    line-height: 1.5;
  }
  .bloco-conceito strong { font-weight: 600; }
  .rotulo-etapa {
    text-transform: uppercase;
    letter-spacing: 0.08em;
    font-size: 0.72rem;
    opacity: 0.65;
    margin-bottom: 0.2rem;
  }
  div[data-testid="stMetricValue"] { font-size: 1.6rem; }
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


def tabela_css() -> str:
    """CSS da demonstracao publicada, com as cores do modo em vigor."""
    p = paleta()
    fundos = FUNDOS["escuro" if p is ESCURO else "claro"]
    return TABELA_CSS.format(
        grade=p.grade,
        superficie=p.superficie,
        texto=p.texto_primario,
        texto_fraco=p.texto_secundario,
        texto_suave=p.texto_suave,
        cabecalho=p.serie(0),
        tinta_forte=fundos["n1"],
        tinta_fraca=fundos["n2"],
        realce=fundos["realce"],
        negativo=p.critico,
    )


def aplicar_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)
    st.markdown(tabela_css(), unsafe_allow_html=True)

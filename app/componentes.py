"""Pecas de interface reutilizadas pelas telas."""

from __future__ import annotations

import re

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .textos import CONCEITOS


_NEGRITO = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
_ITALICO = re.compile(r"(?<!\*)\*([^*]+?)\*(?!\*)", re.DOTALL)
_CODIGO = re.compile(r"`([^`]+?)`")


def _markdown_para_html(texto: str) -> str:
    """Converte a marcacao usada nos textos para HTML.

    Necessario porque o bloco de conceito e uma ``<div>`` propria, e o Streamlit
    nao interpreta markdown dentro de HTML cru -- sem isto os asteriscos
    apareceriam literais na tela.
    """
    texto = _NEGRITO.sub(r"<strong>\1</strong>", texto)
    texto = _ITALICO.sub(r"<em>\1</em>", texto)
    return _CODIGO.sub(r"<code>\1</code>", texto)


def conceito(chave: str, titulo: str = "") -> None:
    """Bloco explicativo de um conceito, sempre no mesmo formato.

    Fica visivel por padrao em vez de escondido atras de um clique: a parte
    educacional do app so funciona se o texto estiver no caminho do olho.
    """
    texto = CONCEITOS.get(chave)
    if not texto:
        return
    prefixo = f"<strong>{titulo}</strong><br>" if titulo else ""
    st.markdown(
        f'<div class="bloco-conceito">{prefixo}{_markdown_para_html(texto)}</div>',
        unsafe_allow_html=True,
    )


def etapa(rotulo: str, titulo: str, subtitulo: str = "") -> None:
    """Cabecalho padrao de tela."""
    st.markdown(f'<div class="rotulo-etapa">{rotulo}</div>', unsafe_allow_html=True)
    st.title(titulo)
    if subtitulo:
        st.caption(subtitulo)


def grafico(figura: go.Figure, dados: pd.DataFrame | pd.Series | None = None,
            rotulo_dados: str = "Ver os dados do gráfico") -> None:
    """Exibe um grafico com a tabela de dados disponivel ao lado.

    A tabela nao e opcional por acaso: parte da paleta fica abaixo de 3:1 de
    contraste no modo claro, e o guia de acessibilidade exige rotulo visivel ou
    visao tabular nesse caso. Aqui ela tambem serve para copiar numero para a
    planilha sem precisar exportar tudo.
    """
    st.plotly_chart(figura, width="stretch", config={"displayModeBar": False})
    if dados is not None:
        with st.expander(rotulo_dados):
            st.dataframe(dados, width="stretch")


def metrica(
    rotulo: str,
    valor: float | None,
    formato: str = "moeda",
    unidade: str = "",
    ajuda: str = "",
    delta: str | None = None,
) -> None:
    """Metrica formatada no padrao brasileiro, com ajuda opcional."""
    st.metric(rotulo, formatar(valor, formato, unidade), delta=delta, help=ajuda or None)


def formatar(valor: float | None, formato: str = "moeda", unidade: str = "") -> str:
    """Formata numeros no padrao brasileiro (milhar com ponto, decimal com virgula)."""
    if valor is None or (isinstance(valor, float) and not np.isfinite(valor)):
        return "—"
    if formato == "pct":
        return f"{valor * 100:,.1f}%".replace(".", ",")
    if formato == "pct2":
        return f"{valor * 100:,.2f}%".replace(".", ",")
    if formato == "multiplo":
        return f"{valor:,.2f}x".replace(".", ",")
    if formato == "numero":
        return f"{valor:,.2f}".replace(",", "@").replace(".", ",").replace("@", ".")
    if formato == "dias":
        return f"{valor:,.0f} dias".replace(",", ".")
    texto = f"{valor:,.1f}".replace(",", "@").replace(".", ",").replace("@", ".")
    return f"{texto} {unidade}".strip()


def tabela_formatada(
    dados: pd.DataFrame, formato: str = "moeda", unidade: str = ""
) -> pd.DataFrame:
    """Aplica a formatacao brasileira a um DataFrame inteiro, para exibicao."""
    return dados.map(lambda v: formatar(v, formato, unidade))


def aviso_sem_modelo(erro: str | None) -> None:
    """Mensagem padrao quando as premissas nao fecham."""
    st.error(
        "O modelo não fecha com as premissas atuais, então não há resultado para "
        f"mostrar.\n\n**Motivo:** {erro}"
        if erro
        else "O modelo não fecha com as premissas atuais."
    )
    st.info(
        "O caso mais comum é o crescimento perpétuo ter ficado acima da taxa de "
        "desconto. Volte em **Premissas** ou **Custo de capital** e ajuste."
    )


def barra_de_severidade(erros: int, alertas: int, informacoes: int) -> None:
    """Resumo do diagnostico em tres numeros."""
    colunas = st.columns(3)
    colunas[0].metric("🔴 Erros", erros)
    colunas[1].metric("🟡 Alertas", alertas)
    colunas[2].metric("🔵 Observações", informacoes)


def linha_de_premissas_anuais(
    rotulo: str,
    valores: list[float],
    anos: list[int],
    chave: str,
    formato: str = "%.1f%%",
    percentual: bool = True,
    passo: float = 0.5,
    ajuda: str = "",
) -> list[float]:
    """Editor de uma premissa ano a ano, em colunas.

    Percentuais sao editados em pontos percentuais (12,5) e devolvidos em
    decimais (0,125): pedir que o usuario digite 0,125 e um convite ao erro de
    ordem de grandeza, que e o mais caro de todos em valuation.
    """
    st.markdown(f"**{rotulo}**" + (f" — {ajuda}" if ajuda else ""))
    colunas = st.columns(len(anos))
    novos = []
    for indice, (coluna, ano) in enumerate(zip(colunas, anos)):
        atual = valores[indice] * 100 if percentual else valores[indice]
        novo = coluna.number_input(
            f"{ano}",
            value=float(atual),
            step=passo,
            format=formato.replace("%%", "%") if percentual else "%.2f",
            key=f"{chave}_{indice}",
            label_visibility="visible",
        )
        novos.append(novo / 100 if percentual else novo)
    return novos

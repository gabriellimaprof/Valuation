"""Tela de historico: o que a empresa entregou, e por que entregou aquilo."""

from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st

from .. import estado
from ..componentes import conceito, etapa, formatar, grafico, metrica, tabela_formatada
from ..graficos import (
    barras_ciclo,
    barras_temporais,
    linhas_percentuais,
    pequenos_multiplos,
    roic_versus_wacc,
)


def render() -> None:
    etapa(
        "Passo 2",
        "Histórico",
        "Margens, retorno sobre o capital e reinvestimento dos últimos anos",
    )

    analise = estado.analise()
    if analise is None:
        st.info(
            "Nenhuma demonstração financeira importada ainda. Vá em **Dados** para "
            "importar uma planilha ou baixar o template.\n\n"
            "O app funciona sem histórico, mas você perde a âncora das premissas e as "
            "comparações mais úteis do diagnóstico."
        )
        return

    dfs = analise.demonstracoes
    st.caption(
        f"{dfs.empresa} · {dfs.anos[0]} a {dfs.anos[-1]} · valores em {dfs.unidade}"
    )

    _cartoes(analise, dfs)
    st.divider()

    abas = st.tabs(
        ["Resultado", "Retorno e decomposição", "Reinvestimento", "Capital de giro", "Tudo"]
    )
    with abas[0]:
        _resultado(analise, dfs)
    with abas[1]:
        _retorno(analise)
    with abas[2]:
        _reinvestimento(analise)
    with abas[3]:
        _capital_de_giro(analise)
    with abas[4]:
        st.dataframe(
            analise.indicadores.style.format("{:,.3f}", na_rep="—"),
            width="stretch",
        )
        st.markdown("**Resumo por indicador**")
        st.dataframe(
            analise.resumo().style.format("{:,.3f}", na_rep="—"),
            width="stretch",
        )


def _cartoes(analise, dfs) -> None:
    colunas = st.columns(4)
    with colunas[0]:
        metrica(
            "Receita do último ano",
            dfs.valor("receita_liquida"),
            "moeda",
            dfs.unidade,
        )
    with colunas[1]:
        metrica(
            "Margem EBITDA (mediana)",
            analise.mediana("Margem EBITDA"),
            "pct",
            ajuda="Mediana do período. Resiste melhor a anos atípicos do que a média.",
        )
    with colunas[2]:
        metrica(
            "ROIC (mediana)",
            analise.mediana("ROIC"),
            "pct",
            ajuda="Retorno sobre o capital investido, calculado sobre capital médio.",
        )
    with colunas[3]:
        metrica(
            "Dívida líquida / EBITDA",
            analise.ultimo("Divida liquida / EBITDA"),
            "multiplo",
            ajuda="Quantos anos de EBITDA seriam necessários para quitar a dívida líquida.",
        )


def _resultado(analise, dfs) -> None:
    st.markdown("#### Evolução do resultado")
    st.caption(
        "Receita e EBITDA em barras; margens em linhas, no gráfico seguinte. São dois "
        "painéis e não um só porque valor e percentual não dividem escala sem enganar."
    )

    linhas = pd.DataFrame(
        {
            "Receita líquida": dfs.serie("receita_liquida"),
            "EBITDA": dfs.ebitda(),
            "Lucro líquido": dfs.serie("lucro_liquido"),
        }
    ).T
    grafico(
        barras_temporais(linhas, "Receita, EBITDA e lucro", dfs.unidade),
        tabela_formatada(linhas, "moeda", dfs.unidade),
    )

    margens = analise.indicadores.loc[
        ["Margem bruta", "Margem EBITDA", "Margem EBIT", "Margem liquida"]
    ]
    grafico(
        linhas_percentuais(margens, "Margens"),
        margens.style.format("{:.1%}", na_rep="—"),
    )
    st.caption(
        "Margens que caem com receita subindo indicam crescimento comprado com preço "
        "ou com custo — vale checar antes de projetar margem estável."
    )


def _retorno(analise) -> None:
    conceito("roic", "O indicador mais importante do valuation")

    resultado = estado.resultado()
    roic = analise.linha("ROIC").dropna()
    if not roic.empty and resultado is not None:
        wacc = resultado.custo_capital.wacc_brl
        grafico(
            roic_versus_wacc(roic, wacc),
            pd.DataFrame({"ROIC": roic, "WACC": wacc}).T.style.format("{:.1%}"),
        )
        spread = float(roic.iloc[-1]) - wacc
        if spread > 0:
            st.success(
                f"A empresa gerou {formatar(spread, 'pct')} acima do custo de capital no "
                "último ano. Nesse regime, crescer **cria** valor."
            )
        else:
            st.warning(
                f"O retorno ficou {formatar(abs(spread), 'pct')} **abaixo** do custo de "
                "capital no último ano. Nesse regime, cada real reinvestido destrói "
                "valor — e crescer piora o resultado para o acionista."
            )
    elif not roic.empty:
        grafico(linhas_percentuais(analise.indicadores.loc[["ROIC"]], "ROIC"))

    st.divider()
    conceito("dupont", "Por que o retorno é o que é")

    st.markdown("#### Decomposição do ROE (DuPont)")
    st.caption("ROE = margem líquida × giro do ativo × alavancagem financeira")
    dupont = analise.decomposicao_dupont()
    formatos = {
        "Margem liquida": ".1%",
        "Giro do ativo": ",.2f",
        "Alavancagem financeira": ",.2f",
        "ROE": ".1%",
    }
    colunas = st.columns(4)
    for coluna, (nome, figura) in zip(colunas, pequenos_multiplos(dupont, formatos)):
        with coluna:
            st.plotly_chart(
                figura, width="stretch", config={"displayModeBar": False}
            )
    with st.expander("Ver os dados da decomposição"):
        st.dataframe(dupont.style.format("{:,.3f}", na_rep="—"), width="stretch")

    st.markdown("#### Decomposição do ROIC")
    st.caption("ROIC = margem NOPAT × giro do capital investido")
    roic_decomposto = analise.decomposicao_roic()
    grafico(
        linhas_percentuais(
            roic_decomposto.loc[
                ["Margem NOPAT", "ROIC", "Crescimento fundamentado (reinvest. x ROIC)"]
            ],
            "Margem, retorno e crescimento sustentável",
        ),
        roic_decomposto.style.format("{:,.3f}", na_rep="—"),
    )


def _reinvestimento(analise) -> None:
    conceito("reinvestimento", "Crescimento não é de graça")

    dados = analise.indicadores.loc[
        ["Capex / Receita", "Depreciacao / Receita", "Taxa de reinvestimento"]
    ]
    grafico(
        linhas_percentuais(dados, "Intensidade de capital"),
        dados.style.format("{:.1%}", na_rep="—"),
    )

    capex_dep = analise.linha("Capex / Depreciacao").dropna()
    if not capex_dep.empty:
        ultimo = float(capex_dep.iloc[-1])
        if ultimo < 0.9:
            st.warning(
                f"No último ano o capex foi {formatar(ultimo, 'multiplo')} a depreciação: "
                "a empresa investiu menos do que consumiu do próprio ativo. Sustentável "
                "por um ano, não por uma projeção inteira."
            )
        elif ultimo > 2.0:
            st.info(
                f"Capex de {formatar(ultimo, 'multiplo')} a depreciação indica ciclo de "
                "expansão. Confira se a receita projetada acompanha esse investimento."
            )

    crescimento_real = analise.linha("Crescimento da receita").dropna()
    crescimento_fundamentado = analise.linha(
        "Crescimento fundamentado (reinvest. x ROIC)"
    ).dropna()
    if not crescimento_real.empty and not crescimento_fundamentado.empty:
        st.markdown("#### Crescimento realizado x crescimento fundamentado")
        st.caption(
            "O fundamentado é reinvestimento × ROIC: o quanto a empresa poderia crescer "
            "com o que reinveste. Descolamento persistente entre os dois merece "
            "explicação — aquisições, alavancagem operacional ou ganho de participação."
        )
        comparacao = pd.DataFrame(
            {
                "Crescimento realizado": crescimento_real,
                "Crescimento fundamentado": crescimento_fundamentado,
            }
        ).T
        grafico(
            linhas_percentuais(comparacao, ""),
            comparacao.style.format("{:.1%}", na_rep="—"),
        )


def _capital_de_giro(analise) -> None:
    conceito("capital_giro", "O caixa preso no ciclo do negócio")

    ciclo = analise.ciclo_de_caixa()
    ultimo_ano = ciclo.columns[-1]
    valores = ciclo[ultimo_ano].dropna()
    if not valores.empty:
        grafico(
            barras_ciclo(valores, f"Ciclo de caixa em {ultimo_ano}"),
            ciclo.style.format("{:,.0f}", na_rep="—"),
        )

    giro = analise.indicadores.loc[["Capital de giro / Receita"]]
    grafico(
        linhas_percentuais(giro, "Capital de giro sobre receita"),
        giro.style.format("{:.1%}", na_rep="—"),
    )
    st.caption(
        "É este percentual que a projeção usa: quando a receita cresce, o capital de "
        "giro cresce junto e consome caixa."
    )

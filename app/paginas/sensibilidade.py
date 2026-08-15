"""Tela de sensibilidade, cenarios e Monte Carlo."""

from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st

from valuation import Distribuicao, cenarios, monte_carlo, tabela_sensibilidade

from .. import estado
from ..componentes import aviso_sem_modelo, conceito, etapa, formatar, grafico, metrica
from ..graficos import distribuicao_simulada, mapa_de_calor

EIXOS = {
    "WACC (taxa de desconto)": ("wacc", True),
    "Crescimento perpétuo": ("perpetuidade.crescimento_perpetuo", True),
    "Margem EBITDA": ("operacionais.margem_ebitda", True),
    "Crescimento da receita": ("operacionais.crescimento_receita", True),
    "Capex / receita": ("operacionais.capex_pct_receita", True),
    "ROIC de perpetuidade": ("perpetuidade.roic_perpetuidade", True),
}

METRICAS = {
    "Equity Value": "equity_value",
    "Enterprise Value": "enterprise_value",
    "Valor por ação": "valor_por_acao",
}


def render() -> None:
    etapa("Passo 6", "Sensibilidade", "O valuation não é um número, é uma faixa")

    resultado = estado.resultado()
    if resultado is None:
        aviso_sem_modelo(estado.erro_do_modelo())
        return

    abas = st.tabs(["Tabela de sensibilidade", "Cenários", "Monte Carlo"])
    with abas[0]:
        _sensibilidade(resultado)
    with abas[1]:
        _cenarios(resultado)
    with abas[2]:
        _monte_carlo(resultado)


def _valores_ao_redor(centro: float, passo: float, pontos: int = 5) -> list[float]:
    """Grade simetrica em torno do caso base."""
    metade = pontos // 2
    return [round(centro + (i - metade) * passo, 6) for i in range(pontos)]


def _sensibilidade(resultado) -> None:
    conceito("sensibilidade", "Por que uma tabela e não um número")

    empresa = estado.empresa()
    colunas = st.columns(4)

    nomes = list(EIXOS)
    eixo_linha = colunas[0].selectbox("Nas linhas", nomes, index=0)
    eixo_coluna = colunas[1].selectbox("Nas colunas", nomes, index=1)
    passo_linha = colunas[2].number_input(
        "Passo das linhas (p.p.)", value=0.5, step=0.25, min_value=0.05
    )
    passo_coluna = colunas[3].number_input(
        "Passo das colunas (p.p.)", value=0.5, step=0.25, min_value=0.05
    )

    metrica_nome = st.selectbox("Métrica", list(METRICAS), index=0)

    if eixo_linha == eixo_coluna:
        st.warning("Escolha duas premissas diferentes para os eixos.")
        return

    caminho_l, _ = EIXOS[eixo_linha]
    caminho_c, _ = EIXOS[eixo_coluna]
    centro_l = _centro(resultado, empresa, caminho_l)
    centro_c = _centro(resultado, empresa, caminho_c)

    if centro_l is None or centro_c is None:
        st.warning(
            "Uma das premissas escolhidas não está ativa no modelo atual "
            "(por exemplo, ROIC de perpetuidade com a normalização desligada)."
        )
        return

    valores_l = _valores_ao_redor(centro_l, passo_linha / 100)
    valores_c = _valores_ao_redor(centro_c, passo_coluna / 100)

    try:
        tabela = tabela_sensibilidade(
            empresa,
            (caminho_l, valores_l),
            (caminho_c, valores_c),
            metrica=METRICAS[metrica_nome],
            **estado.convencoes(),
        )
    except ValueError as erro:
        st.error(str(erro))
        return

    tabela.index.name = eixo_linha
    tabela.columns.name = eixo_coluna
    st.session_state["tabela_sensibilidade"] = tabela

    grafico(
        mapa_de_calor(tabela, f"{metrica_nome} — {eixo_linha} x {eixo_coluna}",
                      empresa.unidade),
        tabela.style.format("{:,.1f}", na_rep="—"),
    )

    valores = tabela.to_numpy(dtype=float)
    validos = valores[np.isfinite(valores)]
    if validos.size:
        minimo, maximo = float(validos.min()), float(validos.max())
        base = _extrair_metrica(resultado, METRICAS[metrica_nome])
        colunas = st.columns(3)
        with colunas[0]:
            metrica("Menor valor da tabela", minimo, "moeda", empresa.unidade)
        with colunas[1]:
            metrica("Caso base", base, "moeda", empresa.unidade)
        with colunas[2]:
            metrica("Maior valor da tabela", maximo, "moeda", empresa.unidade)

        if base and np.isfinite(base) and base != 0:
            amplitude = (maximo - minimo) / abs(base)
            if amplitude > 0.35:
                st.caption(
                    f"A faixa cobre {formatar(amplitude, 'pct')} do caso base — uma "
                    "amplitude dessas costuma significar que a resposta honesta ao "
                    "cliente é a faixa, e não o ponto médio dela."
                )
            else:
                st.caption(
                    f"A faixa cobre {formatar(amplitude, 'pct')} do caso base, o que é "
                    "contido para as variações testadas. Amplie os passos para ver "
                    "quanto o modelo aguenta antes de mudar de conclusão."
                )

    if np.isnan(valores).any():
        st.info(
            "Células vazias são combinações economicamente impossíveis — em geral "
            "crescimento perpétuo acima da taxa de desconto, que tornaria o valor "
            "terminal infinito."
        )


def _centro(resultado, empresa, caminho: str) -> float | None:
    """Valor atual da premissa que serve de centro da grade."""
    if caminho == "wacc":
        return resultado.dcf.taxa_desconto

    objeto = empresa
    for parte in caminho.split("."):
        objeto = getattr(objeto, parte, None)
        if objeto is None:
            return None
    if isinstance(objeto, list):
        return float(np.median(objeto))
    return float(objeto)


def _extrair_metrica(resultado, metrica_chave: str) -> float:
    valores = {
        "equity_value": resultado.equity_value,
        "enterprise_value": resultado.enterprise_value,
        "valor_por_acao": resultado.valor_por_acao,
    }
    valor = valores.get(metrica_chave)
    return float("nan") if valor is None else float(valor)


def _cenarios(resultado) -> None:
    st.markdown(
        "Cenários são conjuntos **coerentes** de premissas. Na prática elas não se "
        "movem isoladamente: se a demanda desaba, o crescimento cai *e* a margem "
        "cede *e* o capital de giro sobe. Uma tabela de sensibilidade não captura "
        "isso; um cenário sim."
    )

    empresa = estado.empresa()
    margem_base = float(np.median(empresa.operacionais.margem_ebitda))
    g_base = empresa.perpetuidade.crescimento_perpetuo

    colunas = st.columns(2)
    delta_margem = colunas[0].number_input(
        "Variação da margem no cenário extremo (p.p.)", value=3.0, step=0.5
    )
    delta_g = colunas[1].number_input(
        "Variação do crescimento perpétuo (p.p.)", value=1.0, step=0.25
    )

    definicoes = {
        "Pessimista": {
            "operacionais.margem_ebitda": margem_base - delta_margem / 100,
            "perpetuidade.crescimento_perpetuo": g_base - delta_g / 100,
        },
        "Base": {},
        "Otimista": {
            "operacionais.margem_ebitda": margem_base + delta_margem / 100,
            "perpetuidade.crescimento_perpetuo": g_base + delta_g / 100,
        },
    }

    tabela = cenarios(empresa, definicoes, **estado.convencoes())
    st.session_state["tabela_cenarios"] = tabela

    st.dataframe(tabela.style.format("{:,.1f}", na_rep="—"), width="stretch")

    if "equity_value" in tabela.index:
        colunas = st.columns(3)
        for coluna, nome in zip(colunas, tabela.columns):
            with coluna:
                metrica(nome, tabela.loc["equity_value", nome], "moeda", empresa.unidade)

    st.caption(
        "O cenário **Base** reproduz exatamente o número da tela de Valor — as três "
        "colunas rodam sob as mesmas convenções de desconto do caso principal."
    )


def _monte_carlo(resultado) -> None:
    conceito("monte_carlo", "Milhares de futuros de uma vez")

    empresa = estado.empresa()
    wacc_base = resultado.dcf.taxa_desconto
    g_base = empresa.perpetuidade.crescimento_perpetuo
    margem_base = float(np.median(empresa.operacionais.margem_ebitda))

    st.markdown("#### Distribuições das premissas")
    st.caption(
        "A distribuição triangular é a mais usada em valuation: é mais fácil opinar "
        "sobre piso, teto e caso mais provável do que sobre um desvio-padrão."
    )

    colunas = st.columns(3)
    with colunas[0]:
        st.markdown("**WACC**")
        wacc_min = st.number_input("Mínimo (%)", value=float((wacc_base - 0.015) * 100), step=0.25, key="wmin")
        wacc_moda = st.number_input("Mais provável (%)", value=float(wacc_base * 100), step=0.25, key="wmoda")
        wacc_max = st.number_input("Máximo (%)", value=float((wacc_base + 0.015) * 100), step=0.25, key="wmax")
    with colunas[1]:
        st.markdown("**Crescimento perpétuo**")
        g_min = st.number_input("Mínimo (%)", value=float((g_base - 0.01) * 100), step=0.25, key="gmin")
        g_moda = st.number_input("Mais provável (%)", value=float(g_base * 100), step=0.25, key="gmoda")
        g_max = st.number_input("Máximo (%)", value=float((g_base + 0.01) * 100), step=0.25, key="gmax")
    with colunas[2]:
        st.markdown("**Margem EBITDA**")
        m_media = st.number_input("Média (%)", value=float(margem_base * 100), step=0.5, key="mmed")
        m_desvio = st.number_input("Desvio-padrão (p.p.)", value=1.5, step=0.25, key="mdes")
        simulacoes = st.number_input(
            "Simulações", min_value=500, max_value=50_000, value=5_000, step=500
        )

    if not (wacc_min <= wacc_moda <= wacc_max) or not (g_min <= g_moda <= g_max):
        st.warning("Em cada distribuição triangular: mínimo ≤ mais provável ≤ máximo.")
        return

    if not st.button("Rodar simulação", type="primary"):
        st.info("Ajuste as distribuições e rode a simulação.")
        return

    distribuicoes = [
        Distribuicao(
            caminho="wacc",
            tipo="triangular",
            parametros={
                "minimo": wacc_min / 100,
                "moda": wacc_moda / 100,
                "maximo": wacc_max / 100,
            },
        ),
        Distribuicao(
            caminho="perpetuidade.crescimento_perpetuo",
            tipo="triangular",
            parametros={"minimo": g_min / 100, "moda": g_moda / 100, "maximo": g_max / 100},
        ),
        Distribuicao(
            caminho="operacionais.margem_ebitda",
            tipo="normal",
            parametros={"media": m_media / 100, "desvio": m_desvio / 100},
            limite_inferior=0.01,
        ),
    ]

    with st.spinner("Simulando..."):
        try:
            simulacao = monte_carlo(
                empresa,
                distribuicoes,
                simulacoes=int(simulacoes),
                metrica="equity_value",
                **estado.convencoes(),
            )
        except ValueError as erro:
            st.error(str(erro))
            return

    st.session_state["simulacao"] = simulacao

    percentis = simulacao.percentis().to_dict()
    grafico(
        distribuicao_simulada(
            simulacao.valores, percentis, resultado.equity_value, empresa.unidade
        ),
        simulacao.resumo().to_frame("Valor").style.format("{:,.1f}"),
    )

    colunas = st.columns(4)
    with colunas[0]:
        metrica("P5 (pessimista)", percentis["P5"], "moeda", empresa.unidade)
    with colunas[1]:
        metrica("Mediana", percentis["P50"], "moeda", empresa.unidade)
    with colunas[2]:
        metrica("P95 (otimista)", percentis["P95"], "moeda", empresa.unidade)
    with colunas[3]:
        metrica(
            "Chance de superar o caso base",
            simulacao.probabilidade_acima(resultado.equity_value),
            "pct",
        )

    if simulacao.descartadas:
        st.info(
            f"{simulacao.descartadas:,} de {simulacao.simulacoes:,} rodadas foram "
            "descartadas por sortearem crescimento perpétuo acima da taxa de desconto. "
            "Elas ficam de fora da distribuição em vez de distorcê-la."
            .replace(",", ".")
        )

    preco = st.number_input(
        "Comparar com um preço/valor pedido",
        value=float(resultado.equity_value),
        step=10.0,
        help="Responde: qual a chance de o valor justificar esse preço?",
    )
    st.metric(
        "Chance de o valor superar esse preço",
        formatar(simulacao.probabilidade_acima(preco), "pct"),
    )

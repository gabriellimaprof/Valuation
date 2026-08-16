"""Tela de valor: o resultado do DCF e a anatomia de como ele se forma."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from .. import estado
from ..componentes import (
    aviso_sem_modelo,
    conceito,
    etapa,
    formatar,
    grafico,
    metrica,
    tabela_formatada,
)
from ..graficos import cascata_ponte, composicao_do_valor, fluxos_projetados


def render() -> None:
    etapa("Passo 5", "Valor", "O resultado, e de onde cada parte dele vem")

    resultado = estado.resultado()
    if resultado is None:
        aviso_sem_modelo(estado.erro_do_modelo())
        return

    empresa = estado.empresa()
    unidade = empresa.unidade
    dcf = resultado.dcf

    _configuracao()
    _cartoes(resultado, unidade)

    st.divider()
    grafico(
        composicao_do_valor(
            dcf.valor_presente_explicito, dcf.valor_presente_terminal, unidade
        )
    )
    if dcf.peso_perpetuidade > 0.75:
        st.warning(
            f"**{formatar(dcf.peso_perpetuidade, 'pct')} do valor vem da perpetuidade.** "
            "Quase tudo depende de duas premissas — crescimento perpétuo e taxa de "
            "desconto — em vez da projeção que você construiu linha a linha. "
            "Considere alongar o horizonte em **Premissas**."
        )
    else:
        st.caption(
            f"{formatar(1 - dcf.peso_perpetuidade, 'pct')} do valor está dentro do "
            "horizonte projetado. Quanto maior essa fatia, mais o valuation se apoia "
            "no que você modelou explicitamente."
        )

    st.divider()
    abas = st.tabs(["Fluxos descontados", "Ponte até o acionista", "Resumo do modelo"])

    with abas[0]:
        _fluxos(resultado, unidade)
    with abas[1]:
        _ponte(resultado, unidade)
    with abas[2]:
        _resumo(resultado, unidade)


def _configuracao() -> None:
    config = estado.config()
    colunas = st.columns([2, 2, 4])

    tipo = colunas[0].radio(
        "Tipo de fluxo",
        ["FCFF (para a firma)", "FCFE (para o acionista)"],
        index=0 if config["tipo_fluxo"] == "fcff" else 1,
        horizontal=True,
    )
    meio = colunas[1].checkbox(
        "Convenção de meio de ano",
        value=config["meio_de_ano"],
        help=(
            "Assume caixa gerado ao longo do ano, descontando em t − 0,5. Eleva o "
            "valor em relação à convenção de fim de ano."
        ),
    )

    novo_tipo = "fcff" if tipo.startswith("FCFF") else "fcfe"
    if novo_tipo != config["tipo_fluxo"] or meio != config["meio_de_ano"]:
        config["tipo_fluxo"] = novo_tipo
        config["meio_de_ano"] = meio
        st.rerun()

    with colunas[2]:
        conceito("fcff" if config["tipo_fluxo"] == "fcff" else "fcfe")


def _cartoes(resultado, unidade: str) -> None:
    dcf = resultado.dcf
    colunas = st.columns(4)
    with colunas[0]:
        metrica("Enterprise Value", resultado.enterprise_value, "moeda", unidade)
    with colunas[1]:
        metrica("Equity Value", resultado.equity_value, "moeda", unidade)
    with colunas[2]:
        metrica(
            "Valor por ação",
            resultado.valor_por_acao,
            "numero",
            ajuda="Informe as ações em circulação na tela de Dados para ver este número.",
        )
    with colunas[3]:
        metrica("Taxa de desconto", dcf.taxa_desconto, "pct2")


def _fluxos(resultado, unidade: str) -> None:
    dcf = resultado.dcf
    grafico(
        fluxos_projetados(dcf.anos, dcf.fluxos, dcf.fluxos_descontados, unidade),
        tabela_formatada(dcf.tabela_fluxos(), "numero"),
    )
    st.caption(
        "A diferença entre as duas barras de cada ano é o custo do tempo: quanto o "
        "dinheiro daquele ano encolhe ao ser trazido para hoje."
    )

    colunas = st.columns(3)
    with colunas[0]:
        metrica(
            "VP dos fluxos projetados", dcf.valor_presente_explicito, "moeda", unidade
        )
    with colunas[1]:
        metrica(
            "Valor terminal (no ano final)", dcf.valor_terminal, "moeda", unidade,
            ajuda="Valor de tudo que vem depois do horizonte, medido no último ano projetado.",
        )
    with colunas[2]:
        metrica("VP do valor terminal", dcf.valor_presente_terminal, "moeda", unidade)


def _ponte(resultado, unidade: str) -> None:
    conceito("ponte", "Da empresa inteira para a fatia do acionista")

    ponte = resultado.empresa.ponte
    itens = [
        ("Enterprise Value", resultado.enterprise_value),
        ("(−) Dívida bruta", -ponte.divida_bruta),
        ("(+) Caixa", ponte.caixa),
        ("(+) Aplicações", ponte.aplicacoes_financeiras),
        ("(−) Minoritários", -ponte.minoritarios),
        ("(−) Contingências", -ponte.contingencias),
        ("(−) Déficit atuarial", -ponte.deficit_atuarial),
        ("(+) Ativos não operacionais", ponte.ativos_nao_operacionais),
        ("Equity Value", resultado.equity_value),
    ]
    relevantes = [
        (nome, valor)
        for nome, valor in itens
        if valor != 0 or nome in ("Enterprise Value", "Equity Value")
    ]

    grafico(
        cascata_ponte(relevantes, unidade),
        tabela_formatada(resultado.tabela_ponte(), "moeda", unidade),
    )

    _arrendamento(ponte, unidade)

    with st.expander("Editar os itens da ponte"):
        _editar_ponte(ponte)


def _arrendamento(ponte, unidade: str) -> None:
    """De que a dívida bruta é feita, e o que a projeção não faz com ela.

    A ponte subtrai um total. Para uma empresa de varejo ou de logística, boa
    parte desse total é arrendamento — e arrendamento tem uma propriedade que
    empréstimo não tem: ele **cresce sozinho** quando a empresa cresce, sem
    passar pelo capex. Quem lê só o total não vê isso chegando.
    """
    from valuation.casos_especiais import ler_leasing

    analise = estado.analise()
    if analise is None:
        return

    leasing = ler_leasing(analise)
    if not (leasing.peso == leasing.peso) or leasing.peso <= 0:  # NaN ou zero
        return

    st.markdown("**De que a dívida bruta é feita**")
    colunas = st.columns(3)
    with colunas[0]:
        metrica("Arrendamento (IFRS 16)", leasing.saldo, "moeda", unidade)
    with colunas[1]:
        metrica("Peso na dívida bruta", leasing.peso, "pct")
    with colunas[2]:
        metrica("Cresceu ao ano", leasing.crescimento_anual, "pct")

    st.caption(leasing.explicacao)

    if not leasing.relevante:
        return

    empresa = estado.empresa()
    crescimento = (
        float(empresa.operacionais.crescimento_receita[0])
        if empresa.operacionais
        else float("nan")
    )
    adicao = leasing.adicao_anual_implicita(crescimento)

    aviso = (
        f"Com {formatar(leasing.peso, 'pct')} da dívida em arrendamento, vale saber o "
        "que a projeção **não** faz: contrato novo de aluguel cria passivo sem passar "
        "pelo capex. O EBITDA sobe, o capex não acompanha, o FCFF sai generoso — e a "
        "ponte fica congelada na data-base."
    )
    if adicao == adicao:
        aviso += (
            f" Crescendo {formatar(crescimento, 'pct')} no ano 1, o passivo de "
            f"arrendamento aumentaria cerca de {formatar(adicao, 'moeda', unidade)}, "
            "que o modelo não desconta de ninguém."
        )
    st.warning(aviso)


def _editar_ponte(ponte) -> None:
    from dataclasses import replace

    colunas = st.columns(4)
    divida = colunas[0].number_input("Dívida bruta", value=float(ponte.divida_bruta), step=10.0)
    caixa = colunas[1].number_input("Caixa", value=float(ponte.caixa), step=10.0)
    aplicacoes = colunas[2].number_input(
        "Aplicações financeiras", value=float(ponte.aplicacoes_financeiras), step=10.0
    )
    minoritarios = colunas[3].number_input(
        "Minoritários", value=float(ponte.minoritarios), step=5.0
    )

    colunas = st.columns(4)
    contingencias = colunas[0].number_input(
        "Contingências", value=float(ponte.contingencias), step=5.0
    )
    atuarial = colunas[1].number_input(
        "Déficit atuarial", value=float(ponte.deficit_atuarial), step=5.0
    )
    nao_operacionais = colunas[2].number_input(
        "Ativos não operacionais", value=float(ponte.ativos_nao_operacionais), step=5.0
    )
    acoes = colunas[3].number_input(
        "Ações em circulação", value=float(ponte.acoes_em_circulacao or 0.0), step=1.0
    )

    if st.button("Aplicar ponte"):
        estado.substituir_bloco(
            "ponte",
            replace(
                ponte,
                divida_bruta=divida,
                caixa=caixa,
                aplicacoes_financeiras=aplicacoes,
                minoritarios=minoritarios,
                contingencias=contingencias,
                deficit_atuarial=atuarial,
                ativos_nao_operacionais=nao_operacionais,
                acoes_em_circulacao=acoes or None,
            ),
        )
        st.rerun()


def _resumo(resultado, unidade: str) -> None:
    st.dataframe(
        resultado.resumo().style.format("{:,.4f}"), width="stretch"
    )
    with st.expander("Projeção completa"):
        st.dataframe(
            tabela_formatada(resultado.projecao.tabela(), "moeda", unidade),
            width="stretch",
        )

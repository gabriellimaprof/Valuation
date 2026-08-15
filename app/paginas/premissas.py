"""Tela de premissas operacionais: a projecao ano a ano."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd
import streamlit as st

from valuation.casos_especiais import normalizar_margem_ciclica
from valuation.historico import sugerir_premissas

from .. import estado
from ..componentes import conceito, etapa, formatar, grafico, tabela_formatada
from ..graficos import barras_temporais, linhas_percentuais


def render() -> None:
    etapa("Passo 3", "Premissas da projeção", "O futuro, ancorado no que já aconteceu")

    empresa = estado.empresa()
    operacionais = empresa.operacionais
    analise = estado.analise()

    _barra_de_acoes(analise)

    horizonte = st.slider(
        "Anos de projeção explícita",
        min_value=3,
        max_value=10,
        value=operacionais.horizonte,
        help=(
            "Projete até a empresa atingir maturidade. Horizonte curto joga o valor "
            "todo para a perpetuidade, que depende de duas premissas em vez das suas."
        ),
    )
    if horizonte != operacionais.horizonte:
        operacionais = _ajustar_horizonte(operacionais, horizonte)
        estado.substituir_bloco("operacionais", operacionais)
        st.rerun()

    anos = [operacionais.ano_base + i + 1 for i in range(operacionais.horizonte)]

    st.divider()
    _editor(operacionais, anos, analise)

    st.divider()
    _perpetuidade(empresa)

    st.divider()
    _visualizar()


def _barra_de_acoes(analise) -> None:
    if analise is None:
        st.info(
            "Sem histórico importado, estas premissas são apenas um ponto de partida. "
            "Importe as demonstrações em **Dados** para ancorá-las no que a empresa "
            "de fato entregou."
        )
        return

    colunas = st.columns([2, 2, 3])
    if colunas[0].button("Sugerir a partir do histórico"):
        try:
            sugestao = sugerir_premissas(analise, horizonte=estado.empresa().operacionais.horizonte)
        except ValueError as erro:
            st.error(str(erro))
        else:
            estado.substituir_bloco("operacionais", sugestao.operacionais)
            st.success("Premissas recalculadas a partir do histórico.")
            with st.expander("De onde veio cada uma", expanded=True):
                for chave, texto in sugestao.justificativas.items():
                    st.markdown(f"- **{chave}**: {texto}")
            st.rerun()

    if colunas[1].button("Normalizar margem (setor cíclico)"):
        try:
            normalizada = normalizar_margem_ciclica(analise)
        except ValueError as erro:
            st.warning(str(erro))
        else:
            estado.atualizar(
                {"operacionais.margem_ebitda": normalizada.margem_normalizada}
            )
            st.success(normalizada.explicacao)
            st.rerun()

    colunas[2].caption(
        "A normalização troca a margem do último ano pela mediana do ciclo observado."
    )


def _ajustar_horizonte(operacionais, horizonte: int):
    """Estende repetindo o ultimo ano, encurta cortando o fim.

    Repetir o ultimo valor e mais seguro do que extrapolar: o app nao deve
    inventar uma trajetoria que o usuario nao pediu.
    """
    def redimensionar(valores: list[float]) -> list[float]:
        if horizonte <= len(valores):
            return list(valores[:horizonte])
        return list(valores) + [valores[-1]] * (horizonte - len(valores))

    return replace(
        operacionais,
        crescimento_receita=redimensionar(operacionais.crescimento_receita),
        margem_ebitda=redimensionar(operacionais.margem_ebitda),
        depreciacao_pct_receita=redimensionar(operacionais.depreciacao_pct_receita),
        capex_pct_receita=redimensionar(operacionais.capex_pct_receita),
        capital_giro_pct_receita=redimensionar(operacionais.capital_giro_pct_receita),
    )


def _referencia(analise, indicador: str) -> str:
    if analise is None:
        return ""
    valor = analise.mediana(indicador)
    if not np.isfinite(valor):
        return ""
    return f"mediana histórica: {formatar(valor, 'pct')}"


def _editor(operacionais, anos: list[int], analise) -> None:
    st.subheader("Direcionadores, ano a ano")
    st.caption("Percentuais em pontos percentuais: digite 12,5 para 12,5%.")

    tabela = pd.DataFrame(
        {
            "Crescimento da receita (%)": [v * 100 for v in operacionais.crescimento_receita],
            "Margem EBITDA (%)": [v * 100 for v in operacionais.margem_ebitda],
            "Depreciação / receita (%)": [v * 100 for v in operacionais.depreciacao_pct_receita],
            "Capex / receita (%)": [v * 100 for v in operacionais.capex_pct_receita],
            "Capital de giro / receita (%)": [
                v * 100 for v in operacionais.capital_giro_pct_receita
            ],
        },
        index=[str(a) for a in anos],
    )

    editada = st.data_editor(
        tabela,
        width="stretch",
        column_config={
            coluna: st.column_config.NumberColumn(coluna, format="%.2f", step=0.25)
            for coluna in tabela.columns
        },
        key="editor_premissas",
    )

    referencias = [
        _referencia(analise, "Crescimento da receita"),
        _referencia(analise, "Margem EBITDA"),
        _referencia(analise, "Depreciacao / Receita"),
        _referencia(analise, "Capex / Receita"),
        _referencia(analise, "Capital de giro / Receita"),
    ]
    visiveis = [f"**{c}** — {r}" for c, r in zip(tabela.columns, referencias) if r]
    if visiveis:
        st.caption("Referências do histórico: " + " · ".join(visiveis))

    colunas = st.columns([1, 3])
    if colunas[0].button("Aplicar", type="primary"):
        estado.substituir_bloco(
            "operacionais",
            replace(
                operacionais,
                crescimento_receita=[v / 100 for v in editada.iloc[:, 0]],
                margem_ebitda=[v / 100 for v in editada.iloc[:, 1]],
                depreciacao_pct_receita=[v / 100 for v in editada.iloc[:, 2]],
                capex_pct_receita=[v / 100 for v in editada.iloc[:, 3]],
                capital_giro_pct_receita=[v / 100 for v in editada.iloc[:, 4]],
            ),
        )
        st.rerun()

    with colunas[1]:
        conceito("capital_giro")

    with st.expander("Receita do ano base e prejuízo fiscal"):
        colunas = st.columns(3)
        receita = colunas[0].number_input(
            "Receita líquida do ano base",
            value=float(operacionais.receita_base),
            step=10.0,
        )
        ano_base = colunas[1].number_input(
            "Ano base", min_value=2000, max_value=2100,
            value=int(operacionais.ano_base) or 2025,
        )
        prejuizo = colunas[2].number_input(
            "Prejuízo fiscal acumulado",
            value=float(estado.empresa().prejuizo_fiscal_acumulado),
            step=10.0,
        )
        conceito("prejuizo_fiscal")
        if st.button("Salvar ano base"):
            estado.substituir_bloco(
                "operacionais",
                replace(operacionais, receita_base=receita, ano_base=int(ano_base)),
            )
            estado.atualizar({"prejuizo_fiscal_acumulado": prejuizo})
            st.rerun()


def _perpetuidade(empresa) -> None:
    st.subheader("Perpetuidade")
    conceito("perpetuidade", "A parte do modelo que mais pesa no valor")

    perpetuidade = empresa.perpetuidade
    colunas = st.columns(4)

    metodo = colunas[0].selectbox(
        "Método",
        ["Crescimento perpétuo (Gordon)", "Múltiplo de saída"],
        index=0 if perpetuidade.metodo == "gordon" else 1,
    )
    usar_gordon = metodo.startswith("Crescimento")

    crescimento = colunas[1].number_input(
        "Crescimento perpétuo (%)",
        value=float(perpetuidade.crescimento_perpetuo * 100),
        step=0.25,
        format="%.2f",
        disabled=not usar_gordon,
        help=(
            "Teto natural: crescimento nominal da economia (inflação + PIB real). "
            "Acima disso, a empresa acabaria maior que o país."
        ),
    )

    normalizar = colunas[2].checkbox(
        "Normalizar reinvestimento",
        value=perpetuidade.roic_perpetuidade is not None,
        disabled=not usar_gordon,
        help="Desconta do fluxo perpétuo a taxa de reinvestimento g/ROIC.",
    )
    roic = colunas[2].number_input(
        "ROIC perpétuo (%)",
        value=float((perpetuidade.roic_perpetuidade or 0.15) * 100),
        step=0.5,
        format="%.2f",
        disabled=not (usar_gordon and normalizar),
    )

    multiplo = colunas[3].number_input(
        "Múltiplo de saída (EV/EBITDA)",
        value=float(perpetuidade.multiplo_saida or 7.0),
        step=0.5,
        disabled=usar_gordon,
    )

    if st.button("Aplicar perpetuidade"):
        if usar_gordon:
            alteracoes = {
                "perpetuidade.metodo": "gordon",
                "perpetuidade.crescimento_perpetuo": crescimento / 100,
                "perpetuidade.roic_perpetuidade": (roic / 100) if normalizar else None,
            }
        else:
            alteracoes = {
                "perpetuidade.metodo": "multiplo",
                "perpetuidade.multiplo_saida": multiplo,
            }
        try:
            estado.atualizar(alteracoes)
        except ValueError as erro:
            st.error(str(erro))
        else:
            st.rerun()

    inflacao = empresa.macro.inflacao_brl
    if usar_gordon and crescimento / 100 > inflacao + 0.02:
        st.warning(
            f"Crescimento de {formatar(crescimento / 100, 'pct')} supera o crescimento "
            f"nominal estimado da economia ({formatar(inflacao + 0.02, 'pct')} = "
            "inflação + 2% de PIB real)."
        )


def _visualizar() -> None:
    st.subheader("Como fica a projeção")
    resultado = estado.resultado()
    if resultado is None:
        st.error(estado.erro_do_modelo() or "As premissas atuais não fecham.")
        return

    projecao = resultado.projecao
    unidade = estado.empresa().unidade
    anos = [str(a) for a in projecao.anos]

    fluxos = pd.DataFrame(
        {
            "Receita líquida": projecao.receita,
            "EBITDA": projecao.ebitda,
            "FCFF": projecao.fcff,
        },
        index=anos,
    ).T
    grafico(
        barras_temporais(fluxos, "Projeção", unidade),
        tabela_formatada(fluxos, "moeda", unidade),
    )

    indicadores = projecao.indicadores()
    indicadores.columns = anos
    grafico(
        linhas_percentuais(
            indicadores.loc[["Crescimento da receita", "Margem EBITDA", "Capex / Receita"]],
            "Consistência da projeção",
        ),
        indicadores.style.format("{:,.3f}", na_rep="—"),
    )

    with st.expander("Ver a projeção completa, linha a linha"):
        st.dataframe(
            tabela_formatada(projecao.tabela(), "moeda", unidade),
            width="stretch",
        )

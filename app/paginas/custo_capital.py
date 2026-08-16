"""Tela de custo de capital: montagem do Ke pelo CAPM e do WACC."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from valuation.dados_setoriais import (
    AVISO_REFERENCIA,
    PAISES_POR_NOME,
    SETORES,
    buscar_setor,
    listar_setores,
)

from .. import estado
from ..componentes import conceito, etapa, formatar, metrica


def render() -> None:
    etapa("Passo 4", "Custo de capital", "A taxa que traz o futuro para hoje")

    conceito("wacc", "O que estamos montando")

    empresa = estado.empresa()
    premissas = empresa.custo_capital

    abas = st.tabs(["Montagem", "Como o número se forma", "Referências por setor"])

    with abas[0]:
        _montagem(empresa, premissas)
    with abas[1]:
        _decomposicao()
    with abas[2]:
        _referencias()


def _montagem(empresa, premissas) -> None:
    st.subheader("Risco do negócio")
    conceito("beta", "Beta: risco do setor, alavancagem da empresa")

    colunas = st.columns([2, 1, 1])
    nomes = ["(informar beta manualmente)"] + [s.nome for s in SETORES]
    escolha = colunas[0].selectbox(
        "Setor",
        nomes,
        index=nomes.index(estado.config().get("setor"))
        if estado.config().get("setor") in nomes
        else 0,
        help="Traz o beta desalavancado típico do setor.",
    )

    if escolha != "(informar beta manualmente)":
        setor = buscar_setor(escolha)
        beta_desalavancado = colunas[1].number_input(
            "Beta desalavancado", value=float(setor.beta_desalavancado), step=0.05
        )
        colunas[2].caption(setor.observacao or "—")
    else:
        beta_desalavancado = colunas[1].number_input(
            "Beta desalavancado",
            value=float(
                premissas.beta_desalavancado
                if premissas.beta_desalavancado is not None
                else 1.0
            ),
            step=0.05,
        )

    st.subheader("Mercado e país")
    colunas = st.columns(4)
    paises = list(PAISES_POR_NOME)
    pais = colunas[0].selectbox(
        "País", paises, index=paises.index(estado.config().get("pais", "Brasil"))
    )
    dados_pais = PAISES_POR_NOME[pais]

    rf = colunas[1].number_input(
        "Taxa livre de risco em USD (%)",
        value=float(premissas.rf_usd * 100),
        step=0.1,
        format="%.2f",
        help="T-Bond de 10 anos. O modelo monta o Ke em USD e converte para a moeda local.",
    )
    erp = colunas[2].number_input(
        "Prêmio de risco de mercado maduro (%)",
        value=float(premissas.erp_maduro * 100),
        step=0.1,
        format="%.2f",
    )
    risco_pais = colunas[3].number_input(
        "Prêmio de risco-país (%)",
        value=float(dados_pais.risco_pais * 100),
        step=0.1,
        format="%.2f",
    )

    colunas = st.columns(4)
    lambda_pais = colunas[0].number_input(
        "Lambda (exposição ao risco-país)",
        value=float(premissas.lambda_pais),
        step=0.1,
        help=(
            "1,0 para empresa 100% exposta ao país. Exportadoras com receita em "
            "moeda forte usam valores menores."
        ),
    )
    premio_tamanho = colunas[1].number_input(
        "Prêmio de tamanho (%)",
        value=float(premissas.premio_tamanho * 100),
        step=0.1,
        format="%.2f",
    )
    inflacao_brl = colunas[2].number_input(
        "Inflação local de longo prazo (%)",
        value=float(empresa.macro.inflacao_brl * 100),
        step=0.1,
        format="%.2f",
    )
    inflacao_usd = colunas[3].number_input(
        "Inflação em USD de longo prazo (%)",
        value=float(empresa.macro.inflacao_usd * 100),
        step=0.1,
        format="%.2f",
    )

    if empresa.perpetuidade.ancora != "livre":
        rotulo = "IPCA" if empresa.perpetuidade.ancora == "ipca" else "PIB nominal"
        st.caption(
            f"O crescimento perpétuo está ancorado em **{rotulo}** — a inflação local "
            "daqui move o **g** junto com o WACC. É a mesma premissa entrando dos dois "
            "lados do desconto."
        )

    st.subheader("Estrutura de capital e dívida")
    colunas = st.columns(4)
    divida_pl = colunas[0].number_input(
        "Dívida / Patrimônio alvo",
        value=float(premissas.divida_pl_alvo),
        step=0.05,
        min_value=0.0,
        help=(
            "Estrutura-alvo, não a de hoje: o WACC deve refletir como a empresa vai "
            "se financiar ao longo da projeção."
        ),
    )
    informar_kd = colunas[1].checkbox(
        "Informar Kd diretamente", value=premissas.custo_divida_brl is not None
    )
    kd = colunas[2].number_input(
        "Custo da dívida bruto (%)",
        value=float((premissas.custo_divida_brl or 0.13) * 100),
        step=0.25,
        format="%.2f",
        disabled=not informar_kd,
    )
    spread = colunas[3].number_input(
        "Spread de crédito (%)",
        value=float(premissas.spread_credito * 100),
        step=0.25,
        format="%.2f",
        disabled=informar_kd,
        help="Usado para montar o Kd sinteticamente quando ele não é informado.",
    )
    aliquota = st.number_input(
        "Alíquota de IR/CSLL (%)",
        value=float(empresa.macro.aliquota_ir * 100),
        step=1.0,
        format="%.2f",
    )

    if st.button("Aplicar custo de capital", type="primary"):
        estado.config()["setor"] = escolha
        estado.config()["pais"] = pais
        try:
            estado.atualizar(
                {
                    "custo_capital.beta_desalavancado": beta_desalavancado,
                    "custo_capital.beta_alavancado_setor": None,
                    "custo_capital.divida_pl_alvo": divida_pl,
                    "custo_capital.rf_usd": rf / 100,
                    "custo_capital.erp_maduro": erp / 100,
                    "custo_capital.risco_pais": risco_pais / 100,
                    "custo_capital.lambda_pais": lambda_pais,
                    "custo_capital.premio_tamanho": premio_tamanho / 100,
                    "custo_capital.custo_divida_brl": (kd / 100) if informar_kd else None,
                    "custo_capital.spread_credito": spread / 100,
                    "macro.inflacao_brl": inflacao_brl / 100,
                    "macro.inflacao_usd": inflacao_usd / 100,
                    "macro.aliquota_ir": aliquota / 100,
                }
            )
        except ValueError as erro:
            st.error(str(erro))
        else:
            st.rerun()

    st.divider()
    resultado = estado.resultado()
    if resultado is None:
        st.error(estado.erro_do_modelo() or "As premissas atuais não fecham.")
        return

    cc = resultado.custo_capital
    colunas = st.columns(4)
    with colunas[0]:
        metrica("WACC (moeda local)", cc.wacc_brl, "pct2")
    with colunas[1]:
        metrica("Ke — capital próprio", cc.ke_brl, "pct2")
    with colunas[2]:
        metrica("Kd após IR", cc.kd_liquido_brl, "pct2")
    with colunas[3]:
        metrica("Beta realavancado", cc.beta_realavancado, "numero")


def _decomposicao() -> None:
    conceito("capm", "Por que montamos em dólar e convertemos depois")

    resultado = estado.resultado()
    if resultado is None:
        st.info("Ajuste as premissas na aba de montagem primeiro.")
        return

    cc = resultado.custo_capital
    premissas = estado.empresa().custo_capital
    macro = estado.empresa().macro

    st.markdown("#### Do risco do setor até a taxa de desconto")
    passos = [
        (
            "1. Beta desalavancado do setor",
            formatar(cc.beta_desalavancado, "numero"),
            "Mede o risco do negócio, sem o efeito de dívida.",
        ),
        (
            "2. Beta realavancado",
            formatar(cc.beta_realavancado, "numero"),
            f"βu × (1 + (1 − IR) × D/E), com D/E alvo de "
            f"{formatar(premissas.divida_pl_alvo, 'numero')}.",
        ),
        (
            "3. Ke em USD nominal",
            formatar(cc.ke_usd, "pct2"),
            f"{formatar(premissas.rf_usd, 'pct2')} (livre de risco) + β × "
            f"{formatar(premissas.erp_maduro, 'pct2')} (prêmio de mercado) + "
            f"{formatar(premissas.lambda_pais * premissas.risco_pais, 'pct2')} (risco-país).",
        ),
        (
            "4. Ke em moeda local",
            formatar(cc.ke_brl, "pct2"),
            f"Convertido pelo diferencial de inflação "
            f"({formatar(macro.inflacao_brl, 'pct')} local x "
            f"{formatar(macro.inflacao_usd, 'pct')} em USD).",
        ),
        (
            "5. Kd após imposto",
            formatar(cc.kd_liquido_brl, "pct2"),
            f"{formatar(cc.kd_bruto_brl, 'pct2')} × (1 − "
            f"{formatar(macro.aliquota_ir, 'pct')}). Juros são dedutíveis, então o "
            "governo banca parte do custo da dívida.",
        ),
        (
            "6. WACC",
            formatar(cc.wacc_brl, "pct2"),
            f"{formatar(cc.peso_equity, 'pct')} × Ke + "
            f"{formatar(cc.peso_divida, 'pct')} × Kd após IR.",
        ),
    ]

    for titulo, valor, explicacao in passos:
        with st.container(border=True):
            colunas = st.columns([3, 1, 6])
            colunas[0].markdown(f"**{titulo}**")
            colunas[1].markdown(f"**{valor}**")
            colunas[2].caption(explicacao)


def _referencias() -> None:
    st.warning(AVISO_REFERENCIA)
    st.markdown(
        "Para trabalho que vai para cliente ou comitê, baixe as planilhas oficiais em "
        "`pages.stern.nyu.edu/~adamodar/New_Home_Page/data.html` — os valores abaixo "
        "servem para orientar a ordem de grandeza, não para citar como fonte."
    )
    st.dataframe(
        listar_setores().style.format(
            {
                "Beta desalavancado": "{:.2f}",
                "D/E tipico": "{:.2f}",
                "Margem EBITDA tipica": "{:.1%}",
            },
            na_rep="—",
        ),
        width="stretch",
    )

    st.markdown("#### Parâmetros por país")
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "País": p.nome,
                    "Risco-país": p.risco_pais,
                    "Inflação de longo prazo": p.inflacao_longo_prazo,
                    "Alíquota de IR": p.aliquota_ir,
                }
                for p in PAISES_POR_NOME.values()
            ]
        )
        .set_index("País")
        .style.format("{:.1%}"),
        width="stretch",
    )

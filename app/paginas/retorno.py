"""Tela de retorno: TSR esperado e de onde ele vem."""

from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st

from valuation.erros import CombinacaoInviavel
from valuation.retorno import (
    decompor_ponte_ev,
    decompor_tsr,
    multiplo_de_saida_do_dcf,
    preco_para_tsr,
    projetar_acionista,
)

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
from ..graficos import cascata_ponte, cascata_tsr, tsr_por_preco

SAIDAS = {
    "O múltiplo que o próprio DCF implica": "dcf",
    "O mesmo múltiplo da entrada (sem re-rating)": "entrada",
    "Um múltiplo que eu escolho": "manual",
}


def render() -> None:
    etapa(
        "Passo 6",
        "Retorno esperado",
        "Comprando a este preço, quanto eu ganho por ano — e de onde vem",
    )

    resultado = estado.resultado()
    if resultado is None:
        aviso_sem_modelo(estado.erro_do_modelo())
        return

    conceito("tsr", "O que estamos calculando")

    acionista = _fluxos_do_acionista(resultado)
    if acionista is None:
        return

    decomposicao = _decompor(resultado, acionista)
    if decomposicao is None:
        return

    # Guardar deixa o diagnostico avaliar a tese de retorno e a exportacao levar
    # a decomposicao para a planilha -- sem isso, o TSR morre nesta tela.
    estado.definir_decomposicao_tsr(decomposicao)
    st.session_state["projecao_acionista"] = acionista

    st.divider()
    _cartoes(decomposicao, resultado)

    st.divider()
    abas = st.tabs(
        [
            "De onde vem o retorno",
            "A que preço vale a pena",
            "Ponte de valor (com dívida)",
            "Fluxos do acionista",
        ]
    )
    with abas[0]:
        _decomposicao(decomposicao)
    with abas[1]:
        _preco(decomposicao, resultado, acionista)
    with abas[2]:
        _ponte_ev(resultado, acionista, decomposicao)
    with abas[3]:
        _fluxos(acionista, decomposicao)


# ---------------------------------------------------------------------------
# Entradas
# ---------------------------------------------------------------------------


def _fluxos_do_acionista(resultado):
    st.subheader("Política de caixa")
    st.caption(
        "O retorno do acionista depende do que a empresa faz com o caixa que gera: "
        "distribui, ou usa para reduzir dívida. As duas coisas valem dinheiro, e por "
        "caminhos diferentes."
    )

    colunas = st.columns(4)
    politica_nome = colunas[0].selectbox(
        "Destino do caixa",
        ["Payout sobre o lucro", "Distribuir todo o caixa livre"],
        help="O payout é limitado pelo caixa que de fato sobra no ano.",
    )
    payout = colunas[1].slider(
        "Payout (%)",
        min_value=0,
        max_value=100,
        value=40,
        step=5,
        disabled=politica_nome != "Payout sobre o lucro",
    )
    amortizar = colunas[2].checkbox(
        "Sobra amortiza dívida",
        value=True,
        help=(
            "A dívida encolhendo transfere valor do credor para o acionista. "
            "Ignorar isso subestima o retorno de empresas endividadas."
        ),
    )
    colunas[3].metric(
        "Horizonte", f"{resultado.projecao.horizonte} anos",
        help="Igual ao horizonte da projeção, definido na tela de Premissas.",
    )

    empresa = estado.empresa()
    try:
        return projetar_acionista(
            resultado.projecao,
            divida_inicial=empresa.ponte.divida_bruta,
            custo_divida=resultado.custo_capital.kd_bruto_brl,
            aliquota_ir=empresa.macro.aliquota_ir,
            payout=payout / 100,
            politica="payout" if politica_nome.startswith("Payout") else "fcfe",
            amortizar_divida=amortizar,
            prejuizo_fiscal_acumulado=empresa.prejuizo_fiscal_acumulado,
        )
    except ValueError as erro:
        st.error(str(erro))
        return None


def _decompor(resultado, acionista):
    st.subheader("Entrada e saída")
    empresa = estado.empresa()
    unidade = empresa.unidade

    lucro_entrada = float(acionista.lucro_liquido[0])
    lucro_saida = float(acionista.lucro_liquido[-1])
    divida_saida = float(acionista.divida_fechamento[-1])

    colunas = st.columns(3)
    preco = colunas[0].number_input(
        f"Preço de entrada ({unidade})",
        value=float(resultado.equity_value),
        step=10.0,
        help=(
            "Por padrão, o valor que o próprio DCF calculou. Troque pelo valor de "
            "mercado para saber o retorno de comprar ao preço de tela."
        ),
    )
    escolha_saida = colunas[1].selectbox("Múltiplo de saída", list(SAIDAS))
    modo = SAIDAS[escolha_saida]

    if lucro_entrada <= 0:
        st.error(
            f"O lucro líquido do primeiro ano projetado é {formatar(lucro_entrada, 'moeda', unidade)}. "
            "Sem lucro positivo não existe P/L de entrada — use a aba **Ponte de valor**, "
            "que trabalha com EBITDA e funciona mesmo com prejuízo."
        )
        return None

    multiplo_entrada = preco / lucro_entrada
    multiplo_saida = None

    if modo == "dcf":
        try:
            multiplo_saida = multiplo_de_saida_do_dcf(resultado, lucro_saida, divida_saida)
        except CombinacaoInviavel as erro:
            st.warning(f"{erro} Usando o múltiplo de entrada como saída.")
            multiplo_saida = None
    elif modo == "manual":
        multiplo_saida = colunas[2].number_input(
            "P/L de saída",
            value=float(round(multiplo_entrada, 1)),
            step=0.5,
            min_value=0.1,
        )

    if modo == "dcf" and multiplo_saida is not None:
        colunas[2].metric("P/L de saída implícito", formatar(multiplo_saida, "multiplo"))
        st.caption(
            "O valor terminal do DCF **é** o valor da empresa no fim do horizonte. "
            "Sair por esse múltiplo mantém o DCF e o TSR contando a mesma história — "
            "qualquer múltiplo diferente é uma aposta sobre o mercado, não sobre a empresa."
        )
    elif modo == "entrada":
        colunas[2].metric("P/L de saída", formatar(multiplo_entrada, "multiplo"))

    try:
        return decompor_tsr(
            preco_entrada=preco,
            lucro_entrada=lucro_entrada,
            lucro_saida=lucro_saida,
            dividendos=acionista.dividendos,
            multiplo_saida=multiplo_saida,
            meio_de_ano=estado.config()["meio_de_ano"],
        )
    except (ValueError, CombinacaoInviavel) as erro:
        st.error(str(erro))
        return None


# ---------------------------------------------------------------------------
# Saidas
# ---------------------------------------------------------------------------


def _cartoes(decomposicao, resultado) -> None:
    ke = resultado.custo_capital.ke_brl
    colunas = st.columns(4)

    with colunas[0]:
        metrica(
            "TSR esperado (TIR)",
            decomposicao.tsr,
            "pct2",
            ajuda="Taxa interna de retorno dos fluxos: preço pago, dividendos e venda.",
        )
    with colunas[1]:
        metrica("Retorno exigido (Ke)", ke, "pct2")
    with colunas[2]:
        metrica(
            "Prêmio sobre o exigido",
            decomposicao.tsr - ke,
            "pct2",
            ajuda="TSR esperado menos o custo do capital próprio.",
        )
    with colunas[3]:
        metrica("P/L de entrada", decomposicao.multiplo_entrada, "multiplo")

    excedente = decomposicao.tsr - ke
    if excedente > 0.01:
        st.success(
            f"A este preço, o retorno esperado supera o exigido em "
            f"{formatar(excedente, 'pct')} ao ano."
        )
    elif excedente < -0.01:
        st.warning(
            f"A este preço, o retorno esperado fica {formatar(abs(excedente), 'pct')} "
            "ao ano **abaixo** do que o risco da empresa exige."
        )
    else:
        st.info(
            "O retorno esperado está praticamente igual ao exigido — o preço está "
            "próximo do valor justo do modelo."
        )

    _explicar_divergencia(decomposicao, resultado, ke)


def _explicar_divergencia(decomposicao, resultado, ke: float) -> None:
    """Explica por que comprar pelo valor justo pode nao render exatamente o Ke.

    Sem esta nota, o usuario ve dois numeros que deveriam bater e conclui,
    razoavelmente, que o app esta errado. A causa e conhecida e vale a pena
    dizer qual e.
    """
    no_valor_justo = abs(
        decomposicao.preco_entrada / resultado.equity_value - 1
    ) < 0.005
    if not no_valor_justo or abs(decomposicao.tsr - ke) < 0.005:
        return

    empresa = estado.empresa()
    alavancagem_alvo = empresa.custo_capital.divida_pl_alvo
    alavancagem_efetiva = (
        empresa.ponte.divida_liquida / resultado.equity_value
        if resultado.equity_value > 0
        else float("nan")
    )

    with st.expander(
        "Por que o retorno ao valor justo não é exatamente o Ke?", expanded=True
    ):
        st.markdown(
            "Comprando exatamente pelo valor que o DCF calculou, o retorno esperado "
            "**deveria** igualar o custo do capital próprio. Ele não iguala aqui, e a "
            "razão não é erro de conta — é uma inconsistência conhecida entre as duas "
            "formas de avaliar:\n\n"
            "- O **DCF** desconta o fluxo da firma a um WACC calculado com uma "
            "estrutura de capital **alvo constante**.\n"
            "- O **TSR** parte da dívida em valor nominal, que não acompanha o "
            "crescimento da empresa. A alavancagem efetiva cai ao longo da projeção, "
            "e o WACC constante deixa de descrevê-la.\n\n"
            "É a divergência clássica entre avaliar por FCFF/WACC e por FCFE/Ke sob "
            "política de dívida fixa em valor nominal."
        )
        if np.isfinite(alavancagem_efetiva):
            colunas = st.columns(2)
            colunas[0].metric(
                "D/E alvo usado no WACC", formatar(alavancagem_alvo, "numero")
            )
            colunas[1].metric(
                "D/E efetivo neste valuation", formatar(alavancagem_efetiva, "numero")
            )
            if abs(alavancagem_efetiva - alavancagem_alvo) > 0.15:
                st.warning(
                    "Os dois estão bem distantes. Aproximar o D/E alvo do efetivo, na "
                    "tela de **Custo de capital**, reduz a divergência e torna o WACC "
                    "coerente com o próprio resultado que ele produziu."
                )


def _decomposicao(decomposicao) -> None:
    contribuicoes = [
        ("Crescimento do lucro", decomposicao.contribuicao_crescimento),
        ("Dividendos", decomposicao.contribuicao_dividendos),
        ("Múltiplo (re-rating)", decomposicao.contribuicao_multiplo),
        ("Termo cruzado", decomposicao.contribuicao_cruzada),
    ]

    grafico(
        cascata_tsr(contribuicoes, decomposicao.tsr, "Fontes do retorno esperado"),
        decomposicao.tabela().style.format("{:.2%}", na_rep="—"),
    )

    if not decomposicao.fecha():
        st.error(
            "As parcelas não somam o TSR — há inconsistência no cálculo. "
            f"Resíduo: {formatar(decomposicao.residuo, 'pct2')}."
        )

    st.markdown("#### Como ler")
    fontes = {
        "Crescimento do lucro": (
            decomposicao.contribuicao_crescimento,
            "Depende da empresa entregar. É a fonte sobre a qual a análise "
            "fundamentalista tem algo a dizer.",
        ),
        "Dividendos": (
            decomposicao.contribuicao_dividendos,
            "Caixa no bolso, independente do que o mercado ache do papel. É a fonte "
            "mais previsível das três.",
        ),
        "Múltiplo": (
            decomposicao.contribuicao_multiplo,
            "Não depende da empresa, e sim de quanto o próximo comprador pagará. "
            "Retorno que depende principalmente daqui é aposta sobre o mercado.",
        ),
    }
    for nome, (valor, explicacao) in fontes.items():
        participacao = valor / decomposicao.tsr if decomposicao.tsr else float("nan")
        with st.container(border=True):
            colunas = st.columns([2, 1, 6])
            colunas[0].markdown(f"**{nome}**")
            colunas[1].markdown(f"**{formatar(valor, 'pct2')}**")
            colunas[2].caption(
                f"{formatar(participacao, 'pct')} do retorno total. {explicacao}"
            )

    peso_multiplo = (
        abs(decomposicao.contribuicao_multiplo) / abs(decomposicao.tsr)
        if decomposicao.tsr
        else float("nan")
    )
    if np.isfinite(peso_multiplo) and peso_multiplo > 0.4:
        st.warning(
            f"**{formatar(peso_multiplo, 'pct')} do retorno vem da mudança de múltiplo.** "
            "Essa é a parcela que não depende da empresa. Uma tese ancorada em re-rating "
            "precisa explicar por que o mercado mudaria de opinião — e o que acontece se "
            "não mudar."
        )

    if decomposicao.contribuicao_cruzada != 0:
        st.caption(
            f"O termo cruzado ({formatar(decomposicao.contribuicao_cruzada, 'pct2')}) é o "
            "produto entre crescimento e re-rating: os dois se multiplicam, e o resultado "
            "não pertence a nenhum deles isoladamente. A regra de bolso do mercado o "
            "ignora; aqui ele aparece para que as parcelas somem o total exatamente."
        )

    with st.expander("Detalhes da entrada e da saída"):
        st.dataframe(
            decomposicao.resumo().to_frame("Valor").style.format("{:,.4f}"),
            width="stretch",
        )


def _preco(decomposicao, resultado, acionista) -> None:
    st.markdown(
        "O preço é a única variável que o investidor controla de verdade. As premissas "
        "da empresa são as mesmas para todo mundo; o retorno, não."
    )

    unidade = estado.empresa().unidade
    ke = resultado.custo_capital.ke_brl

    alvo = st.slider(
        "Retorno anual desejado (%)",
        min_value=0.0,
        max_value=40.0,
        value=float(round(ke * 100, 1)),
        step=0.5,
    )

    try:
        preco_maximo = preco_para_tsr(
            tsr_alvo=alvo / 100,
            lucro_entrada_por_preco=decomposicao.lucro_entrada,
            lucro_saida=decomposicao.lucro_saida,
            dividendos=acionista.dividendos,
            multiplo_saida=decomposicao.multiplo_saida,
        )
    except (ValueError, CombinacaoInviavel) as erro:
        st.error(str(erro))
        return

    colunas = st.columns(3)
    with colunas[0]:
        metrica(f"Preço máximo para {alvo:.1f}% a.a.", preco_maximo, "moeda", unidade)
    with colunas[1]:
        metrica("Preço considerado", decomposicao.preco_entrada, "moeda", unidade)
    with colunas[2]:
        margem = preco_maximo / decomposicao.preco_entrada - 1
        metrica(
            "Margem de segurança",
            margem,
            "pct",
            ajuda="Quanto o preço máximo está acima (ou abaixo) do preço considerado.",
        )

    if margem > 0:
        st.success(
            f"Pagando até {formatar(preco_maximo, 'moeda', unidade)} você ainda obtém "
            f"{alvo:.1f}% ao ano. O preço considerado está "
            f"{formatar(margem, 'pct')} abaixo desse teto."
        )
    else:
        st.warning(
            f"Para obter {alvo:.1f}% ao ano seria preciso pagar no máximo "
            f"{formatar(preco_maximo, 'moeda', unidade)} — "
            f"{formatar(abs(margem), 'pct')} abaixo do preço considerado."
        )

    # Curva do retorno em funcao do preco.
    base = decomposicao.preco_entrada
    precos = [base * fator for fator in (0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.4)]
    retornos = []
    for preco in precos:
        try:
            retornos.append(
                decompor_tsr(
                    preco_entrada=preco,
                    lucro_entrada=decomposicao.lucro_entrada,
                    lucro_saida=decomposicao.lucro_saida,
                    dividendos=decomposicao.dividendos,
                    multiplo_saida=decomposicao.multiplo_saida,
                    meio_de_ano=estado.config()["meio_de_ano"],
                ).tsr
            )
        except (ValueError, CombinacaoInviavel):
            retornos.append(float("nan"))

    grafico(
        tsr_por_preco(precos, retornos, base, alvo / 100, unidade),
        pd.DataFrame({"Preço": precos, "TSR esperado": retornos}).set_index("Preço"),
    )


def _ponte_ev(resultado, acionista, decomposicao) -> None:
    st.markdown(
        "A leitura complementar, no formato usado em private equity: as parcelas em "
        "**valor**, não em taxa, e com a **desalavancagem** separada. Em empresa "
        "endividada, boa parte do ganho vem simplesmente de a dívida encolher — e isso "
        "não aparece nem como crescimento nem como múltiplo."
    )

    empresa = estado.empresa()
    unidade = empresa.unidade
    projecao = resultado.projecao

    ebitda_entrada = float(projecao.ebitda[0])
    ebitda_saida = float(projecao.ebitda[-1])
    divida_entrada = empresa.ponte.divida_bruta
    divida_saida = float(acionista.divida_fechamento[-1])

    colunas = st.columns(2)
    multiplo_entrada = colunas[0].number_input(
        "EV/EBITDA de entrada",
        value=float(round((decomposicao.preco_entrada + divida_entrada) / ebitda_entrada, 2)),
        step=0.25,
        min_value=0.1,
    )
    multiplo_saida = colunas[1].number_input(
        "EV/EBITDA de saída",
        value=float(multiplo_entrada),
        step=0.25,
        min_value=0.1,
    )

    ponte = decompor_ponte_ev(
        ebitda_entrada=ebitda_entrada,
        ebitda_saida=ebitda_saida,
        multiplo_entrada=multiplo_entrada,
        multiplo_saida=multiplo_saida,
        divida_entrada=divida_entrada,
        divida_saida=divida_saida,
        dividendos_acumulados=float(np.sum(acionista.dividendos)),
    )

    itens = [
        ("Equity na entrada", ponte.equity_entrada),
        ("Crescimento do EBITDA", ponte.contribuicao_ebitda),
        ("Múltiplo", ponte.contribuicao_multiplo),
        ("Termo cruzado", ponte.contribuicao_cruzada),
        ("Desalavancagem", ponte.contribuicao_desalavancagem),
        ("Dividendos", ponte.dividendos_acumulados),
        ("Equity na saída + dividendos", ponte.equity_saida + ponte.dividendos_acumulados),
    ]
    grafico(
        cascata_ponte(itens, unidade),
        tabela_formatada(ponte.tabela(), "moeda", unidade),
    )

    if not ponte.fecha():
        st.error(f"A ponte não fecha. Resíduo: {formatar(ponte.residuo, 'moeda', unidade)}.")

    colunas = st.columns(3)
    with colunas[0]:
        metrica("Dívida na entrada", divida_entrada, "moeda", unidade)
    with colunas[1]:
        metrica("Dívida na saída", divida_saida, "moeda", unidade)
    with colunas[2]:
        metrica(
            "Valor transferido do credor",
            ponte.contribuicao_desalavancagem,
            "moeda",
            unidade,
        )


def _fluxos(acionista, decomposicao) -> None:
    unidade = estado.empresa().unidade
    st.markdown("#### Da operação ao bolso do acionista")
    st.dataframe(
        tabela_formatada(acionista.tabela(), "moeda", unidade), width="stretch"
    )

    st.markdown("#### Fluxos do investimento")
    st.caption("É desta série que sai a TIR: o desembolso na entrada, os dividendos e a venda.")
    fluxos = pd.DataFrame(
        {"Fluxo": decomposicao.fluxos},
        index=[f"Ano {i}" for i in range(len(decomposicao.fluxos))],
    ).T
    st.dataframe(tabela_formatada(fluxos, "moeda", unidade), width="stretch")
    st.caption(
        f"Dividendos acumulados: {formatar(float(np.sum(decomposicao.dividendos)), 'moeda', unidade)} · "
        f"Venda no ano {decomposicao.anos}: {formatar(decomposicao.preco_saida, 'moeda', unidade)}"
    )

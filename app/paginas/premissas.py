"""Tela de premissas operacionais: a projecao ano a ano."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd
import streamlit as st

from valuation.casos_especiais import normalizar_margem_ciclica
from valuation.historico import sugerir_premissas
from valuation.premissas import BASES_DO_MULTIPLO

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

    extras = {}
    if operacionais.arrendamento_pct_receita is not None:
        extras["arrendamento_pct_receita"] = redimensionar(
            operacionais.arrendamento_pct_receita
        )
    return replace(
        operacionais,
        crescimento_receita=redimensionar(operacionais.crescimento_receita),
        margem_ebitda=redimensionar(operacionais.margem_ebitda),
        depreciacao_pct_receita=redimensionar(operacionais.depreciacao_pct_receita),
        capex_pct_receita=redimensionar(operacionais.capex_pct_receita),
        capital_giro_pct_receita=redimensionar(operacionais.capital_giro_pct_receita),
        **extras,
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

    colunas_tabela = {
        "Crescimento da receita (%)": [v * 100 for v in operacionais.crescimento_receita],
        "Margem EBITDA (%)": [v * 100 for v in operacionais.margem_ebitda],
        "Depreciação / receita (%)": [v * 100 for v in operacionais.depreciacao_pct_receita],
        "Capex / receita (%)": [v * 100 for v in operacionais.capex_pct_receita],
        "Capital de giro / receita (%)": [
            v * 100 for v in operacionais.capital_giro_pct_receita
        ],
    }
    tem_arrendamento = operacionais.arrendamento_pct_receita is not None
    if tem_arrendamento:
        colunas_tabela["Arrendamento / receita (%)"] = [
            v * 100 for v in operacionais.arrendamento_pct_receita
        ]
    tabela = pd.DataFrame(colunas_tabela, index=[str(a) for a in anos])

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
    if tem_arrendamento:
        referencias.append(_referencia(analise, "Arrendamento / Divida bruta"))
    visiveis = [f"**{c}** — {r}" for c, r in zip(tabela.columns, referencias) if r]
    if visiveis:
        st.caption("Referências do histórico: " + " · ".join(visiveis))

    if tem_arrendamento:
        st.caption(
            "**Arrendamento / receita** é o saldo do passivo de arrendamento, não o "
            "aluguel do ano. Ele existe porque contrato novo de aluguel **não passa "
            "pelo capex**: assinar um ponto cria ativo e passivo na mesma hora. Sem "
            "esta linha, uma rede que abre lojas mostra EBITDA subindo, capex parado "
            "e FCFF generoso, enquanto a dívida cresce todo ano."
        )

    colunas = st.columns([1, 3])
    if colunas[0].button("Aplicar", type="primary"):
        novas = dict(
            crescimento_receita=[v / 100 for v in editada.iloc[:, 0]],
            margem_ebitda=[v / 100 for v in editada.iloc[:, 1]],
            depreciacao_pct_receita=[v / 100 for v in editada.iloc[:, 2]],
            capex_pct_receita=[v / 100 for v in editada.iloc[:, 3]],
            capital_giro_pct_receita=[v / 100 for v in editada.iloc[:, 4]],
        )
        if tem_arrendamento:
            novas["arrendamento_pct_receita"] = [v / 100 for v in editada.iloc[:, 5]]
        estado.substituir_bloco("operacionais", replace(operacionais, **novas))
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


ANCORAS = {
    "Livre — digito o número": "livre",
    "IPCA": "ipca",
    "PIB nominal": "pib_nominal",
}


def _perpetuidade(empresa) -> None:
    st.subheader("Perpetuidade")
    conceito("perpetuidade", "A parte do modelo que mais pesa no valor")

    perpetuidade = empresa.perpetuidade
    ipca = empresa.macro.inflacao_brl
    colunas = st.columns(4)

    metodo = colunas[0].selectbox(
        "Método",
        ["Crescimento perpétuo (Gordon)", "Múltiplo de saída"],
        index=0 if perpetuidade.metodo == "gordon" else 1,
    )
    usar_gordon = metodo.startswith("Crescimento")

    rotulos = list(ANCORAS)
    ancora = ANCORAS[
        colunas[1].selectbox(
            "De onde vem o g",
            rotulos,
            index=rotulos.index(
                next(r for r, v in ANCORAS.items() if v == perpetuidade.ancora)
            ),
            disabled=not usar_gordon,
            help=(
                "Ancorado, o crescimento perpétuo deixa de ser um número solto: "
                "estressar a macro passa a movê-lo junto. **IPCA** supõe crescimento "
                "real zero para sempre — a empresa acompanha os preços e nada mais. "
                "**PIB nominal** é o teto lógico: acima dele, a empresa acabaria "
                "maior que o país."
            ),
        )
    ]

    normalizar = colunas[2].checkbox(
        "Normalizar reinvestimento",
        value=perpetuidade.roic_perpetuidade is not None,
        disabled=not usar_gordon,
        help="Desconta do fluxo perpétuo a taxa de reinvestimento g/ROIC.",
    )
    roic_real = colunas[2].checkbox(
        "ROIC em termos reais",
        value=perpetuidade.roic_real is not None,
        disabled=not (usar_gordon and normalizar),
        help=(
            "O ROIC de g/ROIC é nominal. Com o g ancorado na macro, deixar o ROIC "
            "parado faz a taxa de reinvestimento subir sozinha quando a inflação "
            "sobe — e o estresse de inflação sai exagerado. Marcando aqui, o "
            "número abaixo é lido como real e o nominal acompanha o IPCA. **O "
            "valor de hoje não muda**; muda a resposta ao estresse."
        ),
    )
    # Marcar a caixa nao pode mudar o valuation: o padrao do campo passa a ser o
    # equivalente real do nominal que ja estava la. Deixar 15% virar 15% real
    # seria subir o ROIC efetivo para 20,75% sem ninguem pedir.
    nominal_atual = perpetuidade.roic_perpetuidade or 0.15
    if roic_real:
        padrao = (
            perpetuidade.roic_real
            if perpetuidade.roic_real is not None
            else (1 + nominal_atual) / (1 + ipca) - 1
        )
    else:
        padrao = nominal_atual

    roic = colunas[2].number_input(
        "ROIC perpétuo real (%)" if roic_real else "ROIC perpétuo (%)",
        value=float(padrao * 100),
        step=0.5,
        format="%.2f",
        disabled=not (usar_gordon and normalizar),
    )
    if roic_real:
        colunas[2].caption(
            f"Nominal a {formatar(ipca, 'pct')} de IPCA: "
            f"**{formatar((1 + roic / 100) * (1 + ipca) - 1, 'pct')}**"
        )

    # A base do múltiplo depende do caso: uma indústria sai por EV/EBITDA, uma
    # empresa cujo par negocia por lucro sai por P/L. **A escolha muda a moeda
    # do valor terminal** — EV/EBITDA dá valor de firma, P/L dá valor de equity
    # —, e é o app que faz a conversão para a moeda do fluxo, avisando.
    bases = list(BASES_DO_MULTIPLO.values())
    base = colunas[3].radio(
        "Múltiplo sobre",
        bases,
        index=bases.index(BASES_DO_MULTIPLO[perpetuidade.base_do_multiplo]),
        horizontal=True,
        disabled=usar_gordon,
        help=(
            "**EV/EBITDA** precifica a firma inteira e a dívida sai na ponte. "
            "**P/L** precifica o que sobra para o acionista — o lucro já é "
            "depois do juro —, então o app soma a dívida líquida de volta ao "
            "valor terminal para ela não ser descontada duas vezes."
        ),
    )
    base_escolhida = next(k for k, v in BASES_DO_MULTIPLO.items() if v == base)

    multiplo = colunas[3].number_input(
        f"Múltiplo de saída ({base})",
        value=float(perpetuidade.multiplo_saida or (7.0 if base_escolhida == "ebitda" else 12.0)),
        step=0.5,
        disabled=usar_gordon,
    )

    st.markdown("**Economia de longo prazo** — os dois números que formam o teto do g")
    colunas = st.columns(4)

    colunas[0].metric("IPCA de longo prazo", formatar(ipca, "pct"), border=True)
    colunas[0].caption("Editável em **Custo de capital** — de lá ele também entra no WACC.")

    pib_real = colunas[1].number_input(
        "PIB real de longo prazo (%)",
        value=float(empresa.macro.pib_real * 100),
        step=0.25,
        format="%.2f",
        help=(
            "Crescimento real da economia. Não entra no custo de capital: serve "
            "para compor o teto do crescimento perpétuo, e como âncora dele."
        ),
    )

    pib_nominal = (1 + ipca) * (1 + pib_real / 100) - 1
    colunas[2].metric("PIB nominal", formatar(pib_nominal, "pct"), border=True)
    colunas[2].caption("Os dois compostos, não somados.")

    previsto = {"livre": None, "ipca": ipca, "pib_nominal": pib_nominal}[ancora]
    crescimento = colunas[3].number_input(
        "Crescimento perpétuo (%)",
        value=float((previsto if previsto is not None else perpetuidade.crescimento_perpetuo) * 100),
        step=0.25,
        format="%.2f",
        disabled=not usar_gordon or previsto is not None,
        help=(
            "Teto natural: o crescimento nominal da economia. Acima disso, a "
            "empresa acabaria maior que o país."
        ),
    )
    if previsto is not None:
        colunas[3].caption("Derivado da âncora — para digitá-lo, escolha *Livre*.")

    if st.button("Aplicar perpetuidade"):
        alteracoes: dict = {"macro.pib_real": pib_real / 100}
        if usar_gordon:
            alteracoes["perpetuidade.metodo"] = "gordon"
            alteracoes["perpetuidade.ancora"] = ancora
            # Campos derivados nao viajam: mandar o numero da tela junto soltaria
            # a origem dele na hora de aplicar.
            if ancora == "livre":
                alteracoes["perpetuidade.crescimento_perpetuo"] = crescimento / 100
            if normalizar and roic_real:
                alteracoes["perpetuidade.roic_real"] = roic / 100
            else:
                alteracoes["perpetuidade.roic_perpetuidade"] = (
                    (roic / 100) if normalizar else None
                )
        else:
            alteracoes["perpetuidade.metodo"] = "multiplo"
            alteracoes["perpetuidade.multiplo_saida"] = multiplo
            alteracoes["perpetuidade.base_do_multiplo"] = base_escolhida
        try:
            estado.atualizar(alteracoes)
        except ValueError as erro:
            st.error(str(erro))
        else:
            st.rerun()

    _confrontar_com_o_focus(ipca, pib_real / 100)

    g_previsto = previsto if previsto is not None else crescimento / 100
    if usar_gordon and g_previsto > pib_nominal:
        st.warning(
            f"Crescimento de {formatar(g_previsto, 'pct')} supera o crescimento "
            f"nominal da economia ({formatar(pib_nominal, 'pct')} = IPCA de "
            f"{formatar(ipca, 'pct')} composto com PIB real de "
            f"{formatar(pib_real / 100, 'pct')})."
        )


def _confrontar_com_o_focus(ipca: float, pib_real: float) -> None:
    """O que está digitado, contra o que o mercado projeta.

    Os dois números que formam o teto do `g` são hoje escolha do analista —
    a prática do dono do projeto é IPCA de 5% e PIB real de 1,5%. O Focus tem os
    dois, e a comparação é a pergunta que se faz ao abrir esta tela.

    **Não busca nada sem o usuário pedir, e não troca nada sozinho.** Mesma regra
    do risco-país medido pela NTN-B: o padrão do app continua sendo a prática de
    quem o construiu, e o consenso entra como referência ao lado, não por cima.
    Aplicar é um segundo clique, explícito.
    """
    if not st.toggle(
        "Comparar com o Focus",
        value=False,
        key="comparar_focus",
        help=(
            "Busca as projeções do Boletim Focus no Banco Central. Só quando "
            "você pede, e o app não altera nenhuma premissa por conta própria."
        ),
    ):
        return

    from valuation import mercado

    try:
        focus = mercado.macro_do_focus()
    except mercado.ErroMercado as erro:
        st.warning(f"Não consegui falar com o Banco Central: {erro}")
        return

    colunas = st.columns(4)
    for coluna, (rotulo, no_modelo, no_focus, casas) in zip(
        colunas,
        (
            ("IPCA", ipca, focus.ipca, focus.respondentes["ipca"]),
            ("PIB real", pib_real, focus.pib_real, focus.respondentes["pib_real"]),
            ("Selic", None, focus.selic, focus.respondentes["selic"]),
            ("Câmbio", None, focus.cambio, focus.respondentes["cambio"]),
        ),
    ):
        if rotulo == "Câmbio":
            coluna.metric("Câmbio (Focus)", formatar(no_focus, "numero"), border=True)
        elif no_modelo is None:
            coluna.metric(f"{rotulo} (Focus)", formatar(no_focus, "pct"), border=True)
        else:
            coluna.metric(
                rotulo,
                formatar(no_modelo, "pct"),
                delta=f"{formatar(no_modelo - no_focus, 'pct')} vs. Focus",
                delta_color="off",
                border=True,
            )
        coluna.caption(f"{casas} casas responderam")

    st.caption(
        f"Coleta de {focus.coleta}, projeções para **{focus.ano_de_referencia}** — "
        "o ano mais distante da janela, e não o próximo: a projeção curta carrega "
        "o choque corrente, e premissa de perpetuidade quer regime. O Focus "
        "publica duas estatísticas por ano; esta é a de **30 dias**, a do "
        "relatório, que tem mais que o dobro de respondentes da de 5 dias."
    )

    if st.button("Usar os números do Focus"):
        estado.atualizar(
            {"macro.inflacao_brl": focus.ipca, "macro.pib_real": focus.pib_real}
        )
        st.rerun()


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

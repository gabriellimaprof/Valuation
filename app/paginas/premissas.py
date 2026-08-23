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
from ..componentes import (
    balizador,
    conceito,
    etapa,
    formatar,
    grafico,
    secao,
    tabela_de_indicadores,
    tabela_formatada,
)
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
    _perpetuidade(empresa, analise)

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

    _balizadores_da_projecao(editada, analise, tem_arrendamento)

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



# O indicador do histórico que baliza cada coluna do editor, na mesma ordem.
BALIZAS = (
    ("Crescimento da receita (%)", "Crescimento da receita"),
    ("Margem EBITDA (%)", "Margem EBITDA"),
    ("Depreciação / receita (%)", "Depreciacao / Receita"),
    ("Capex / receita (%)", "Capex / Receita"),
    ("Capital de giro / receita (%)", "Capital de giro / Receita"),
    ("Arrendamento / receita (%)", "Arrendamento / Divida bruta"),
)


def _balizadores_da_projecao(editada, analise, tem_arrendamento: bool) -> None:
    """O que você projetou, contra o que a empresa entregou e o que a base diz.

    A queixa que originou esta tabela: *"é muita opção, pouca explicação, e muita
    info que eu tenho que ficar indo e voltando pras outras janelas para
    verificar"*. Projetar margem de 25% sem ver que a empresa nunca passou de 19%
    é fácil, e o erro só aparece três telas depois — quando aparece.

    As três colunas respondem coisas diferentes e nenhuma sozinha basta: a média
    projetada é a decisão, a mediana histórica é a âncora mais forte, e o
    percentil da base cobre o caso da empresa sem histórico longo ou em
    transformação.
    """
    if analise is None:
        return

    from valuation import referencias

    linhas = []
    balizas = BALIZAS if tem_arrendamento else BALIZAS[:-1]
    for coluna, indicador in balizas:
        if coluna not in editada.columns:
            continue
        projetado = float(np.mean(editada[coluna])) / 100
        try:
            historico = float(analise.mediana(indicador))
        except Exception:  # noqa: BLE001 - indicador ausente na analise
            historico = float("nan")
        onde = referencias.descrever(indicador, projetado)
        linhas.append(
            {
                "Direcionador": coluna.replace(" (%)", ""),
                "Você projetou (média)": formatar(projetado, "pct"),
                "A empresa entregou (mediana)": formatar(historico, "pct"),
                "Onde isso cai na base": onde.replace("companhias brasileiras", "companhias")
                if onde
                else "—",
            }
        )

    if not linhas:
        return

    secao(
        "O que isso significa",
        "Sua projeção ao lado do que a empresa entregou e do que a base "
        "brasileira mostra — para não precisar sair da tela para conferir.",
    )
    st.html(
        tabela_de_indicadores(pd.DataFrame(linhas).set_index("Direcionador"))
    )

def _perpetuidade(empresa, analise=None) -> None:
    """A perpetuidade, mostrando **só os campos do método escolhido**.

    A tela desenhava os dois caminhos ao mesmo tempo — Gordon e múltiplo de
    saída — com o não escolhido em cinza. Oito controles à vista para quatro
    decisões, e metade deles inertes: era a maior parte do "é muita opção" da
    queixa. Campo desabilitado não ajuda quem não vai usá-lo; ele só ocupa a
    largura de que o campo usado precisava.
    """
    secao("Perpetuidade")
    conceito("perpetuidade", "A parte do modelo que mais pesa no valor")

    perpetuidade = empresa.perpetuidade
    ipca = empresa.macro.inflacao_brl

    metodo = st.radio(
        "Método",
        ["Crescimento perpétuo (Gordon)", "Múltiplo de saída"],
        index=0 if perpetuidade.metodo == "gordon" else 1,
        horizontal=True,
    )
    usar_gordon = metodo.startswith("Crescimento")

    pib_real, pib_nominal = _economia_de_longo_prazo(empresa, ipca)

    base_escolhida = perpetuidade.base_do_multiplo
    multiplo = perpetuidade.multiplo_saida
    ancora, crescimento, previsto = perpetuidade.ancora, 0.0, None
    normalizar = roic_real = para_o_acionista = False
    roic = 0.0

    if usar_gordon:
        (
            ancora,
            crescimento,
            previsto,
            normalizar,
            roic_real,
            roic,
            para_o_acionista,
        ) = _campos_do_gordon(perpetuidade, analise, ipca, pib_nominal)
    else:
        base_escolhida, multiplo = _campos_do_multiplo(perpetuidade)

    if st.button("Aplicar perpetuidade", type="primary"):
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
            elif para_o_acionista:
                # No FCFE o número digitado é ROE, e vai para o campo dele. O
                # ROIC é zerado junto: deixar os dois preenchidos faria o motor
                # escolher entre premissas que descrevem capitais diferentes.
                alteracoes["perpetuidade.roe_perpetuidade"] = (
                    (roic / 100) if normalizar else None
                )
                alteracoes["perpetuidade.roic_perpetuidade"] = None
            else:
                alteracoes["perpetuidade.roic_perpetuidade"] = (
                    (roic / 100) if normalizar else None
                )
                alteracoes["perpetuidade.roe_perpetuidade"] = None
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


def _economia_de_longo_prazo(empresa, ipca: float) -> tuple[float, float]:
    """IPCA e PIB, recolhidos — com os números no próprio título do expansor.

    Ocupavam uma fila de quatro colunas para um único campo editável. No título
    eles continuam à vista sem gastar a largura, e quem quer mexer abre.
    """
    pib_real_atual = empresa.macro.pib_real
    nominal_atual = (1 + ipca) * (1 + pib_real_atual) - 1

    with st.expander(
        f"Economia de longo prazo — IPCA {formatar(ipca, 'pct')} · "
        f"PIB nominal {formatar(nominal_atual, 'pct')}"
    ):
        st.caption(
            "Os dois números que formam o teto do crescimento perpétuo, "
            "**compostos e não somados**. O IPCA é editável em **Custo de "
            "capital** — de lá ele também entra no WACC."
        )
        pib_real = st.number_input(
            "PIB real de longo prazo (%)",
            value=float(pib_real_atual * 100),
            step=0.25,
            format="%.2f",
            help=(
                "Crescimento real da economia. Não entra no custo de capital: "
                "serve para compor o teto do crescimento perpétuo, e como "
                "âncora dele."
            ),
        )
    return pib_real, (1 + ipca) * (1 + pib_real / 100) - 1


def _campos_do_gordon(perpetuidade, analise, ipca: float, pib_nominal: float):
    """Âncora, crescimento e normalização do reinvestimento."""
    colunas = st.columns(3)

    rotulos = list(ANCORAS)
    ancora = ANCORAS[
        colunas[0].selectbox(
            "De onde vem o g",
            rotulos,
            index=rotulos.index(
                next(r for r, v in ANCORAS.items() if v == perpetuidade.ancora)
            ),
            help=(
                "Ancorado, o crescimento perpétuo deixa de ser um número solto: "
                "estressar a macro passa a movê-lo junto. **IPCA** supõe crescimento "
                "real zero para sempre — a empresa acompanha os preços e nada mais. "
                "**PIB nominal** é o teto lógico: acima dele, a empresa acabaria "
                "maior que o país."
            ),
        )
    ]

    previsto = {"livre": None, "ipca": ipca, "pib_nominal": pib_nominal}[ancora]
    crescimento = colunas[1].number_input(
        "Crescimento perpétuo (%)",
        value=float(
            (previsto if previsto is not None else perpetuidade.crescimento_perpetuo)
            * 100
        ),
        step=0.25,
        format="%.2f",
        disabled=previsto is not None,
        help=(
            "Teto natural: o crescimento nominal da economia. Acima disso, a "
            "empresa acabaria maior que o país."
        ),
    )
    if previsto is not None:
        colunas[1].caption("Derivado da âncora — para digitá-lo, escolha *Livre*.")
    with colunas[1]:
        balizador(
            crescimento / 100,
            "Crescimento da receita",
            analise,
            "pct",
            contexto=(
                f"Teto: {formatar(pib_nominal, 'pct')} — o PIB nominal."
                if crescimento / 100 <= pib_nominal
                else f"**Acima do PIB nominal ({formatar(pib_nominal, 'pct')})**: "
                "a empresa acabaria maior que o país."
            ),
        )

    # **O retorno da normalização depende de qual fluxo se desconta.** Crescer
    # para sempre exige reinvestir para sempre, e a taxa é `g / retorno` — mas o
    # retorno tem de descrever o mesmo capital que o fluxo remunera: ROIC para o
    # FCFF, ROE para o FCFE. Rotular sempre "ROIC" fazia o campo pedir uma coisa
    # e o modelo usar outra.
    para_o_acionista = estado.config()["tipo_fluxo"] == "fcfe"
    sigla = "ROE" if para_o_acionista else "ROIC"

    normalizar = colunas[2].checkbox(
        "Normalizar reinvestimento",
        value=(perpetuidade.roic_perpetuidade is not None)
        or (perpetuidade.roe_perpetuidade is not None),
        help=f"Desconta do fluxo perpétuo a taxa de reinvestimento g/{sigla}.",
    )
    roic_real = False
    roic = 0.0
    if normalizar:
        roic_real = colunas[2].checkbox(
            f"{sigla} em termos reais",
            value=perpetuidade.roic_real is not None,
            help=(
                f"O {sigla} de g/{sigla} é nominal. Com o g ancorado na macro, "
                "deixá-lo parado faz a taxa de reinvestimento subir sozinha "
                "quando a inflação sobe — e o estresse de inflação sai "
                "exagerado. Marcando aqui, o número abaixo é lido como real e o "
                "nominal acompanha o IPCA. **O valor de hoje não muda**; muda a "
                "resposta ao estresse."
            ),
        )
        # Marcar a caixa nao pode mudar o valuation: o padrao do campo passa a
        # ser o equivalente real do nominal que ja estava la. Deixar 15% virar
        # 15% real seria subir o ROIC efetivo para 20,75% sem ninguem pedir.
        guardado = (
            perpetuidade.roe_perpetuidade if para_o_acionista else None
        ) or perpetuidade.roic_perpetuidade
        nominal_atual = guardado or (0.18 if para_o_acionista else 0.15)
        padrao = (
            (
                perpetuidade.roic_real
                if perpetuidade.roic_real is not None
                else (1 + nominal_atual) / (1 + ipca) - 1
            )
            if roic_real
            else nominal_atual
        )
        roic = colunas[2].number_input(
            f"{sigla} perpétuo real (%)" if roic_real else f"{sigla} perpétuo (%)",
            value=float(padrao * 100),
            step=0.5,
            format="%.2f",
        )
        if roic_real:
            colunas[2].caption(
                f"Nominal a {formatar(ipca, 'pct')} de IPCA: "
                f"**{formatar((1 + roic / 100) * (1 + ipca) - 1, 'pct')}**"
            )
        with colunas[2]:
            # A pergunta que este campo levanta e nao respondia: 25% e muito ou
            # pouco? A resposta estava duas telas atras, no Historico.
            balizador(
                roic / 100,
                sigla,
                analise,
                "pct",
                contexto=(
                    "Acima do histórico exige motivo: é dizer que a empresa vai "
                    "empregar capital novo melhor do que empregou o antigo."
                ),
            )

    return ancora, crescimento, previsto, normalizar, roic_real, roic, para_o_acionista


def _campos_do_multiplo(perpetuidade):
    """A conta em que o múltiplo incide, e o múltiplo."""
    colunas = st.columns(3)

    # A base do múltiplo depende do caso: uma indústria sai por EV/EBITDA, uma
    # empresa cujo par negocia por lucro sai por P/L. **A escolha muda a moeda
    # do valor terminal** — EV/EBITDA dá valor de firma, P/L dá valor de equity
    # —, e é o app que faz a conversão para a moeda do fluxo, avisando.
    bases = list(BASES_DO_MULTIPLO.values())
    base = colunas[0].radio(
        "Múltiplo sobre",
        bases,
        index=bases.index(BASES_DO_MULTIPLO[perpetuidade.base_do_multiplo]),
        horizontal=True,
        help=(
            "**EV/EBITDA** precifica a firma inteira e a dívida sai na ponte. "
            "**P/L** precifica o que sobra para o acionista — o lucro já é "
            "depois do juro —, então o app soma a dívida líquida de volta ao "
            "valor terminal para ela não ser descontada duas vezes."
        ),
    )
    base_escolhida = next(k for k, v in BASES_DO_MULTIPLO.items() if v == base)

    multiplo = colunas[1].number_input(
        f"Múltiplo de saída ({base})",
        value=float(
            perpetuidade.multiplo_saida or (7.0 if base_escolhida == "ebitda" else 12.0)
        ),
        step=0.5,
    )
    colunas[2].caption(
        "O múltiplo troca duas premissas de perpetuidade por uma — e por uma que "
        "o mercado observa. O custo é que ele **não diz de onde vem o valor**: "
        "7x embute crescimento e retorno que ficam implícitos. Em **Retorno "
        "esperado** o app mostra qual múltiplo o próprio DCF implica."
    )
    return base_escolhida, multiplo


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

"""Tela de valor: o resultado do DCF e a anatomia de como ele se forma."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from valuation import substituir_varios

from .. import estado
from ..componentes import (
    aviso_sem_modelo,
    conceito,
    em_texto,
    etapa,
    formatar,
    grafico,
    metrica,
    tabela_formatada,
)
from ..graficos import cascata_ponte, composicao_do_valor, fluxos_projetados


def render() -> None:
    etapa("Passo 5", "Valor", "O resultado, e de onde cada parte dele vem")

    # Banco e seguradora saem por outra porta, e **antes** de qualquer número
    # aparecer: mostrar um EV descontado ao WACC para eles seria mostrar um
    # número errado com aparência de certo.
    if _banco_em_vez_de_dcf():
        return

    # A configuracao vem **antes** do resultado. Escolher FCFE sem cronograma
    # deixava o modelo sem fechar, e o editor que resolveria isso ficava atras
    # da mensagem de erro -- o usuario via "nao fecha" sem alcance ao que
    # faltava.
    _configuracao()

    resultado = estado.resultado()
    if resultado is None:
        aviso_sem_modelo(estado.erro_do_modelo())
        return

    empresa = estado.empresa()
    unidade = empresa.unidade
    dcf = resultado.dcf

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



def _banco_em_vez_de_dcf() -> bool:
    """Instituição financeira não se avalia por FCFF descontado ao WACC.

    O motivo não é técnico, é econômico: para uma indústria a dívida financia o
    ativo e o custo dela entra na taxa de desconto; para um banco a dívida —
    depósito, captação — **é o insumo do negócio**, e o spread entre captar e
    emprestar é a receita. Descontar um "fluxo para a firma" ao WACC de um banco
    soma ao valor o que ele ganha por tomar dinheiro e depois desconta por ele
    tomar dinheiro.

    São 19 das 467 companhias da base. Devolve ``True`` quando desenhou a tela
    do banco, para o chamador não seguir para o DCF.
    """
    from valuation.bancos import e_instituicao_financeira, sugerir_premissas_do_banco
    from valuation.lucro_residual import avaliar_lucro_residual

    dfs = estado.demonstracoes()
    if dfs is None or not e_instituicao_financeira(dfs):
        return False

    st.warning(
        "**Esta companhia publica no plano de contas de instituição financeira, "
        "e o DCF de FCFF ao WACC não se aplica a ela.** Para um banco a dívida "
        "não financia o ativo — ela *é* o insumo do negócio, e o spread entre "
        "captar e emprestar é a receita. Em vez do fluxo para a firma, o valor "
        "aqui sai do **lucro residual**: o patrimônio que a instituição tem, "
        "mais o valor presente do que ela ganha acima do custo de capital sobre "
        "esse patrimônio."
    )

    ke, realavancava = _ke_de_instituicao_financeira()
    if realavancava is not None:
        st.warning(
            f"**O beta desta empresa estava sendo realavancado, e isso não vale "
            f"para banco.** Hamada supõe que a dívida é escolha de financiamento "
            "que acrescenta risco ao acionista; num banco o depósito é a "
            "**matéria-prima**, e o risco dele já está dentro do beta observado "
            f"do equity. Com o D/E alvo que está em Custo de capital, o Ke sairia "
            f"{formatar(realavancava, 'pct')}; sem realavancar, "
            f"**{formatar(ke, 'pct')}**. Usei o segundo.\n\n"
            "Medido nas 18 instituições com balanço legível em 2024: o passivo de "
            "terceiros é **11,2x o patrimônio na mediana**, e realavancar um beta "
            "de 0,95 por esse D/E daria beta 8,0 e Ke de **41% em dólar**. Banco "
            "nenhum tem isso — os betas observados ficam perto de 1."
        )

    try:
        sugestao = sugerir_premissas_do_banco(dfs)
    except ValueError as erro:
        st.error(str(erro))
        return True

    colunas = st.columns(3)
    roe = colunas[0].number_input(
        "ROE projetado (%)",
        value=float(sugestao.premissas.roe[0] * 100),
        step=0.5,
        format="%.2f",
        help="Retorno sobre o patrimônio médio. Mediana histórica, por padrão.",
    )
    payout = colunas[1].number_input(
        "Payout (%)",
        value=float(sugestao.premissas.payout[0] * 100),
        min_value=0.0,
        max_value=100.0,
        step=5.0,
        format="%.1f",
        help="Quanto do lucro é distribuído. O resto fica retido e faz o patrimônio crescer.",
    )
    roe_perpetuo = colunas[2].number_input(
        "ROE perpétuo (%)",
        value=float(ke * 100),
        step=0.5,
        format="%.2f",
        help=(
            "Igual ao Ke zera o valor terminal — a afirmação de que a vantagem "
            "competitiva não sobrevive para sempre. É o padrão para instituição "
            "madura, e é a premissa que mais move o resultado."
        ),
    )

    horizonte = sugestao.premissas.horizonte
    premissas = substituir_varios(
        sugestao.premissas,
        {
            "roe": [roe / 100] * horizonte,
            "payout": [payout / 100] * horizonte,
            "roe_perpetuo": roe_perpetuo / 100,
        },
    )
    try:
        # O ano-base e o ultimo do historico: sem ele a tabela numera as linhas
        # 1, 2, 3... e o analista conta nos dedos qual exercicio esta olhando.
        valuation = avaliar_lucro_residual(
            premissas, ke=ke, ano_base=int(dfs.anos[-1])
        )
    except ValueError as erro:
        st.error(str(erro))
        return True

    unidade = estado.empresa().unidade
    cartoes = st.columns(4)
    with cartoes[0]:
        metrica("Equity Value", valuation.equity_value, "moeda", unidade)
    with cartoes[1]:
        metrica("Patrimônio contábil", valuation.patrimonio_inicial, "moeda", unidade)
    with cartoes[2]:
        metrica(
            "P/VP implícito",
            valuation.equity_value / valuation.patrimonio_inicial,
            "multiplo",
            ajuda="Abaixo de 1x, o modelo diz que a instituição destrói valor sobre o próprio livro.",
        )
    with cartoes[3]:
        metrica("Ke", ke, "pct2")

    if valuation.equity_value < valuation.patrimonio_inicial:
        st.info(
            f"**O modelo devolve menos que o patrimônio contábil.** Com ROE de "
            f"{formatar(roe / 100, 'pct')} abaixo do Ke de {formatar(ke, 'pct')}, "
            "cada real retido rende menos que o custo de capital — e a conta diz "
            "isso sem que ninguém precise afirmar."
        )

    st.markdown("#### A conta, ano a ano")
    st.caption(
        f"Valores em {unidade}. O custo do capital próprio incide sobre o "
        "patrimônio de **abertura**: o lucro do ano foi ganho sobre o capital que "
        "estava lá no começo dele."
    )
    st.dataframe(tabela_formatada(valuation.tabela(), "moeda"), width="stretch")

    colunas = st.columns(3)
    with colunas[0]:
        metrica("Do patrimônio", valuation.peso_do_patrimonio, "pct")
    with colunas[1]:
        metrica(
            "Do lucro acima do Ke",
            valuation.valor_presente_residual / valuation.equity_value
            if valuation.equity_value
            else float("nan"),
            "pct",
        )
    with colunas[2]:
        metrica("Do valor terminal", valuation.peso_do_terminal, "pct")
    st.caption(
        "**É a virtude do modelo.** No DCF de uma indústria o valor terminal "
        "costuma valer 60% a 80% do total, e a premissa mais frágil carrega quase "
        "tudo. Aqui a âncora contábil segura a maior parte, e erro na "
        "perpetuidade custa menos."
    )

    with st.expander("O que o histórico diz, e o que este modelo não faz"):
        st.dataframe(
            tabela_formatada(sugestao.historico.tabela(), "numero"), width="stretch"
        )
        for chave, texto in sugestao.justificativas.items():
            st.markdown(f"- **{chave}** — {texto}")
        for alerta in sugestao.alertas:
            st.warning(alerta)

    return True



def _ke_de_instituicao_financeira() -> tuple[float, float | None]:
    """O Ke do banco, com o beta **não** realavancado.

    Devolve ``(ke, ke_que_sairia_realavancando)``. O segundo é ``None`` quando as
    premissas já estavam marcadas como instituição financeira — aí não há o que
    avisar, porque nada mudou.

    Existe porque o usuário pode ter escolhido um setor industrial na tela de
    Custo de capital antes de importar um banco, e nesse caso o Ke que chega aqui
    carrega um realavancamento que não se aplica.
    """
    from valuation import substituir_varios
    from valuation.custo_capital import calcular_custo_capital

    empresa = estado.empresa()
    if empresa is None:
        return 0.145, None

    ja_marcado = getattr(empresa.custo_capital, "instituicao_financeira", False)
    correto = calcular_custo_capital(
        substituir_varios(
            empresa.custo_capital, {"instituicao_financeira": True}
        ),
        empresa.macro,
    ).ke_brl
    if ja_marcado:
        return correto, None

    realavancado = calcular_custo_capital(empresa.custo_capital, empresa.macro).ke_brl
    # Só avisa quando a diferença existe: com D/E alvo zerado os dois coincidem,
    # e um aviso que não corresponde a mudança nenhuma treina o leitor a ignorar.
    if abs(realavancado - correto) < 1e-9:
        return correto, None
    return correto, realavancado


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

    if config["tipo_fluxo"] == "fcfe":
        _cronograma_de_divida(config)


def _cronograma_de_divida(config) -> None:
    """O saldo de dívida ao fim de cada ano projetado.

    **O FCFE não existe sem ele.** `FCFE = FCFF − juros × (1 − t) + variação da
    dívida`, e a variação da dívida só se conhece com o saldo ano a ano. O motor
    sempre suportou; faltava onde informar, e a tela oferecia o FCFE sem ter como
    calculá-lo.

    O padrão é dívida constante — a hipótese que a maioria dos modelos assume sem
    dizer. Ela não é neutra: com dívida constante a variação é zero e o FCFE fica
    abaixo do FCFF pelo juro depois de imposto. Amortizar derruba mais ainda o
    fluxo do acionista nos anos de pagamento.
    """
    empresa = estado.empresa()
    if empresa is None or empresa.operacionais is None:
        return
    anos = [
        empresa.operacionais.ano_base + i + 1
        for i in range(len(empresa.operacionais.crescimento_receita))
    ]
    inicial = float(empresa.ponte.divida_bruta)

    # Sempre aberto. Ele fechava sozinho: na primeira renderização o cronograma
    # ainda era ``None``, o bloco o preenchia com dívida constante e chamava
    # ``st.rerun()`` -- e na segunda passada ``expanded`` já era falso. Quem
    # acabou de escolher FCFE via o cronograma sumir sem nunca te-lo visto.
    with st.expander("Cronograma da dívida — obrigatório para o FCFE", expanded=True):
        st.caption(
            "Saldo de dívida bruta ao fim de cada ano. O "
            f"saldo de partida é {em_texto(inicial, empresa.unidade)}, o "
            "da ponte. O juro de cada ano incide sobre o saldo de **abertura**, e "
            "a variação do saldo entra no fluxo do acionista: amortizar consome "
            "caixa do acionista, captar devolve."
        )

        salvos = config.get("divida_por_ano")
        if not salvos or len(salvos) != len(anos):
            salvos = [inicial] * len(anos)

        # O ano vai como **coluna**, e não como índice: o ``data_editor`` esconde
        # o índice e numera as linhas 1, 2, 3…, o que faria o analista contar nos
        # dedos qual ano está editando.
        tabela = st.data_editor(
            pd.DataFrame({"Ano": anos, "Dívida ao fim do ano": salvos}),
            width="stretch",
            hide_index=True,
            key="editor_divida",
            column_config={
                "Ano": st.column_config.NumberColumn("Ano", format="%d", disabled=True),
                "Dívida ao fim do ano": st.column_config.NumberColumn(
                    f"Dívida ao fim do ano ({empresa.unidade})", format="%.1f"
                ),
            },
        )
        valores = [float(v) for v in tabela["Dívida ao fim do ano"]]

        colunas = st.columns([1, 1, 3])
        if colunas[0].button("Manter constante"):
            config["divida_por_ano"] = [inicial] * len(anos)
            st.rerun()
        if colunas[1].button("Amortizar até zero"):
            passo = inicial / len(anos)
            config["divida_por_ano"] = [
                max(inicial - passo * (i + 1), 0.0) for i in range(len(anos))
            ]
            st.rerun()

        if valores != list(config.get("divida_por_ano") or []):
            config["divida_por_ano"] = valores
            st.rerun()

        if any(v < 0 for v in valores):
            st.error(
                "Saldo de dívida negativo não é caixa líquido: é dívida negativa, "
                "que não existe. Use zero e leve o caixa para a ponte."
            )


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

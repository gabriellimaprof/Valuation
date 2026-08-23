"""Tela de historico: o que a empresa entregou, e por que entregou aquilo."""

from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st

from valuation.qualidade import BOM, RUIM, SEM_DADOS, avaliar_qualidade

from .. import estado
from ..componentes import (
    conceito,
    em_texto,
    etapa,
    formatar,
    grafico,
    formulas_dos_indicadores,
    metrica,
    secao,
    tabela_de_indicadores,
    tabela_financeira,
    tabela_formatada,
    unidade_curta,
)
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

    from valuation.casos_especiais import ver_ex_ifrs16

    visao = ver_ex_ifrs16(analise)
    rotulos = [
        "DRE",
        "Resultado",
        "Qualidade dos lucros",
        "Retorno e decomposição",
        "Reinvestimento",
        "Capital de giro",
    ]
    if visao is not None:
        rotulos += ["IFRS 16"]
    tem_arvore = getattr(dfs, "detalhe", None) is not None and not dfs.detalhe.empty
    if tem_arvore:
        rotulos += ["Liquidez e composição"]
    rotulos += ["Tudo"]
    abas = st.tabs(rotulos)

    with abas[0]:
        _dre_gerencial(dfs)
    with abas[1]:
        _resultado(analise, dfs)
    with abas[2]:
        _qualidade(analise)
    with abas[3]:
        _retorno(analise)
    with abas[4]:
        _reinvestimento(analise)
    with abas[5]:
        _capital_de_giro(analise)
    proxima = 6
    if visao is not None:
        with abas[proxima]:
            _ifrs16(visao, dfs)
        proxima += 1
    if tem_arvore:
        with abas[proxima]:
            _liquidez(analise, dfs)
    with abas[-1]:
        indicadores = analise.indicadores
        indicadores.columns = [str(c) for c in indicadores.columns]
        st.html(tabela_de_indicadores(indicadores, "numero"))

        secao("Resumo por indicador")
        st.html(tabela_de_indicadores(analise.resumo(), "numero"))

        formulas_dos_indicadores(list(analise.indicadores.index))


def _dre_gerencial(dfs) -> None:
    """A DRE na forma em que o analista a monta — e a conferência dela.

    A CVM publica a DRE numa árvore que serve para fiscalizar, não para modelar:
    ``3.04`` é um bloco único que junta SG&A, impairment, outras receitas,
    outras despesas e equivalência patrimonial. A tela abre os cinco, porque
    três não se repetem e um não é operacional.

    A conferência anda junto de propósito. A ponte é montada por subtração em
    vários pontos, e subtração com sinal trocado produz uma DRE que parece certa
    e não fecha — foi assim que apareceram os dois erros de sinal que já
    corrigimos. Quem lê precisa ver que ela fechou, não confiar que fechou.
    """
    st.markdown("#### A DRE do jeito que se modela")
    st.caption(
        "Receita líquida − custos = lucro bruto; menos SG&A, mais equivalência e "
        "outros = EBIT; mais D&A = EBITDA; menos o que não se repete = EBITDA "
        "ajustado; menos o resultado financeiro = LAIR; menos impostos = lucro "
        "líquido."
    )

    dre = dfs.dre_gerencial()
    if dre.empty:
        st.info("Sem DRE importada para montar a ponte.")
        return
    dre.columns = [str(coluna) for coluna in dre.columns]

    base = st.radio(
        "Como exibir",
        ["Valores", "% da receita líquida"],
        horizontal=True,
        key="dre_gerencial_base",
        help=(
            "Em percentual da receita a DRE vira estrutura de custo, que é o que "
            "se projeta — e o que se compara com par."
        ),
    )

    subtotais = set(dfs.SUBTOTAIS_DRE)

    # A unidade fica no rótulo da coluna e não em cada célula: com 22 linhas e 7
    # anos, repeti-la são 154 vezes o mesmo texto empurrando o número para fora
    # da largura útil. Visto no navegador, não no teste.
    if base == "Valores":
        st.html(tabela_financeira(dre, subtotais, "moeda", dfs.unidade))
    else:
        receita = dre.loc["Receita líquida"].replace(0, np.nan)
        st.html(tabela_financeira(dre.div(receita, axis=1), subtotais, "pct"))

    _conferencia_da_dre(dfs)

    st.info(
        "**O “EBITDA ajustado” daqui não é o do release da companhia, e a "
        "diferença pode ser grande.** O daqui tira o que a CVM padroniza em "
        "código — impairment (`3.04.03`), outras receitas (`3.04.04`) e outras "
        "despesas operacionais (`3.04.05`). O da companhia tira o que ela "
        "decidiu chamar de não recorrente no próprio release: reestruturação, "
        "despesa de M&A, remuneração em ações. Essas moram **dentro do SG&A**, "
        "não têm código próprio e não existem separadas no DFP — nenhum leitor "
        "as alcança sem a reconciliação que a companhia publica à parte.\n\n"
        # Tres cifroes na mesma frase: o Streamlit fecharia dois deles num par
        # ``$...$`` e o meio viraria formula. Escapados, como manda ``em_texto``.
        "Medido na Viveo de 2024: o release traz EBITDA ajustado de R\\$ 652 mi e "
        "esta ponte traz **R\\$ 131,8 mi**. Os dois estão certos sobre coisas "
        "diferentes. O que esta tela garante é que o número **sai dos códigos "
        "da CVM e fecha com o publicado**, sempre igual entre companhias — que é "
        "o que permite comparar; o do release não é comparável, porque cada uma "
        "define o seu."
    )

    st.caption(
        "**O SG&A sai por subtração, e não das contas `3.04.01` e `3.04.02`** — "
        "elas só existem em 297 e 454 das 467 companhias da base, enquanto o "
        "bloco `3.04` existe em todas. Tirando dele impairment, outras "
        "receitas/despesas e equivalência, sobra o SG&A de verdade para qualquer "
        "companhia. **Derivativos e câmbio saem por resíduo** do resultado "
        "financeiro: não há código padronizado para eles, então quando a "
        "companhia abre a linha ela cai num código livre dentro de `3.06` e o "
        "resíduo a captura; quando não abre, o resíduo é zero — que é a resposta "
        "certa."
    )


def _conferencia_da_dre(dfs) -> None:
    """Cada subtotal contra a soma das linhas que o compõem."""
    conferencia = dfs.conferir_dre_gerencial()
    if conferencia.empty:
        return
    conferencia.columns = [str(coluna) for coluna in conferencia.columns]

    valores = conferencia.to_numpy(dtype=float)
    pior = float(np.nanmax(valores)) if np.isfinite(valores).any() else 0.0

    if pior < 1e-6:
        st.success(
            "**Todos os subtotais fecham.** Cada um bate com a soma das linhas "
            "acima dele, em todos os anos."
        )
        with st.expander("Ver a conferência linha a linha"):
            st.dataframe(
                tabela_formatada(conferencia, "pct2"), width="stretch"
            )
        return

    st.warning(
        f"**Um subtotal não fecha** — desvio máximo de {formatar(pior, 'pct2')} "
        "sobre o valor publicado. Isso pode ser leitura errada **ou** a própria "
        "demonstração não reconciliando consigo mesma: a Azul de 2024, por "
        "exemplo, publica o lucro dos controladores positivo com o consolidado "
        "negativo. O app acusa e não conserta em silêncio — consertar esconderia "
        "de você que a companhia publicou algo inconsistente."
    )
    st.dataframe(
        tabela_formatada(conferencia, "pct2"),
        width="stretch",
    )


def _ifrs16(visao, dfs) -> None:
    """As duas leituras do resultado: com e sem o aluguel dentro do EBITDA.

    Não existe leitura "certa" aqui — existem duas, e a única coisa que não pode
    acontecer é misturá-las. A tela mostra as duas lado a lado justamente para
    que a comparação seja entre pares de números coerentes.
    """
    st.markdown(
        "Até 2018 o aluguel era despesa operacional e entrava no EBITDA. Desde o "
        "**IFRS 16 / CPC 06 (R2)** ele virou depreciação de direito de uso mais "
        "juros — então o EBITDA subiu sem que nada tenha melhorado no negócio, e "
        "o passivo de arrendamento apareceu no balanço."
    )

    if not visao.relevante:
        st.info(
            "Nesta companhia o aluguel é pequeno em relação ao EBITDA, então as "
            "duas leituras quase coincidem. A tabela abaixo mostra as duas mesmo "
            "assim."
        )

    unidade = dfs.unidade
    colunas = st.columns(4)
    with colunas[0]:
        metrica(
            "Margem EBITDA reportada",
            float(visao.margem_ebitda_reportada.dropna().iloc[-1]),
            "pct",
        )
    with colunas[1]:
        metrica(
            "Margem EBITDA ex-IFRS 16",
            float(visao.margem_ebitda.dropna().iloc[-1]),
            "pct",
        )
    with colunas[2]:
        metrica(
            "Dív. líq./EBITDA reportada",
            float(visao.alavancagem_reportada.dropna().iloc[-1]),
            "numero",
        )
    with colunas[3]:
        metrica(
            "Dív. líq./EBITDA ex-IFRS 16",
            float(visao.alavancagem.dropna().iloc[-1]),
            "numero",
        )

    st.warning(
        "**As duas colunas não se misturam.** Ou dívida **com** arrendamento sobre "
        "EBITDA **com** aluguel dentro, ou dívida **sem** arrendamento sobre EBITDA "
        "**sem** aluguel. Cruzar — dívida cheia sobre EBITDA ex-aluguel — infla a "
        "alavancagem; ao contrário, esconde."
    )

    anos = [str(a) for a in dfs.anos]
    tabela = pd.DataFrame(
        {
            "EBITDA reportado": visao.ebitda_reportado,
            "(−) Aluguel pago": -visao.aluguel,
            "EBITDA ex-IFRS 16": visao.ebitda,
            "EBIT reportado": visao.ebit_reportado,
            "(−) Juros de arrendamento": -visao.juros,
            "EBIT ex-IFRS 16": visao.ebit,
            "Dívida bruta reportada": visao.divida_bruta_reportada,
            "(−) Passivo de arrendamento": visao.divida_bruta - visao.divida_bruta_reportada,
            "Dívida bruta ex-IFRS 16": visao.divida_bruta,
        }
    ).T
    tabela.columns = anos
    st.dataframe(tabela_formatada(tabela, "moeda", unidade), width="stretch")

    st.markdown(f"**{visao.explicacao}**")
    if visao.ressalva:
        st.warning(visao.ressalva)

    _valuation_nas_duas_bases(visao, unidade)

    with st.expander("Como cada número é obtido"):
        st.markdown(
            "- **Aluguel** = principal + juros de arrendamento desembolsados no ano, "
            "lidos da DFC. É o que mais se parece com o aluguel que existia na DRE.\n"
            "- **EBITDA ex** = EBITDA − aluguel.\n"
            "- **EBIT ex** = EBIT − juros. O EBIT já desconta a depreciação do direito "
            "de uso, que em regime estacionário se aproxima do principal; o que sobra "
            "para tirar é o juro.\n"
            "- **Dívida ex** = dívida bruta − passivo de arrendamento.\n\n"
            "A depreciação do direito de uso viria mais direto, mas só **10% das "
            "companhias** a publicam em linha própria — esparsa demais para sustentar "
            "a conta."
        )


def _valuation_nas_duas_bases(visao, unidade: str) -> None:
    """Roda o DCF nas duas bases e mostra de onde vem a diferença.

    A diferença não é erro de conversão: o balanço reconhece o aluguel do
    **prazo contratado**, e quem aluga ponto comercial renova. A distância entre
    as duas avaliações mede quanto do valor vem de supor que o aluguel acaba.
    """
    from valuation.casos_especiais import (
        aluguel_perpetuo,
        empresa_ex_ifrs16,
        passivo_de_arrendamento,
    )

    resultado = estado.resultado()
    if resultado is None:
        return

    st.markdown("#### O mesmo valuation nas duas bases")
    try:
        convertida = empresa_ex_ifrs16(estado.empresa(), visao)
        ex = __import__("valuation", fromlist=["avaliar"]).avaliar(
            convertida, **estado.convencoes()
        )
    except (ValueError, ZeroDivisionError) as erro:
        st.info(f"Não consegui converter o modelo para a base ex-IFRS 16: {erro}")
        return

    wacc = resultado.dcf.taxa_desconto
    perpetuo = aluguel_perpetuo(visao, wacc, estado.empresa().macro.aliquota_ir)
    passivo = passivo_de_arrendamento(visao)

    colunas = st.columns(4)
    with colunas[0]:
        metrica("Equity — base reportada", resultado.equity_value, "moeda", unidade)
    with colunas[1]:
        metrica("Equity — base ex-IFRS 16", ex.equity_value, "moeda", unidade)
    with colunas[2]:
        metrica("Passivo de arrendamento (contratado)", passivo, "moeda", unidade)
    with colunas[3]:
        metrica("Aluguel perpétuo, a valor presente", perpetuo, "moeda", unidade)

    if np.isfinite(perpetuo) and np.isfinite(passivo):
        folga = perpetuo - passivo
        st.caption(
            f"O balanço reconhece {em_texto(passivo, unidade)} de "
            f"arrendamento — o valor presente dos aluguéis do **prazo contratado**. "
            f"Pagar aluguel para sempre custa {em_texto(perpetuo, unidade)} "
            f"a valor presente. A diferença de {em_texto(folga, unidade)} é o "
            "que a leitura reportada ganha por supor que o aluguel termina quando o "
            "contrato vence."
        )

    st.caption(
        "A conversão desloca a margem EBITDA pelo aluguel, tira a depreciação do "
        "direito de uso, zera as adições projetadas de arrendamento e retira o "
        "passivo da ponte. **O D/E alvo do custo de capital não é convertido** — "
        "quem o escolheu escolheu com a dívida cheia em mente, e mexer nisso é "
        "decisão de quem tem o julgamento."
    )


def _qualidade(analise) -> None:
    """A distância entre o lucro contábil e o caixa que ele gerou.

    O veredito é o **pior** sinal, não a média deles: uma boa conversão de caixa
    não cancela juro que virou ativo. Média de sinais é como um alerta some.
    """
    st.markdown(
        "Lucro é opinião, caixa é fato. Esta aba mede a distância entre os dois nos "
        "anos importados — não para acusar ninguém de nada, mas porque uma projeção "
        "ancorada num lucro que não vira caixa herda o problema inteiro."
    )

    qualidade = avaliar_qualidade(analise)
    st.session_state["qualidade"] = qualidade

    icone = {BOM: "🟢", RUIM: "🔴"}.get(qualidade.veredito, "🟡")
    if qualidade.veredito == BOM:
        st.success(f"{icone} {qualidade.resumo}")
    elif qualidade.veredito == RUIM:
        st.error(f"{icone} {qualidade.resumo}")
    elif qualidade.veredito == SEM_DADOS:
        st.info(f"⚪ {qualidade.resumo}")
    else:
        st.warning(f"{icone} {qualidade.resumo}")

    _conversao_em_dois_degraus(analise, qualidade)

    for sinal in qualidade.por_severidade:
        with st.expander(f"{sinal.icone} {sinal.titulo}", expanded=sinal.veredito == RUIM):
            st.markdown(sinal.detalhe)
            if np.isfinite(sinal.valor):
                st.caption(f"Medido: {formatar(sinal.valor, 'pct2')}")

    # Este texto dizia que os cortes eram "90% e 60% de conversao, 2 p.p. de
    # descolamento no juro, convencoes calibradas na mao e ainda nao medidas
    # contra a base". Os tres numeros mudaram e a afirmacao ficou falsa: os
    # cortes sao os quartis da base, e o de juro so foi calibrado porque o de
    # 2 p.p. acusava 82,3% das companhias.
    from valuation.qualidade import CONVERSAO_BOA, CONVERSAO_FRACA, JURO_DESCOLADO

    st.caption(
        f"Os cortes de conversão ({formatar(CONVERSAO_FRACA, 'pct')} e "
        f"{formatar(CONVERSAO_BOA, 'pct')}) e o de descolamento do juro "
        f"({formatar(JURO_DESCOLADO, 'pct')}) são os **quartis medidos** na "
        "base da CVM, e não convenção de mercado. Servem para dirigir atenção, "
        "não para decidir."
    )
    _safra_dos_percentis()



def _safra_dos_percentis() -> None:
    """A idade dos percentis que esta aba cita.

    ``referencias.BASE`` é um instantâneo **colado**: ela não se atualiza quando
    sai DFP nova. Sem este aviso, o app cita percentis de uma safra antiga com a
    mesma aparência de atual — que é o pior tipo de número desatualizado, o que
    não se anuncia.
    """
    from valuation import referencias

    safra = referencias.safra()
    if safra is None:
        return
    if safra.desatualizada:
        st.warning(safra.resumo())
    else:
        st.caption(safra.resumo())


COMPOSICOES = (
    ("1.01", "Ativo circulante", "O circulante é caixa ou estoque parado?"),
    ("2.01", "Passivo circulante", "O que vence no ano, e para quem."),
    ("2.01.04", "Dívida de curto prazo", "Empréstimo, debênture ou arrendamento."),
    ("2.02.01", "Dívida de longo prazo", "A mesma abertura, no prazo longo."),
)

LIQUIDEZ = [
    "Liquidez corrente",
    "Liquidez seca",
    "Liquidez imediata",
    "FCO / Passivo circulante",
    "Caixa / Divida de curto prazo",
    "Divida de curto prazo / Divida bruta",
]


def _liquidez(analise, dfs) -> None:
    """Liquidez, e a composição das contas que a explicam.

    Um índice de liquidez é um quociente entre dois totais, e dois totais
    iguais podem esconder situações opostas: circulante cheio de caixa não é o
    mesmo que circulante cheio de estoque. A composição vem ao lado por isso.
    """
    presentes = [i for i in LIQUIDEZ if i in analise.indicadores.index]
    if presentes:
        st.markdown("**Liquidez**")
        st.caption(
            "Não entram no fluxo descontado — o DCF não pergunta se a empresa "
            "paga a conta do mês que vem. Decidem se o valuation faz sentido: "
            "quem não atravessa o curto prazo não chega à perpetuidade."
        )
        liquidez = analise.indicadores.loc[presentes].copy()
        liquidez.columns = [str(c) for c in liquidez.columns]
        st.html(tabela_de_indicadores(liquidez, "numero"))
        st.caption(
            "**FCO / Passivo circulante** mede solvência sem depender de estoque "
            "virar caixa no prazo. Quando ele é alto e a liquidez corrente é "
            "baixa, as duas estão certas: a operação paga o que o balanço não cobre."
        )

    st.divider()
    st.markdown("**De que cada conta é feita**")
    ano = dfs.ano_base
    st.caption(f"Saldos de {ano}, em {dfs.unidade}. Só as subcontas diretas.")

    for codigo, titulo, explicacao in COMPOSICOES:
        composicao = dfs.composicao(codigo, ano)
        if composicao.empty:
            continue
        with st.expander(f"{titulo} ({codigo})"):
            st.caption(explicacao)
            # O indice e o codigo CVM; quem le a composicao quer o nome da
            # conta. O codigo continua a mao no expansor, no titulo.
            aberta = composicao.set_index("Conta")[["Valor", "% do total"]]
            aberta.columns = [f"Valor ({unidade_curta(dfs.unidade)})", "% do total"]
            st.html(
                tabela_de_indicadores(
                    aberta.iloc[:, :1], "moeda"
                ).replace("<th class=\"conta\">Indicador</th>", '<th class="conta">Conta</th>')
            )
            st.caption(
                "Participação: "
                + " · ".join(
                    f"**{nome}** {formatar(linha['% do total'], 'pct')}"
                    for nome, linha in aberta.iterrows()
                )
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

    _nao_recorrente(analise, dfs)


def _nao_recorrente(analise, dfs) -> None:
    """O que no resultado se repete, e o que aconteceu uma vez.

    Reversão de impairment, venda de ativo, ganho tributário e ganho judicial
    entram na DRE do SG&A para baixo. Podem fazer EBIT, LAIR e lucro líquido
    superarem o **lucro bruto** — contabilmente correto, economicamente
    enganoso, porque nada disso se repete.
    """
    from valuation.casos_especiais import ver_recorrente

    visao = ver_recorrente(analise)
    if visao is None or not visao.relevante:
        return

    st.markdown("#### O que se repete, e o que aconteceu uma vez")
    colunas = st.columns(3)
    with colunas[0]:
        metrica(
            "Margem EBIT reportada",
            float(visao.margem_ebit.dropna().iloc[-1]),
            "pct",
        )
    with colunas[1]:
        metrica(
            "Margem EBIT recorrente",
            float(visao.margem_ebit_recorrente.dropna().iloc[-1]),
            "pct",
        )
    with colunas[2]:
        metrica("Peso do não recorrente no EBIT", visao.peso, "pct")

    tabela = pd.DataFrame(
        {
            "EBIT reportado": visao.ebit,
            "(−) Impairment": -visao.impairment,
            "(−) Outras receitas operacionais": -visao.outras_receitas,
            "(−) Outras despesas operacionais": -visao.outras_despesas,
            "EBIT recorrente": visao.ebit_recorrente,
            "Equivalência patrimonial (à parte)": visao.equivalencia,
        }
    ).T
    tabela.columns = [str(a) for a in dfs.anos]
    st.dataframe(tabela_formatada(tabela, "moeda", dfs.unidade), width="stretch")

    anos = visao.anos_com_lucro_acima_do_bruto()
    if anos:
        st.warning(
            f"**O lucro líquido superou o lucro bruto em {', '.join(str(a) for a in anos)}.** "
            "Contabilmente é possível e não indica erro: reversão de impairment, "
            "venda de ativo, ganho tributário ou judicial entram abaixo do lucro "
            "bruto e podem superá-lo. O que não se pode é projetar a partir daí."
        )

    st.caption(
        "O ajuste vai nos **dois sentidos**: quando o item foi uma perda — "
        "impairment, tipicamente — a margem recorrente fica **maior** que a "
        "reportada. A equivalência patrimonial aparece à parte e não é subtraída: "
        "para uma holding ela é o negócio, para uma indústria é resultado de "
        "coligada que não gera caixa na controladora."
    )



def _conversao_em_dois_degraus(analise, qualidade) -> None:
    """As duas conversões lado a lado, e a ponte que explica a diferença.

    Uma conversão FCO/EBITDA baixa responde três perguntas de uma vez, e só uma
    delas é sobre a operação: o resultado virou caixa? o giro prendeu caixa?
    quanto saiu para imposto e juro? Medido no consolidado de 2024, **metade da
    base (190 de 371) tem CGO acima de 78% do EBITDA e FCO abaixo disso** — nelas
    a operação converte, e o consumo está abaixo dela.

    Por isso os dois números aparecem juntos, e a ponte fica ao lado: sem ela, o
    analista lê "converte 34%" e vai procurar receita fictícia onde o que há é
    dívida cara.
    """
    from valuation.qualidade import ponte_do_caixa

    operacional = (
        float(analise.mediana("Conversao operacional (CGO / EBITDA)"))
        if "Conversao operacional (CGO / EBITDA)" in analise.indicadores.index
        else float("nan")
    )
    if not (np.isfinite(qualidade.conversao_mediana) or np.isfinite(operacional)):
        return

    colunas = st.columns([1, 1, 2])
    with colunas[0]:
        metrica(
            "Conversão operacional CGO / EBITDA",
            operacional,
            "pct",
            ajuda="Caixa gerado pelas operações sobre EBITDA — antes de giro, "
            "imposto e juro. É esta que fala da operação.",
        )
    with colunas[1]:
        metrica(
            "Conversão final FCO / EBITDA",
            qualidade.conversao_mediana,
            "pct",
            ajuda="Depois de giro, imposto de renda e juros pagos.",
        )
    colunas[2].caption(
        "**As duas medem coisas diferentes, e a distância entre elas é o ponto.** "
        "Medido em 374 companhias de 2024: a mediana converte **105,9% do EBITDA "
        "em CGO** e só **59,2% em FCO**. Os 42,4 pontos de diferença são capital "
        "de giro, imposto e juro — e o **juro pago sozinho vale 25,8% do EBITDA "
        "na mediana** da base. FCO fraco com CGO alto não é operação que não "
        "gera caixa: é caixa que sai depois dela."
    )

    ponte = ponte_do_caixa(analise)
    if ponte is None:
        return

    with st.expander(f"A ponte, degrau a degrau — {analise.anos[-1]}"):
        unidade = analise.demonstracoes.unidade
        # Os degraus vão nas duas leituras, e em duas tabelas: o valor é moeda e
        # a fração é percentual, e uma tabela só teria de escolher um formato
        # para as duas colunas. Os subtotais da ponte — CGO e FCO — ganham peso.
        subtotais = {r for r, _, _ in ponte.degraus if r.startswith("=")}
        colunas = st.columns(2)
        with colunas[0]:
            st.html(
                tabela_financeira(
                    pd.DataFrame(
                        {analise.anos[-1]: [v for _, v, _ in ponte.degraus]},
                        index=[r for r, _, _ in ponte.degraus],
                    ),
                    subtotais,
                    "moeda",
                    unidade,
                )
            )
        with colunas[1]:
            st.html(
                tabela_financeira(
                    pd.DataFrame(
                        {"% do EBITDA": [f for _, _, f in ponte.degraus]},
                        index=[r for r, _, _ in ponte.degraus],
                    ),
                    subtotais,
                    "pct",
                )
            )
        st.caption(
            "`FCO = CGO + variação do giro + outros − imposto pago − juro pago`. "
            + (
                "A ponte fecha com o FCO publicado."
                if ponte.fecha
                else "**A ponte não fecha com o FCO publicado** — a companhia "
                "publica a DFC pelo método direto ou abre a seção de um jeito "
                "que estas linhas não reconstroem."
            )
        )


def _retorno(analise) -> None:
    conceito("roic", "O indicador mais importante do valuation")
    _formula_do_roic()

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



def _formula_do_roic() -> None:
    """Qual das várias contas de ROIC este número usou.

    Há vários jeitos de chegar no ROIC e eles não dão o mesmo número: o
    denominador pode ser capital de abertura, de fechamento ou médio; o
    numerador pode usar alíquota nominal ou efetiva; o capital investido pode
    incluir ou não o caixa. Mostrar 34,0% sem dizer qual dos jeitos foi usado
    obriga quem lê a confiar ou a refazer a conta.

    Fica **aberto**, e não atrás de um clique, porque é a primeira pergunta que
    um analista faz ao ver um ROIC que não bate com o do terminal dele.
    """
    from valuation.formulas import formula as buscar_formula

    verbete = buscar_formula("ROIC")
    if verbete is None:
        return
    st.markdown("**Como este ROIC é calculado**")
    st.markdown(verbete.formula)
    if verbete.convencao:
        with st.expander("As três escolhas que mudam o número"):
            st.markdown(verbete.convencao)


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

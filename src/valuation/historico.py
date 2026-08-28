"""Analise historica das demonstracoes importadas.

Duas entregas, que na pratica sao a mesma coisa vista de dois angulos:

1. **Entender o passado** -- margens, retorno sobre o capital, reinvestimento,
   ciclo de caixa e a decomposicao do retorno (DuPont e ROIC). E o material que
   um analista junior precisa ler antes de projetar qualquer coisa.
2. **Ancorar o futuro** -- as premissas iniciais do modelo saem daqui, e nao de
   um numero escolhido no ar. Projetar margem de 25% para quem entregou 18% nos
   ultimos cinco anos e uma decisao que precisa ser consciente, e so da para ser
   consciente se o historico estiver na tela.

Convencao importante: retornos usam **capital medio** do ano (saldo de abertura
mais saldo de fechamento, dividido por dois), como manda o material do CFA. Usar
o saldo final subestima o retorno de empresas que cresceram no ano, porque
compara o lucro do periodo inteiro com um capital que so existiu no fim.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .importacao import Demonstracoes
from .premissas import (
    ALIQUOTA_IR_BRASIL,
    PonteValor,
    PremissasCustoCapital,
    PremissasOperacionais,
)

DIAS_NO_ANO = 365


def dias_do_periodo(colunas) -> "pd.Series":
    """Quantos dias cada coluna cobre: 365 num exercicio, 91,25 num trimestre.

    **O prazo medio divide um saldo por uma venda diaria**, e a venda diaria sai
    da receita do periodo. Com a constante de 365 fixa, uma serie trimestral
    divide o saldo de estoque pela receita de tres meses e multiplica por um ano
    inteiro: medido na WEG, o ciclo lia **689 dias** contra os 166 do exercicio
    -- quase exatamente 4x, e com cara de numero plausivel, porque dia e dia.

    O rotulo da coluna e quem sabe a duracao, e ele ja e lido em
    ``series.periodo_do_rotulo``. 365/4 e nao os 89-91 dias reais do trimestre:
    assim quatro trimestres somam o ano, e o prazo trimestral fica comparavel com
    o anual em vez de oscilar com o calendario.
    """
    from .importacao.series import periodo_do_rotulo

    return pd.Series(
        [
            DIAS_NO_ANO / 4 if periodo_do_rotulo(c) else DIAS_NO_ANO
            for c in colunas
        ],
        index=list(colunas),
        dtype=float,
    )

# Teto do que se pode chamar de custo de divida corporativa no Brasil. A Selic
# oscilou entre 10% e 14% no periodo coberto pelos dados; um Kd acima disto quase
# sempre indica que o numerador nao e juro, e nao que a empresa paga tanto.
KD_MAXIMO_PLAUSIVEL = 0.25


def _media_movel_de_saldo(serie: pd.Series) -> pd.Series:
    """Saldo medio do ano: media entre abertura e fechamento.

    O primeiro ano fica ``NaN`` por falta de saldo de abertura -- e uma ausencia
    honesta, nao um numero inventado a partir de um unico ponto.
    """
    return (serie + serie.shift(1)) / 2


def _crescimento_no_par_certo(serie: pd.Series) -> pd.Series:
    """Crescimento contra o periodo comparavel, e nao contra a coluna a esquerda.

    Numa serie anual as duas coisas coincidem. Numa serie **trimestral** nao: a
    coluna a esquerda de 1T25 e 3T24, e a divisao entre as duas mede sazonalidade
    somada a um buraco -- o 4T24 nem esta na serie. O par que responde
    "cresceu?" e 3T25 contra 3T24.
    """
    from .importacao.series import anterior_comparavel

    pares = anterior_comparavel(serie.index)
    anterior = pd.Series(
        [
            serie.get(pares[coluna], float("nan")) if coluna in pares else float("nan")
            for coluna in serie.index
        ],
        index=serie.index,
        dtype="float64",
    )
    return serie / anterior - 1


def _divisao_segura(numerador: pd.Series, denominador: pd.Series) -> pd.Series:
    """Divide series tratando zero e negativo no denominador como indefinido."""
    denominador = denominador.where(denominador > 0)
    return numerador / denominador


@dataclass(frozen=True)
class AnaliseHistorica:
    """Indicadores historicos derivados das demonstracoes."""

    demonstracoes: Demonstracoes
    indicadores: pd.DataFrame

    @property
    def anos(self) -> list[int]:
        return list(self.indicadores.columns)

    def linha(self, nome: str) -> pd.Series:
        if nome not in self.indicadores.index:
            return pd.Series(np.nan, index=self.indicadores.columns, name=nome)
        return self.indicadores.loc[nome]

    def mediana(self, nome: str) -> float:
        """Mediana historica de um indicador, ignorando anos sem dado.

        A mediana e preferida a media para ancorar premissas: um unico ano
        atipico -- greve, aquisicao, pandemia -- desloca a media e nao deveria
        virar premissa de perpetuidade.
        """
        valores = self.linha(nome).replace([np.inf, -np.inf], np.nan).dropna()
        return float(valores.median()) if not valores.empty else float("nan")

    def ultimo(self, nome: str) -> float:
        valores = self.linha(nome).replace([np.inf, -np.inf], np.nan).dropna()
        return float(valores.iloc[-1]) if not valores.empty else float("nan")

    def resumo(self) -> pd.DataFrame:
        """Ultimo ano, mediana e desvio de cada indicador, lado a lado."""
        limpo = self.indicadores.replace([np.inf, -np.inf], np.nan)
        return pd.DataFrame(
            {
                "Ultimo ano": limpo.apply(
                    lambda l: l.dropna().iloc[-1] if l.notna().any() else np.nan, axis=1
                ),
                "Mediana": limpo.median(axis=1),
                "Minimo": limpo.min(axis=1),
                "Maximo": limpo.max(axis=1),
            }
        )

    def decomposicao_dupont(self) -> pd.DataFrame:
        """ROE decomposto em margem, giro do ativo e alavancagem.

        ``ROE = margem liquida x giro do ativo x alavancagem financeira``

        Serve para responder *por que* o retorno ao acionista e o que e: a
        empresa ganha por vender caro (margem), por girar rapido (giro) ou por
        usar dinheiro de terceiros (alavancagem)? Duas empresas com o mesmo ROE
        e composicao diferente sao negocios completamente diferentes.
        """
        return self.indicadores.loc[
            [
                "Margem liquida",
                "Giro do ativo",
                "Alavancagem financeira",
                "ROE",
            ]
        ].copy()

    def decomposicao_roic(self) -> pd.DataFrame:
        """ROIC decomposto em margem NOPAT e giro do capital investido.

        ``ROIC = margem NOPAT x giro do capital investido``

        O ROIC e mais informativo que o ROE para valuation porque nao depende da
        estrutura de capital: ele mede a qualidade da operacao, e e ele que,
        comparado ao WACC, diz se crescer cria ou destroi valor.
        """
        return self.indicadores.loc[
            [
                "Margem NOPAT",
                "Giro do capital investido",
                "ROIC",
                "Taxa de reinvestimento",
                "Crescimento fundamentado (reinvest. x ROIC)",
            ]
        ].copy()

    def ciclo_de_caixa(self) -> pd.DataFrame:
        """Prazos medios e ciclo de conversao de caixa, em dias."""
        return self.indicadores.loc[
            [
                "Prazo medio de recebimento (dias)",
                "Prazo medio de estoque (dias)",
                "Prazo medio de pagamento (dias)",
                "Ciclo de conversao de caixa (dias)",
            ]
        ].copy()


def analisar(demonstracoes: Demonstracoes) -> AnaliseHistorica:
    """Calcula os indicadores historicos a partir das demonstracoes importadas."""
    d = demonstracoes
    anos = d.anos
    if not anos:
        raise ValueError("As demonstracoes nao tem nenhum ano com dados.")

    receita = d.serie("receita_liquida")
    ebit = d.serie("ebit")
    ebitda = d.ebitda()
    lucro = d.serie("lucro_liquido")
    lair = d.serie("lucro_antes_impostos")
    impostos = d.serie("impostos")
    cpv = d.serie("custo_produtos_vendidos")
    # A duracao da coluna decide o multiplicador do prazo medio, e nao uma
    # constante: numa serie trimestral o denominador e a receita de tres meses.
    dias = dias_do_periodo(receita.index)
    depreciacao = d.serie("depreciacao_amortizacao")
    capex = d.serie("capex")
    ativo = d.serie("ativo_total")
    patrimonio = d.serie("patrimonio_liquido")
    giro_operacional = d.capital_giro()
    divida_bruta = d.divida_bruta()
    divida_liquida = d.divida_liquida()
    despesas_financeiras = d.serie("despesas_financeiras")

    # Aliquota efetiva do proprio historico. Costuma ficar abaixo dos 34%
    # nominais por incentivos, JCP e subvencoes -- e e ela, nao a nominal, que
    # descreve o caixa que a empresa realmente entrega.
    aliquota_efetiva = _divisao_segura(impostos, lair).clip(0, 1)
    aliquota_para_nopat = aliquota_efetiva.fillna(ALIQUOTA_IR_BRASIL)
    nopat = ebit * (1 - aliquota_para_nopat)

    capital_investido = divida_liquida.add(patrimonio, fill_value=0)
    capital_medio = _media_movel_de_saldo(capital_investido)
    patrimonio_medio = _media_movel_de_saldo(patrimonio)
    ativo_medio = _media_movel_de_saldo(ativo)
    divida_media = _media_movel_de_saldo(divida_bruta)

    crescimento = _crescimento_no_par_certo(receita)
    variacao_giro = giro_operacional.diff()
    reinvestimento = capex.sub(depreciacao, fill_value=0).add(variacao_giro, fill_value=0)

    roic = _divisao_segura(nopat, capital_medio)
    taxa_reinvestimento = _divisao_segura(reinvestimento, nopat)

    indicadores: dict[str, pd.Series] = {
        # Crescimento e margens
        "Crescimento da receita": crescimento,
        "Margem bruta": _divisao_segura(receita.sub(cpv, fill_value=0), receita),
        "Margem EBITDA": _divisao_segura(ebitda, receita),
        "Margem EBIT": _divisao_segura(ebit, receita),
        "Margem NOPAT": _divisao_segura(nopat, receita),
        "Margem liquida": _divisao_segura(lucro, receita),
        "Aliquota efetiva de IR": aliquota_efetiva,
        # Retorno e sua decomposicao
        "Giro do ativo": _divisao_segura(receita, ativo_medio),
        "Alavancagem financeira": _divisao_segura(ativo_medio, patrimonio_medio),
        "ROE": _divisao_segura(lucro, patrimonio_medio),
        "Giro do capital investido": _divisao_segura(receita, capital_medio),
        "ROIC": roic,
        # Reinvestimento
        "Capex / Receita": _divisao_segura(capex, receita),
        "Depreciacao / Receita": _divisao_segura(depreciacao, receita),
        "Capex / Depreciacao": _divisao_segura(capex, depreciacao),
        "Reinvestimento": reinvestimento,
        "Taxa de reinvestimento": taxa_reinvestimento,
        "Crescimento fundamentado (reinvest. x ROIC)": taxa_reinvestimento * roic,
        # Capital de giro e ciclo
        "Capital de giro / Receita": _divisao_segura(giro_operacional, receita),
        "Prazo medio de recebimento (dias)": _divisao_segura(
            d.serie("contas_receber") * dias, receita
        ),
        "Prazo medio de estoque (dias)": _divisao_segura(
            d.serie("estoques") * dias, cpv
        ),
        "Prazo medio de pagamento (dias)": _divisao_segura(
            d.serie("fornecedores") * dias, cpv
        ),
        # Estrutura de capital
        "Divida liquida / EBITDA": _divisao_segura(divida_liquida, ebitda),
        "Divida bruta / Patrimonio liquido": _divisao_segura(divida_bruta, patrimonio),
        "Custo da divida efetivo": _divisao_segura(despesas_financeiras, divida_media),
    }

    # Liquidez. Nao entra no DCF -- o fluxo descontado nao pergunta se a empresa
    # paga a conta do mes que vem --, mas decide se o valuation faz sentido:
    # empresa que nao atravessa o curto prazo nao chega a perpetuidade.
    circulante = d.serie("ativo_circulante")
    passivo_circulante = d.serie("passivo_circulante")
    caixa_total = d.serie("caixa_equivalentes").add(
        d.serie("aplicacoes_financeiras"), fill_value=0
    )
    if circulante.notna().any() and passivo_circulante.notna().any():
        indicadores["Liquidez corrente"] = _divisao_segura(
            circulante, passivo_circulante
        )
        indicadores["Liquidez seca"] = _divisao_segura(
            circulante.sub(d.serie("estoques"), fill_value=0), passivo_circulante
        )
        indicadores["Liquidez imediata"] = _divisao_segura(
            caixa_total, passivo_circulante
        )
    caixa_operacional = d.serie("fluxo_operacional")
    if caixa_operacional.notna().any() and passivo_circulante.notna().any():
        # Quanto do passivo de curto prazo um ano de operacao cobre. Diz mais
        # sobre solvencia que a liquidez corrente, que depende de estoque virar
        # caixa no prazo.
        indicadores["FCO / Passivo circulante"] = _divisao_segura(
            caixa_operacional, passivo_circulante
        )
    if divida_bruta.notna().any():
        curto = d.serie("divida_curto_prazo")
        indicadores["Divida de curto prazo / Divida bruta"] = _divisao_segura(
            curto, divida_bruta
        )
        if caixa_total.notna().any():
            # Vencimento do ano coberto pelo caixa de hoje: e o teste de
            # refinanciamento, que a divida liquida sozinha esconde.
            indicadores["Caixa / Divida de curto prazo"] = _divisao_segura(
                caixa_total, curto
            )

    # Contraprova de caixa. As linhas acima descrevem o regime de competencia;
    # as de baixo, quando a origem traz a DFC aberta, descrevem o mesmo fato
    # pelo caixa. Elas nao substituem nada -- a divergencia entre as duas e que
    # e a informacao: juro que aparece na DRE e nao no caixa foi capitalizado,
    # e lucro que nao vira caixa costuma estar preso no giro.
    fluxo_operacional = d.serie("fluxo_operacional")
    juros_pagos = d.serie("juros_pagos")
    giro_dfc = d.serie("variacao_capital_giro")
    dividendos = d.serie("dividendos_pagos")
    arrendamento = d.serie("arrendamento_curto_prazo").add(
        d.serie("arrendamento_longo_prazo"), fill_value=0
    )

    # A conversao para FCO responde tres perguntas de uma vez, e so uma delas e
    # sobre a operacao: o EBITDA virou caixa? o giro prendeu caixa? quanto foi
    # para imposto e juro? Um FCO fraco por juro alto nao diz o mesmo que um FCO
    # fraco por resultado que nao se realiza, e tratar os dois como o mesmo sinal
    # aponta o analista para o lugar errado.
    #
    # O CGO (``6.01.01``, "Caixa Gerado pelas Operacoes") e o EBITDA depois de
    # se realizar, **antes** de giro, imposto e juro. Medido no consolidado de
    # 2024: a mediana converte 105,9% do EBITDA em CGO e so 59,2% em FCO -- os
    # 42,4 p.p. de distancia sao a soma dos tres, com o **juro pago valendo
    # sozinho 25,8% do EBITDA na mediana** (P75 de 42,7%).
    caixa_das_operacoes = d.serie("caixa_das_operacoes")
    if caixa_das_operacoes.notna().any():
        indicadores["Conversao operacional (CGO / EBITDA)"] = _divisao_segura(
            caixa_das_operacoes, ebitda
        )
    if fluxo_operacional.notna().any():
        indicadores["Conversao de caixa (FCO / EBITDA)"] = _divisao_segura(
            fluxo_operacional, ebitda
        )
        indicadores["Capex / FCO"] = _divisao_segura(capex, fluxo_operacional)
        indicadores["Fluxo de caixa livre (FCO - capex)"] = fluxo_operacional.sub(
            capex, fill_value=0
        )
    if juros_pagos.notna().any():
        indicadores["Custo da divida pelo caixa"] = _divisao_segura(
            juros_pagos, divida_media
        )
    if giro_dfc.notna().any():
        # Sinal invertido para ler como as demais: positivo = giro consumiu caixa.
        indicadores["Investimento em giro (DFC) / Receita"] = _divisao_segura(
            -giro_dfc, receita
        )
    if dividendos.notna().any():
        indicadores["Payout (dividendos / lucro)"] = _divisao_segura(dividendos, lucro)
    if arrendamento.notna().any() and divida_bruta.notna().any():
        indicadores["Arrendamento / Divida bruta"] = _divisao_segura(
            arrendamento, divida_bruta
        )

    # Itens que nao se repetem. A CVM padroniza os codigos (3.04.03 impairment,
    # 3.04.04 outras receitas, 3.04.05 outras despesas), entao a separacao nao
    # depende de adivinhar rotulo. Medido na base: 165 de 172 companhias tem
    # algum, com peso mediano de 17,4% do EBIT -- projetar do EBIT reportado e,
    # nessa metade da base, projetar um evento como se fosse regime.
    nao_recorrente = (
        d.serie("impairment")
        .fillna(0)
        .add(d.serie("outras_receitas_operacionais").fillna(0), fill_value=0)
        .add(d.serie("outras_despesas_operacionais").fillna(0), fill_value=0)
    )
    if nao_recorrente.abs().sum() > 0:
        indicadores["Margem EBIT recorrente"] = _divisao_segura(
            ebit.sub(nao_recorrente, fill_value=0), receita
        )
        # A margem EBITDA recorrente existe porque e **ela** que a projecao usa.
        # O item nao recorrente entra na DRE do SG&A para baixo, entao contamina
        # o EBIT e o EBITDA por igual -- a D&A nao muda com ele, e a subtracao e
        # a mesma nos dois. Sugerir margem a partir da reportada projeta como
        # regime uma reversao de impairment ou uma venda de ativo.
        indicadores["Margem EBITDA recorrente"] = _divisao_segura(
            ebitda.sub(nao_recorrente, fill_value=0), receita
        )
        indicadores["Itens nao recorrentes / EBIT"] = _divisao_segura(
            nao_recorrente, ebit
        )

    # Ex-IFRS 16. Desde 2019 o aluguel saiu do resultado operacional e virou
    # depreciacao mais juros, entao o EBITDA subiu sem que nada tenha melhorado.
    # Em rede de farmacia ou de academia isso muda a leitura inteira: a margem da
    # Smart Fit e 48% reportada e 21,8% sem o aluguel.
    #
    # As duas visoes **nao se misturam**: a alavancagem ex-IFRS 16 usa a divida
    # sem arrendamento sobre o EBITDA sem aluguel. Cruzar as duas infla ou
    # esconde, dependendo do lado que se troca.
    aluguel = d.serie("arrendamento_principal_pago").add(
        d.serie("arrendamento_juros_pagos"), fill_value=0
    )
    if aluguel.notna().any():
        ebitda_ex = ebitda.sub(aluguel.fillna(0), fill_value=0)
        indicadores["Aluguel (arrendamento pago) / Receita"] = _divisao_segura(
            aluguel, receita
        )
        indicadores["Aluguel / EBITDA"] = _divisao_segura(aluguel, ebitda)
        indicadores["Margem EBITDA (ex-IFRS 16)"] = _divisao_segura(ebitda_ex, receita)
        juros_arrendamento = d.serie("arrendamento_juros_pagos")
        if juros_arrendamento.notna().any():
            indicadores["Margem EBIT (ex-IFRS 16)"] = _divisao_segura(
                ebit.sub(juros_arrendamento.fillna(0), fill_value=0), receita
            )
        if arrendamento.notna().any():
            divida_liquida_ex = divida_bruta.sub(
                arrendamento.fillna(0), fill_value=0
            ).sub(caixa_total, fill_value=0)
            indicadores["Divida liquida / EBITDA (ex-IFRS 16)"] = _divisao_segura(
                divida_liquida_ex, ebitda_ex
            )

    # **O ciclo exige recebimento e pagamento; o estoque pode ser zero.**
    # `fill_value=0` sozinho transforma "nao publicou" em "e zero", que e o
    # defeito mais caro que esta base ja teve. Medido no universo 2021-2025:
    # 413 das 418 companhias com ciclo publicam as tres pernas, e as outras 5
    # tem **so o recebimento** -- sem fornecedor, o ciclo delas saia inflado,
    # com mediana de 107 dias, e nada dizia que faltava a perna que o encurta.
    #
    # O estoque continua podendo ser zero porque **103 companhias o publicam
    # como zero**: prestadora de servico nao tem estoque, e ali o zero e o dado.
    pmr = indicadores["Prazo medio de recebimento (dias)"]
    pme = indicadores["Prazo medio de estoque (dias)"]
    pmp = indicadores["Prazo medio de pagamento (dias)"]
    indicadores["Ciclo de conversao de caixa (dias)"] = (
        pmr.add(pme, fill_value=0).sub(pmp, fill_value=0).where(pmr.notna() & pmp.notna())
    )

    tabela = pd.DataFrame(indicadores).T
    tabela.columns = anos
    return AnaliseHistorica(demonstracoes=demonstracoes, indicadores=tabela)


# As contas que respondem "como foi o trimestre". Sao poucas de proposito: a
# comparacao a/a existe para dar a leitura em um olhar, e uma tabela de quarenta
# linhas nao faz isso -- para essa ja existe a aba "Tudo".
CONTAS_DA_COMPARACAO = (
    ("receita_liquida", "Receita liquida"),
    ("lucro_bruto", "Lucro bruto"),
    ("ebit", "EBIT"),
    ("lucro_liquido", "Lucro liquido"),
)


def comparacao_ano_a_ano(demonstracoes) -> pd.DataFrame | None:
    """O ultimo periodo contra o **mesmo periodo do exercicio anterior**.

    Devolve ``None`` quando o par nao existe -- serie anual de um ano so, ou
    trimestral sem o exercicio anterior. Ausencia e resposta: uma tabela vazia
    com cabecalho sugere que a comparacao foi feita e nao achou nada.

    Numa serie trimestral o par e 3T25 contra 3T24, que e a leitura sem
    sazonalidade; numa anual e simplesmente o ano anterior. Quem decide e
    ``anterior_comparavel``, pelo rotulo da coluna.
    """
    from .importacao.series import anterior_comparavel, periodo_do_rotulo

    colunas = list(demonstracoes.valores.columns)
    if not colunas:
        return None
    atual = colunas[-1]
    anterior = anterior_comparavel(colunas).get(atual)
    if anterior is None:
        return None

    linhas = {}
    for chave, rotulo in CONTAS_DA_COMPARACAO:
        if chave not in demonstracoes.valores.index:
            continue
        agora = float(demonstracoes.valores.loc[chave, atual])
        antes = float(demonstracoes.valores.loc[chave, anterior])
        if not np.isfinite(agora) or not np.isfinite(antes):
            continue
        # Variacao percentual so tem sentido com base positiva: de -10 para -5 a
        # razao diz -50%, que se le como piora e e melhora. Nesses casos a
        # coluna fica vazia e os dois valores continuam la, que e o que permite
        # ler o caso sem que o app afirme um sinal errado.
        variacao = agora / antes - 1 if antes > 0 else float("nan")
        linhas[rotulo] = {atual: agora, anterior: antes, "Variacao": variacao}

    if not linhas:
        return None
    tabela = pd.DataFrame(linhas).T
    tabela.attrs["periodo_atual"] = atual
    tabela.attrs["periodo_anterior"] = anterior
    tabela.attrs["trimestral"] = periodo_do_rotulo(atual) is not None
    return tabela


def crescimento_composto(serie: pd.Series) -> float:
    """CAGR entre o primeiro e o ultimo ano com dado positivo."""
    valores = serie.dropna()
    valores = valores[valores > 0]
    if len(valores) < 2:
        return float("nan")
    periodos = len(valores) - 1
    return float((valores.iloc[-1] / valores.iloc[0]) ** (1 / periodos) - 1)


# ---------------------------------------------------------------------------
# Premissas sugeridas a partir do historico
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PremissasSugeridas:
    """Premissas iniciais derivadas do historico, com a justificativa de cada uma.

    As justificativas existem para que o app possa mostrar *de onde veio* cada
    numero. Uma premissa sugerida que o analista nao consegue explicar e pior do
    que uma premissa em branco.
    """

    operacionais: PremissasOperacionais
    ponte: PonteValor
    custo_capital: PremissasCustoCapital
    justificativas: dict[str, str]
    alertas: list[str]


def _convergir(inicio: float, fim: float, anos: int) -> list[float]:
    """Serie que caminha linearmente de ``inicio`` ate ``fim`` ao longo do horizonte.

    Empresas nao mantem para sempre o crescimento do ultimo ano; a convergencia
    ate uma taxa sustentavel e a forma padrao de projetar sem fingir precisao
    que nao existe.
    """
    if anos <= 1:
        return [fim]
    return [inicio + (fim - inicio) * (i / (anos - 1)) for i in range(anos)]


def sugerir_premissas(
    analise: AnaliseHistorica,
    horizonte: int = 5,
    crescimento_de_longo_prazo: float = 0.045,
    aliquota_ir: float = ALIQUOTA_IR_BRASIL,
) -> PremissasSugeridas:
    """Deriva premissas iniciais do historico, prontas para o analista revisar.

    O crescimento da receita converge do historico recente ate
    ``crescimento_de_longo_prazo``; margens e intensidade de capital partem da
    mediana historica, que resiste melhor a anos atipicos.
    """
    if horizonte < 1:
        raise ValueError("O horizonte precisa de ao menos um ano.")

    d = analise.demonstracoes
    justificativas: dict[str, str] = {}
    alertas: list[str] = []

    receita_base = d.valor("receita_liquida")
    if not np.isfinite(receita_base) or receita_base <= 0:
        raise ValueError(
            "Nao ha receita liquida no ultimo ano; sem ela nao da para projetar."
        )

    cagr = crescimento_composto(d.serie("receita_liquida"))
    crescimento_recente = analise.ultimo("Crescimento da receita")
    partida = next(
        (v for v in (cagr, crescimento_recente) if np.isfinite(v)),
        crescimento_de_longo_prazo,
    )
    # Teto de sanidade: partir de um crescimento explosivo do ultimo ano
    # projetaria para sempre uma anomalia pontual.
    if partida > 0.30:
        alertas.append(
            f"O crescimento historico de {partida:.1%} foi limitado a 30% na sugestao. "
            "Se o ritmo se sustenta, ajuste manualmente."
        )
        partida = 0.30
    if partida < 0:
        alertas.append(
            f"A receita encolheu {abs(partida):.1%} ao ano no historico. A sugestao "
            "parte dessa queda e converge para o crescimento de longo prazo."
        )

    crescimentos = _convergir(partida, crescimento_de_longo_prazo, horizonte)
    justificativas["crescimento_receita"] = (
        f"Parte de {partida:.1%} (CAGR historico da receita) e converge linearmente "
        f"ate {crescimento_de_longo_prazo:.1%} no ultimo ano projetado."
    )

    # A margem parte da **recorrente**, e nao da reportada. Impairment, venda de
    # ativo e ganho tributario entram na DRE do SG&A para baixo e contaminam
    # EBIT e EBITDA por igual; projeta-los como regime e projetar um evento para
    # sempre. Medido na base: 165 de 172 companhias tem item nao recorrente, com
    # peso mediano de 17,4% do EBIT. O ajuste vai nos dois sentidos -- quando o
    # item foi perda, a recorrente e **maior** que a reportada.
    margem_reportada = analise.mediana("Margem EBITDA")
    margem = analise.mediana("Margem EBITDA recorrente")
    if np.isfinite(margem) and np.isfinite(margem_reportada):
        diferenca = margem - margem_reportada
        justificativas["margem_ebitda"] = (
            f"Mediana historica da margem EBITDA **recorrente**: {margem:.1%}, "
            f"contra {margem_reportada:.1%} reportada ({diferenca:+.1%}). Tira "
            "impairment, outras receitas e outras despesas operacionais, que nao "
            "se repetem. Mantida constante no horizonte."
        )
        if abs(diferenca) >= 0.02:
            alertas.append(
                f"A margem EBITDA recorrente ({margem:.1%}) difere da reportada "
                f"({margem_reportada:.1%}) em {abs(diferenca):.1%}. A sugestao usa a "
                "recorrente; se o item se repete no seu negocio, volte para a reportada."
            )
    elif np.isfinite(margem_reportada):
        margem = margem_reportada
        justificativas["margem_ebitda"] = (
            f"Mediana historica de {margem:.1%}, mantida constante no horizonte. "
            "A companhia nao publica item nao recorrente, entao reportada e "
            "recorrente coincidem."
        )
    else:
        margem = 0.15
        alertas.append("Sem margem EBITDA historica; adotei 15% como ponto de partida.")

    depreciacao_pct = analise.mediana("Depreciacao / Receita")
    if not np.isfinite(depreciacao_pct):
        depreciacao_pct = 0.04
        alertas.append("Sem depreciacao historica; adotei 4% da receita.")
    else:
        justificativas["depreciacao_pct_receita"] = (
            f"Mediana historica de {depreciacao_pct:.1%} da receita."
        )

    capex_pct = analise.mediana("Capex / Receita")
    if not np.isfinite(capex_pct):
        capex_pct = depreciacao_pct
        alertas.append(
            "Sem capex historico; adotei capex igual a depreciacao (empresa apenas "
            "repondo o ativo, sem expansao)."
        )
    else:
        justificativas["capex_pct_receita"] = (
            f"Mediana historica de {capex_pct:.1%} da receita."
        )

    giro_pct = analise.mediana("Capital de giro / Receita")
    if not np.isfinite(giro_pct):
        giro_pct = 0.10
        alertas.append("Sem capital de giro historico; adotei 10% da receita.")
    else:
        justificativas["capital_giro_pct_receita"] = (
            f"Mediana historica de {giro_pct:.1%} da receita."
        )

    # Arrendamento so entra na projecao quando a companhia tem arrendamento
    # relevante. Sugerir zero para todo mundo seria poluir o modelo de quem nao
    # aluga nada; nao sugerir para quem aluga deixa o FCFF generoso demais.
    arrendamento = d.serie("arrendamento_curto_prazo").add(
        d.serie("arrendamento_longo_prazo"), fill_value=0
    )
    arrendamento_pct = None
    arrendamento_inicial = None
    if arrendamento.notna().any():
        razao = (arrendamento / d.serie("receita_liquida")).replace(
            [np.inf, -np.inf], np.nan
        ).dropna()
        if not razao.empty and float(razao.median()) > 0.02:
            arrendamento_pct = [float(razao.median())] * horizonte
            arrendamento_inicial = float(arrendamento.dropna().iloc[-1])
            justificativas["arrendamento_pct_receita"] = (
                f"Passivo de arrendamento mediano de {float(razao.median()):.1%} da "
                "receita. Crescendo com ela, a adicao anual vira saida de caixa: "
                "contrato novo de aluguel nao passa pelo capex, e sem esta linha o "
                "FCFF sairia maior do que e."
            )

    operacionais = PremissasOperacionais(
        receita_base=receita_base,
        crescimento_receita=crescimentos,
        margem_ebitda=[margem] * horizonte,
        depreciacao_pct_receita=[depreciacao_pct] * horizonte,
        capex_pct_receita=[capex_pct] * horizonte,
        capital_giro_pct_receita=[giro_pct] * horizonte,
        arrendamento_pct_receita=arrendamento_pct,
        arrendamento_inicial=arrendamento_inicial,
        capital_giro_inicial=(
            float(d.capital_giro().dropna().iloc[-1])
            if d.capital_giro().notna().any()
            else None
        ),
        ano_base=d.ano_base or 0,
    )

    # A quantidade de acoes vem da propria origem quando ela a informa (a CVM
    # publica emitidas e em tesouraria junto da DFP). Sem ela nao ha valor por
    # acao, e o numero que o usuario digitaria a mao erra o preco sem errar o
    # valor da empresa -- um engano que atravessa revisao sem ser notado.
    acoes = d.valor("acoes_em_circulacao")
    ponte = PonteValor(
        divida_bruta=float(np.nan_to_num(d.divida_bruta().dropna().iloc[-1]))
        if d.divida_bruta().notna().any()
        else 0.0,
        caixa=float(np.nan_to_num(d.valor("caixa_equivalentes"))),
        aplicacoes_financeiras=float(np.nan_to_num(d.valor("aplicacoes_financeiras"))),
        minoritarios=float(np.nan_to_num(d.valor("minoritarios"))),
        acoes_em_circulacao=float(acoes) if np.isfinite(acoes) and acoes > 0 else None,
    )
    justificativas["ponte"] = (
        f"Saldos do balanco de {d.ano_base}: divida bruta, caixa, aplicacoes e "
        "minoritarios."
        + (
            " Acoes em circulacao (emitidas menos tesouraria) vieram da origem."
            if ponte.acoes_em_circulacao
            else ""
        )
    )

    divida_pl = analise.ultimo("Divida bruta / Patrimonio liquido")
    if not np.isfinite(divida_pl):
        divida_pl = 0.0
    # O Kd vem do juro efetivamente pago quando a DFC esta disponivel, e nao da
    # despesa financeira da DRE.
    #
    # A linha 3.06.02 da CVM chama-se "Despesas Financeiras", mas nao e juro de
    # divida: junta variacao cambial, variacao monetaria e ajuste a valor
    # presente de todo o passivo. Na WEG de 2024 ela da R$ 1,72 bi contra R$ 3,6
    # bi de divida -- 48% ao ano --, enquanto o juro que saiu do caixa foi R$ 160
    # mi, ou 4,5%. Medido nas 467 companhias de 2024, a conta pela DRE produzia
    # Kd acima de 25% em 28% delas, com a Selic entre 10% e 14%: um WACC inflado
    # que derrubava o valor sem que nada avisasse.
    kd = analise.mediana("Custo da divida pelo caixa")
    kd_origem = "juros pagos na DFC sobre a divida media"
    if not np.isfinite(kd):
        kd = analise.mediana("Custo da divida efetivo")
        kd_origem = "despesas financeiras sobre a divida media"

    aliquota_hist = analise.mediana("Aliquota efetiva de IR")
    if np.isfinite(aliquota_hist) and abs(aliquota_hist - aliquota_ir) > 0.05:
        alertas.append(
            f"A aliquota efetiva historica ({aliquota_hist:.1%}) difere bastante da "
            f"nominal ({aliquota_ir:.1%}). Considere usar a efetiva na projecao."
        )

    # Acima de KD_MAXIMO_PLAUSIVEL a serie nao esta medindo custo de divida --
    # sobra de variacao cambial, divida media quase zero, ou os dois. Montar o Kd
    # sinteticamente e mais honesto que propagar o numero.
    kd_utilizavel = bool(np.isfinite(kd) and 0 < kd < KD_MAXIMO_PLAUSIVEL)
    if np.isfinite(kd) and not kd_utilizavel:
        alertas.append(
            f"O custo da divida calculado do historico deu {kd:.1%}, fora do que "
            "se paga por credito corporativo. Deixei o Kd para ser montado "
            "sinteticamente; confira a divida media e o resultado financeiro."
        )

    custo_capital = PremissasCustoCapital(
        beta_alavancado_setor=1.0,
        divida_pl_setor=divida_pl,
        divida_pl_alvo=divida_pl,
        custo_divida_brl=float(kd) if kd_utilizavel else None,
    )
    justificativas["custo_capital"] = (
        f"D/E de {divida_pl:.2f} vem do balanco do ultimo ano. "
        + (
            f"Kd de {kd:.1%} vem de {kd_origem}."
            if kd_utilizavel
            else "Kd sera montado sinteticamente (rf + risco-pais + spread)."
        )
        + " O beta precisa vir do setor: 1,0 e apenas um marcador."
    )
    alertas.append(
        "O beta sugerido (1,0) e um marcador. Escolha o setor na tela de custo de "
        "capital antes de defender o numero."
    )

    return PremissasSugeridas(
        operacionais=operacionais,
        ponte=ponte,
        custo_capital=custo_capital,
        justificativas=justificativas,
        alertas=alertas,
    )


# ---------------------------------------------------------------------------
# O ciclo de conversao de caixa, acompanhado ao longo do tempo
# ---------------------------------------------------------------------------

# O app calculava os quatro numeros e mostrava **um exercicio so**, num grafico
# de barras. Isso responde "qual e o ciclo hoje" e nao responde a pergunta que
# se faz de um ciclo: **para onde ele foi, e por causa de qual perna**.
#
# A decomposicao e exata por construcao -- ``CCC = PMR + PME - PMP`` --, entao a
# variacao tambem e: ``dCCC = dPMR + dPME - dPMP``, sem termo residual. E o
# mesmo tipo de ponte que o TSR e a conversao de caixa ja usam neste projeto, e
# pela mesma razao: a soma que fecha e o que separa diagnostico de impressao.

NOME_DO_CICLO = "Ciclo de conversao de caixa (dias)"
NOME_DO_PMR = "Prazo medio de recebimento (dias)"
NOME_DO_PME = "Prazo medio de estoque (dias)"
NOME_DO_PMP = "Prazo medio de pagamento (dias)"


@dataclass(frozen=True)
class PernaDoCiclo:
    """Uma perna do ciclo, do periodo de partida ao de chegada."""

    nome: str
    de: float
    para: float
    #: Quanto ela moveu o ciclo, **ja com o sinal da contribuicao**: alongar o
    #: prazo de pagamento encurta o ciclo, entao entra negativa.
    contribuicao: float

    @property
    def variacao(self) -> float:
        """A variacao da propria perna, sem inverter o sinal."""
        return self.para - self.de


@dataclass(frozen=True)
class PonteDoCiclo:
    """O que moveu o ciclo entre dois periodos, em dias e em caixa."""

    de: object
    para: object
    ciclo_de: float
    ciclo_para: float
    pernas: tuple[PernaDoCiclo, ...]
    receita_diaria: float
    unidade: str = ""

    @property
    def variacao(self) -> float:
        return self.ciclo_para - self.ciclo_de

    @property
    def fecha(self) -> bool:
        """A soma das pernas reproduz a variacao do ciclo?

        Tem de fechar por construcao. Nao fechar significa que alguma perna nao
        pode ser lida num dos periodos, e ai a ponte nao deve ser apresentada
        como se explicasse a variacao inteira.
        """
        soma = sum(p.contribuicao for p in self.pernas)
        return bool(np.isfinite(soma)) and abs(soma - self.variacao) < 0.5

    @property
    def caixa(self) -> float:
        """Quanto caixa a variacao do ciclo prendeu (positivo) ou liberou.

        E a variacao em dias vezes a **venda diaria do periodo de chegada**.
        Segurar a receita fixa e deliberado: misturar o efeito do ciclo com o do
        crescimento devolve um numero que nao responde nem a uma pergunta nem a
        outra. Empresa que cresce prende caixa no giro com o ciclo parado, e isso
        e outro assunto -- ``Capital de giro / Receita`` ja o diz.
        """
        return self.variacao * self.receita_diaria


def ponte_do_ciclo(analise, de=None, para=None) -> "PonteDoCiclo | None":
    """Decompoe a variacao do ciclo de caixa entre dois periodos.

    Por padrao compara o **primeiro periodo legivel com o ultimo**: e a leitura
    que responde "o ciclo desta empresa vem alongando?", que e a pergunta de
    quem acompanha. Devolve ``None`` quando nao ha dois periodos com ciclo -- e
    ausencia honesta, e nao uma ponte de um ponto so.
    """
    indicadores = analise.indicadores
    if NOME_DO_CICLO not in indicadores.index:
        return None

    ciclo = indicadores.loc[NOME_DO_CICLO].dropna()
    if len(ciclo) < 2:
        return None

    de = ciclo.index[0] if de is None else de
    para = ciclo.index[-1] if para is None else para
    if de not in ciclo.index or para not in ciclo.index or de == para:
        return None

    def _valor(nome: str, coluna) -> float:
        if nome not in indicadores.index:
            return float("nan")
        return float(indicadores.loc[nome, coluna])

    pernas = tuple(
        PernaDoCiclo(
            nome=nome,
            de=_valor(nome, de),
            para=_valor(nome, para),
            contribuicao=sinal * (_valor(nome, para) - _valor(nome, de)),
        )
        # O sinal e a informacao: alongar o pagamento ao fornecedor **encurta** o
        # ciclo, e uma ponte que mostrasse os tres com o mesmo sinal nao somaria
        # a variacao -- e nao somar e o que faz uma ponte deixar de ser ponte.
        for nome, sinal in ((NOME_DO_PMR, 1.0), (NOME_DO_PME, 1.0), (NOME_DO_PMP, -1.0))
    )

    receita = analise.demonstracoes.serie("receita_liquida")
    dias = float(dias_do_periodo([para]).iloc[0])
    receita_final = float(receita.get(para, float("nan")))
    diaria = receita_final / dias if np.isfinite(receita_final) else float("nan")

    return PonteDoCiclo(
        de=de,
        para=para,
        ciclo_de=float(ciclo.loc[de]),
        ciclo_para=float(ciclo.loc[para]),
        pernas=pernas,
        receita_diaria=diaria,
        unidade=getattr(analise.demonstracoes, "unidade", "") or "",
    )


def caixa_preso_no_ciclo(analise) -> pd.Series:
    """Quanto caixa o ciclo prende em cada periodo, na moeda da demonstracao.

    ``dias de ciclo x venda diaria`` -- a traducao que falta para quem le "o
    ciclo subiu 12 dias" e precisa decidir se isso importa. E o mesmo principio
    ja aplicado ao resto do app: "nao fecha" sem tamanho nao ajuda a decidir.
    """
    indicadores = analise.indicadores
    if NOME_DO_CICLO not in indicadores.index:
        return pd.Series(dtype="float64")
    ciclo = indicadores.loc[NOME_DO_CICLO]
    receita = analise.demonstracoes.serie("receita_liquida").reindex(ciclo.index)
    dias = dias_do_periodo(ciclo.index)
    return ciclo * (receita / dias)

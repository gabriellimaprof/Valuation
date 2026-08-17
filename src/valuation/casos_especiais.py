"""Ajustes contabeis que a analise de valuation exige e a contabilidade nao faz.

Tres situacoes em que os numeros publicados descrevem mal a economia da empresa:

* **P&D tratado como despesa.** A norma manda lancar pesquisa e desenvolvimento
  no resultado, mas economicamente e investimento: gera beneficio por varios
  anos. Sem o ajuste, empresas de tecnologia e farmaceuticas aparecem com lucro
  e capital investido subestimados, e com ROIC artificialmente alto.
* **Empresa ciclica avaliada no pico ou no fundo.** Projetar a partir da margem
  do ultimo ano de uma siderurgica ou de uma empresa de commodity e projetar um
  momento do ciclo como se fosse permanente.
* **Arrendamento operacional fora do balanco.** Depois do IFRS 16 / CPC 06 (R2)
  a maior parte ja esta no balanco, mas dados anteriores a 2019 e alguns
  reportes em US GAAP ainda deixam o compromisso de fora -- e ele e divida.

Cada funcao devolve o ajuste **e** o detalhamento de como chegou nele, porque
ajuste de valuation que nao pode ser auditado nao deveria ser usado.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .historico import AnaliseHistorica


@dataclass(frozen=True)
class AjustePD:
    """Resultado da capitalizacao de pesquisa e desenvolvimento."""

    ativo_de_pd: float
    amortizacao_do_ano: float
    ajuste_no_ebit: float
    detalhamento: pd.DataFrame

    @property
    def explicacao(self) -> str:
        return (
            f"O ativo de P&D de {self.ativo_de_pd:,.1f} passa a compor o capital "
            f"investido, e o EBIT sobe {self.ajuste_no_ebit:,.1f} (gasto do ano "
            f"devolvido ao lucro, menos a amortizacao de {self.amortizacao_do_ano:,.1f})."
        )


def capitalizar_pesquisa_desenvolvimento(
    gastos_por_ano: dict[int, float],
    vida_util: int = 5,
) -> AjustePD:
    """Converte P&D lancado como despesa em ativo amortizavel.

    Metodo do Damodaran: o gasto de cada um dos ultimos ``vida_util`` anos e
    tratado como investimento, amortizado linearmente. O ano corrente entra
    integralmente no ativo (ainda nao amortizado); o gasto de um ano atras entra
    com ``(vida_util - 1) / vida_util`` do valor, e assim por diante.

    ``gastos_por_ano`` mapeia ano para gasto de P&D daquele ano. Anos faltantes
    sao tratados como ausencia de informacao, nao como gasto zero, e o
    detalhamento mostra quais entraram.
    """
    if vida_util < 1:
        raise ValueError("vida_util deve ser de ao menos um ano.")
    if not gastos_por_ano:
        raise ValueError("Informe ao menos um ano de gasto com P&D.")

    anos = sorted(gastos_por_ano)
    ano_corrente = anos[-1]

    linhas = []
    ativo = 0.0
    amortizacao = 0.0
    for ano in anos:
        idade = ano_corrente - ano
        if idade > vida_util:
            continue
        gasto = float(gastos_por_ano[ano])
        parcela_nao_amortizada = max(0.0, (vida_util - idade) / vida_util)
        valor_no_ativo = gasto * parcela_nao_amortizada
        # O gasto do ano corrente ainda nao comecou a amortizar.
        amortizacao_do_ano = gasto / vida_util if idade > 0 else 0.0

        ativo += valor_no_ativo
        amortizacao += amortizacao_do_ano
        linhas.append(
            {
                "Ano": ano,
                "Gasto com P&D": gasto,
                "Idade (anos)": idade,
                "Parcela nao amortizada": parcela_nao_amortizada,
                "Valor no ativo": valor_no_ativo,
                "Amortizacao no ano corrente": amortizacao_do_ano,
            }
        )

    gasto_corrente = float(gastos_por_ano[ano_corrente])
    return AjustePD(
        ativo_de_pd=ativo,
        amortizacao_do_ano=amortizacao,
        ajuste_no_ebit=gasto_corrente - amortizacao,
        detalhamento=pd.DataFrame(linhas).set_index("Ano"),
    )


@dataclass(frozen=True)
class MargemNormalizada:
    """Margem de um setor ciclico, normalizada pelo ciclo inteiro."""

    margem_normalizada: float
    margem_do_ultimo_ano: float
    posicao_no_ciclo: str
    amplitude: float
    detalhamento: pd.Series

    @property
    def explicacao(self) -> str:
        return (
            f"A margem do ultimo ano ({self.margem_do_ultimo_ano:.1%}) esta no "
            f"{self.posicao_no_ciclo} do ciclo observado, cuja amplitude e de "
            f"{self.amplitude:.1%}. A mediana do periodo, {self.margem_normalizada:.1%}, "
            "descreve melhor um ano tipico."
        )


def normalizar_margem_ciclica(
    analise: AnaliseHistorica,
    indicador: str = "Margem EBITDA",
) -> MargemNormalizada:
    """Substitui a margem do ultimo ano pela mediana do ciclo observado.

    Empresas ciclicas nao tem uma margem: tem uma faixa. Projetar a partir do
    ultimo ano significa apostar que o momento atual do ciclo e o permanente --
    o erro classico de avaliar siderurgica no pico e varejo na crise.

    Quanto mais anos o historico cobrir, mais confiavel a normalizacao; com
    menos de um ciclo inteiro (tipicamente 5 a 7 anos) o resultado ainda carrega
    o vies do periodo escolhido.
    """
    serie = analise.linha(indicador).replace([np.inf, -np.inf], np.nan).dropna()
    if serie.empty:
        raise ValueError(f"Sem historico de '{indicador}' para normalizar.")
    if len(serie) < 3:
        raise ValueError(
            f"Normalizacao ciclica precisa de ao menos 3 anos de '{indicador}'; "
            f"ha {len(serie)}."
        )

    mediana = float(serie.median())
    ultimo = float(serie.iloc[-1])
    minimo, maximo = float(serie.min()), float(serie.max())
    amplitude = maximo - minimo

    if amplitude == 0:
        posicao = "meio"
    else:
        relativo = (ultimo - minimo) / amplitude
        posicao = "pico" if relativo > 0.66 else "fundo" if relativo < 0.33 else "meio"

    return MargemNormalizada(
        margem_normalizada=mediana,
        margem_do_ultimo_ano=ultimo,
        posicao_no_ciclo=posicao,
        amplitude=amplitude,
        detalhamento=serie,
    )


@dataclass(frozen=True)
class AjusteLeasing:
    """Capitalizacao de arrendamento operacional fora do balanco."""

    divida_equivalente: float
    ajuste_no_ebit: float
    detalhamento: pd.DataFrame

    @property
    def explicacao(self) -> str:
        return (
            f"O compromisso de aluguel equivale a uma divida de "
            f"{self.divida_equivalente:,.1f}, que entra na ponte de valor, e devolve "
            f"{self.ajuste_no_ebit:,.1f} ao EBIT (a parcela de juros embutida no aluguel)."
        )


def capitalizar_leasing_operacional(
    despesa_anual: float,
    prazo_anos: int,
    custo_divida: float,
) -> AjusteLeasing:
    """Converte aluguel operacional em divida equivalente e ajuste no EBIT.

    A divida equivalente e o valor presente dos alugueis futuros descontados ao
    custo da divida da empresa. O ajuste no EBIT devolve a parcela de juros
    embutida no aluguel, que economicamente e despesa financeira e nao
    operacional.

    Depois do IFRS 16 / CPC 06 (R2), vigente desde 2019, a maior parte dos
    arrendamentos ja esta reconhecida no balanco -- aplicar este ajuste sobre
    demonstracoes ja ajustadas contaria a mesma divida duas vezes.
    """
    if despesa_anual < 0:
        raise ValueError("despesa_anual deve ser positiva.")
    if prazo_anos < 1:
        raise ValueError("prazo_anos deve ser de ao menos um ano.")
    if custo_divida <= 0:
        raise ValueError("custo_divida deve ser positivo.")

    anos = np.arange(1, prazo_anos + 1)
    fatores = 1 / (1 + custo_divida) ** anos
    valores_presentes = despesa_anual * fatores
    divida = float(valores_presentes.sum())

    detalhamento = pd.DataFrame(
        {
            "Ano": anos,
            "Aluguel": despesa_anual,
            "Fator de desconto": fatores,
            "Valor presente": valores_presentes,
        }
    ).set_index("Ano")

    return AjusteLeasing(
        divida_equivalente=divida,
        ajuste_no_ebit=divida * custo_divida,
        detalhamento=detalhamento,
    )


# ---------------------------------------------------------------------------
# Arrendamento ja no balanco: o que o modelo faz com ele, e o que nao faz
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LeasingNoBalanco:
    """O passivo de arrendamento visto pelo modelo, com o buraco declarado.

    Depois do IFRS 16 o arrendamento **ja esta** na divida bruta, e o EBITDA ja
    e liquido dele -- as duas pontas batem, e a ponte EV -> equity esta certa.

    O que nao bate e a projecao. Aluguel novo nao passa por capex: assinar um
    contrato cria ativo de direito de uso e passivo de arrendamento sem tocar o
    fluxo de investimento. Numa rede de lojas que cresce abrindo pontos, o
    EBITDA sobe, o capex nao acompanha, o FCFF sai generoso -- e o passivo de
    arrendamento cresce todo ano sem que a ponte, congelada na data-base, saiba.
    O modelo superestima essa empresa, e o erro cresce com o horizonte.
    """

    saldo: float
    divida_bruta: float
    peso: float
    crescimento_anual: float
    crescimento_receita: float
    anos: int

    @property
    def relevante(self) -> bool:
        return np.isfinite(self.peso) and self.peso > 0.20

    @property
    def acompanha_a_receita(self) -> bool:
        """O arrendamento cresce junto com o negocio, e nao por evento isolado."""
        if not np.isfinite(self.crescimento_anual) or not np.isfinite(self.crescimento_receita):
            return False
        return self.crescimento_anual > 0 and self.crescimento_receita > 0

    def adicao_anual_implicita(self, crescimento_projetado: float) -> float:
        """Quanto o passivo cresceria por ano se acompanhasse o crescimento.

        Nao e previsao: e a ordem de grandeza do que a projecao ignora, para
        quem precisa decidir se ignorar importa.
        """
        if not np.isfinite(self.saldo) or not np.isfinite(crescimento_projetado):
            return float("nan")
        return self.saldo * crescimento_projetado

    @property
    def explicacao(self) -> str:
        if not np.isfinite(self.peso):
            return "Não há passivo de arrendamento reconhecido nas demonstrações."
        texto = (
            f"O arrendamento é {self.peso:.1%} da dívida bruta "
            f"({self.saldo:,.1f} de {self.divida_bruta:,.1f})."
        )
        if np.isfinite(self.crescimento_anual) and self.anos > 1:
            texto += (
                f" No período apurado cresceu {self.crescimento_anual:.1%} ao ano, "
                f"contra {self.crescimento_receita:.1%} da receita."
            )
        return texto


def ler_leasing(analise: AnaliseHistorica) -> LeasingNoBalanco:
    """Le o passivo de arrendamento e como ele se moveu no historico.

    Devolve ``NaN`` no peso quando a companhia nao reconhece arrendamento
    separado -- ausencia de conta e ausencia de informacao, nao zero.
    """
    d = analise.demonstracoes
    curto = d.serie("arrendamento_curto_prazo")
    longo = d.serie("arrendamento_longo_prazo")
    arrendamento = curto.add(longo, fill_value=0).dropna()

    divida = d.serie("divida_bruta").dropna()
    if divida.empty:
        divida = (
            d.serie("divida_curto_prazo").add(d.serie("divida_longo_prazo"), fill_value=0).dropna()
        )

    if arrendamento.empty or divida.empty:
        return LeasingNoBalanco(
            saldo=float("nan"),
            divida_bruta=float(divida.iloc[-1]) if not divida.empty else float("nan"),
            peso=float("nan"),
            crescimento_anual=float("nan"),
            crescimento_receita=float("nan"),
            anos=0,
        )

    saldo = float(arrendamento.iloc[-1])
    divida_bruta = float(divida.iloc[-1])
    receita = d.serie("receita_liquida").dropna()

    return LeasingNoBalanco(
        saldo=saldo,
        divida_bruta=divida_bruta,
        peso=saldo / divida_bruta if divida_bruta else float("nan"),
        crescimento_anual=_taxa_anual(arrendamento),
        crescimento_receita=_taxa_anual(receita),
        anos=len(arrendamento),
    )


def _taxa_anual(serie: pd.Series) -> float:
    """Crescimento composto entre a primeira e a ultima observacao."""
    valores = serie.dropna()
    if len(valores) < 2:
        return float("nan")
    inicio, fim = float(valores.iloc[0]), float(valores.iloc[-1])
    periodos = len(valores) - 1
    if inicio <= 0 or fim <= 0:
        return float("nan")
    return (fim / inicio) ** (1 / periodos) - 1


# ---------------------------------------------------------------------------
# Ler a DRE como era antes do IFRS 16
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VisaoExIFRS16:
    """EBITDA, EBIT e divida como seriam sem o IFRS 16.

    **Por que alguem quer isso.** Ate 2018 o aluguel era despesa operacional e
    entrava no EBITDA. Desde o IFRS 16 / CPC 06 (R2) ele virou depreciacao de
    direito de uso mais juros, entao **o EBITDA subiu sem que nada tenha
    melhorado no negocio**. Numa rede de farmacias isso e enorme: medido na
    Raia Drogasil de 2024, a margem EBITDA e 10,8% reportada e 6,5% ex-IFRS 16.
    Na Pague Menos, 8,6% contra 3,3%.

    Para quem compara com o historico anterior a 2019, com par que reporta em
    US GAAP (onde o aluguel operacional continua no resultado) ou simplesmente
    quer saber quanto caixa sobra depois de pagar o ponto, a visao ex-IFRS 16 e
    a que responde.

    **A regra que nao pode ser quebrada:** as duas visoes nao se misturam. Ou se
    usa EBITDA reportado com a divida que inclui arrendamento, ou EBITDA
    ex-IFRS 16 com a divida que o exclui. Cruzar as duas -- divida cheia sobre
    EBITDA sem aluguel -- infla a alavancagem; ao contrario, esconde.

    Como cada numero e obtido
    -------------------------

    ``aluguel`` e o desembolso do ano (principal + juros), que e o que mais se
    parece com o aluguel que existia na DRE::

        EBITDA_ex = EBITDA - aluguel
        EBIT_ex   = EBIT - juros
        divida_ex = divida bruta - passivo de arrendamento

    O ``EBIT`` ja desconta a depreciacao do direito de uso, que em regime
    estacionario se aproxima do principal; o que sobra para tirar e o juro. A
    depreciacao do direito de uso viria mais direto, mas so 10% das companhias
    a publicam em linha propria -- esparsa demais para sustentar a conta.
    """

    ebitda: pd.Series
    ebitda_reportado: pd.Series
    ebit: pd.Series
    ebit_reportado: pd.Series
    receita: pd.Series
    aluguel: pd.Series
    principal: pd.Series
    juros: pd.Series
    divida_bruta: pd.Series
    divida_bruta_reportada: pd.Series
    caixa: pd.Series
    tem_juros: bool

    @property
    def margem_ebitda(self) -> pd.Series:
        return self.ebitda / self.receita

    @property
    def margem_ebitda_reportada(self) -> pd.Series:
        return self.ebitda_reportado / self.receita

    @property
    def margem_ebit(self) -> pd.Series:
        return self.ebit / self.receita

    @property
    def divida_liquida(self) -> pd.Series:
        return self.divida_bruta - self.caixa

    @property
    def alavancagem(self) -> pd.Series:
        """Divida liquida sem arrendamento sobre EBITDA sem aluguel."""
        return self.divida_liquida / self.ebitda.replace(0, np.nan)

    @property
    def alavancagem_reportada(self) -> pd.Series:
        return (self.divida_bruta_reportada - self.caixa) / self.ebitda_reportado.replace(
            0, np.nan
        )

    @property
    def peso_do_aluguel(self) -> float:
        """Quanto do EBITDA reportado e, na verdade, aluguel."""
        aluguel = self.aluguel.dropna()
        ebitda = self.ebitda_reportado.reindex(aluguel.index).dropna()
        if ebitda.empty or not (ebitda > 0).any():
            return float("nan")
        return float((aluguel / ebitda.replace(0, np.nan)).median())

    @property
    def relevante(self) -> bool:
        """Vale a pena olhar as duas visoes nesta companhia?"""
        peso = self.peso_do_aluguel
        return bool(np.isfinite(peso) and peso >= 0.10)

    @property
    def ressalva(self) -> str:
        if self.tem_juros:
            return ""
        return (
            "Esta companhia não publica os juros do arrendamento em linha própria, "
            "então o aluguel usado aqui é só o principal. O ajuste é um **piso**: "
            "o EBITDA ex-IFRS 16 real é menor do que o mostrado."
        )

    @property
    def explicacao(self) -> str:
        peso = self.peso_do_aluguel
        if not np.isfinite(peso):
            return "Não há desembolso de arrendamento na DFC para montar a visão ex-IFRS 16."
        return (
            f"O aluguel consome {peso:.1%} do EBITDA reportado. Sem ele, a margem "
            f"EBITDA cai de {self.margem_ebitda_reportada.dropna().iloc[-1]:.1%} para "
            f"{self.margem_ebitda.dropna().iloc[-1]:.1%}."
        )


def ver_ex_ifrs16(analise: AnaliseHistorica) -> VisaoExIFRS16 | None:
    """Monta a visao ex-IFRS 16, ou ``None`` se a DFC nao traz o desembolso.

    Devolver ``None`` e melhor do que devolver uma visao igual a reportada:
    "sem arrendamento no caixa" e "arrendamento zero" sao coisas diferentes, e
    so a primeira e verdade aqui.
    """
    d = analise.demonstracoes
    principal = d.serie("arrendamento_principal_pago")
    juros = d.serie("arrendamento_juros_pagos")
    if principal.dropna().empty and juros.dropna().empty:
        return None

    aluguel = principal.fillna(0).add(juros.fillna(0), fill_value=0)
    aluguel = aluguel.where(aluguel != 0)

    ebitda = d.ebitda()
    ebit = d.serie("ebit")
    arrendamento = d.serie("arrendamento_curto_prazo").add(
        d.serie("arrendamento_longo_prazo"), fill_value=0
    )
    divida = d.divida_bruta()
    caixa = d.serie("caixa_equivalentes").add(
        d.serie("aplicacoes_financeiras"), fill_value=0
    )

    return VisaoExIFRS16(
        ebitda=ebitda.sub(aluguel.fillna(0), fill_value=0),
        ebitda_reportado=ebitda,
        ebit=ebit.sub(juros.fillna(0), fill_value=0),
        ebit_reportado=ebit,
        receita=d.serie("receita_liquida"),
        aluguel=aluguel,
        principal=principal,
        juros=juros,
        divida_bruta=divida.sub(arrendamento.fillna(0), fill_value=0),
        divida_bruta_reportada=divida,
        caixa=caixa,
        tem_juros=bool(juros.dropna().any()),
    )


def empresa_ex_ifrs16(empresa, visao: VisaoExIFRS16):
    """Converte um valuation inteiro para a base pre-IFRS 16, coerentemente.

    Nao basta baixar a margem: o aluguel volta a ser custo operacional **e** o
    passivo de arrendamento sai da ponte. Fazer so metade e o erro que a tela
    avisa o tempo todo -- margem sem aluguel com divida que inclui arrendamento
    conta o mesmo compromisso duas vezes.

    O que muda, e por que
    ---------------------

    * ``margem_ebitda`` cai pelo aluguel sobre receita: ele volta ao resultado.
    * ``depreciacao_pct_receita`` cai pelo **principal** sobre receita. Sai a
      depreciacao do direito de uso, que em regime estacionario se aproxima do
      principal -- e a mesma aproximacao que sustenta ``EBIT_ex = EBIT - juros``.
    * ``arrendamento_pct_receita`` e **zerado**: antes do IFRS 16 nao ha passivo
      para crescer, o aluguel ja saiu como despesa.
    * ``ponte.divida_bruta`` perde o passivo de arrendamento.

    O que **nao** muda, e precisa de olho: ``divida_pl_alvo`` do custo de
    capital. Tirar arrendamento da divida muda a estrutura de capital de fato, e
    quem escolheu o D/E alvo escolheu com a divida cheia na cabeca. O ajuste
    fica com quem tem o julgamento.

    As duas avaliacoes **nao coincidem**, e isso nao e defeito
    ----------------------------------------------------------

    Escrevi aqui, antes de medir, que elas deveriam ficar proximas -- afinal o
    IFRS 16 e mudanca de apresentacao. Nao ficam, e a razao e economica.

    O passivo de arrendamento no balanco e o valor presente dos alugueis do
    **prazo contratado**. Uma rede de lojas nao para de pagar aluguel quando os
    contratos vencem: renova. Na base pos-IFRS 16 o modelo desconta esse passivo
    finito e nunca mais cobra aluguel; na base pre-IFRS 16 o aluguel sai do
    fluxo **para sempre**, inclusive na perpetuidade.

    Medido num caso sem crescimento, aluguel de 10 ao ano e passivo de 37,9
    (cinco anos a 10%): o valor presente perpetuo do aluguel apos imposto ao
    WACC e **49,4**. A diferenca de 11,5 e exatamente o que a leitura
    pos-IFRS 16 ganha por supor que o aluguel acaba.

    A direcao do efeito depende de crescimento e da relacao entre o passivo
    contratado e o aluguel perpetuo, entao nao ha regra de sinal -- ha duas
    leituras, e a distancia entre elas mede quanto do valor vem da hipotese de
    que o aluguel termina.
    """
    from dataclasses import replace as _replace

    operacionais = empresa.operacionais
    if operacionais is None:
        raise ValueError("Sem premissas operacionais nao ha o que converter.")

    # O deslocamento da margem vem da **mediana das duas series de margem**, e
    # nao da mediana da razao aluguel/receita. Sao numeros diferentes quando os
    # anos bons e ruins nao coincidem, e o primeiro e o que de fato se observou.
    receita = visao.receita.replace(0, np.nan)
    margens = (visao.margem_ebitda_reportada - visao.margem_ebitda).dropna()
    aluguel_pct = float(margens.median()) if not margens.empty else float("nan")
    principal_pct = float((visao.principal / receita).dropna().median())
    if not np.isfinite(aluguel_pct):
        raise ValueError("Sem aluguel medido, a conversao nao tem de onde sair.")
    if not np.isfinite(principal_pct):
        principal_pct = aluguel_pct

    arrendamento = visao.divida_bruta_reportada - visao.divida_bruta
    saldo = float(arrendamento.dropna().iloc[-1]) if arrendamento.dropna().any() else 0.0

    novas_margens = [m - aluguel_pct for m in operacionais.margem_ebitda]
    novas_depreciacoes = [
        max(d - principal_pct, 0.0) for d in operacionais.depreciacao_pct_receita
    ]

    return _replace(
        empresa,
        operacionais=_replace(
            operacionais,
            margem_ebitda=novas_margens,
            depreciacao_pct_receita=novas_depreciacoes,
            arrendamento_pct_receita=None,
            arrendamento_inicial=None,
        ),
        ponte=_replace(
            empresa.ponte,
            divida_bruta=max(empresa.ponte.divida_bruta - saldo, 0.0),
        ),
    )


def aluguel_perpetuo(visao: VisaoExIFRS16, wacc: float, aliquota: float = 0.34) -> float:
    """Valor presente do aluguel apos imposto, cobrado para sempre.

    E o numero que falta na leitura pos-IFRS 16. O balanco traz o passivo do
    **prazo contratado**; quem aluga ponto comercial renova, e o compromisso
    economico nao termina com o contrato. Comparar os dois diz quanto de valor
    o modelo ganha por supor que o aluguel acaba.
    """
    aluguel = visao.aluguel.dropna()
    if aluguel.empty or not np.isfinite(wacc) or wacc <= 0:
        return float("nan")
    return float(aluguel.iloc[-1]) * (1 - aliquota) / wacc


def passivo_de_arrendamento(visao: VisaoExIFRS16) -> float:
    """O passivo contratado que o balanco reconhece, no ultimo ano."""
    diferenca = (visao.divida_bruta_reportada - visao.divida_bruta).dropna()
    return float(diferenca.iloc[-1]) if not diferenca.empty else float("nan")


# ---------------------------------------------------------------------------
# O que se repete, e o que aconteceu uma vez
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResultadoRecorrente:
    """EBIT com e sem os itens que nao se repetem.

    **Por que isso importa mais do que parece.** Reversao de impairment, ganho
    na venda de ativo, credito tributario e ganho judicial entram na DRE do
    SG&A para baixo. Eles podem fazer EBIT, LAIR e lucro liquido superarem o
    **lucro bruto** -- o que e contabilmente correto e economicamente enganoso,
    porque nada disso se repete no ano seguinte.

    Medido na base de 2024: **165 de 172 companhias tem item nao recorrente
    diferente de zero**, com peso mediano de 17,4% do EBIT e acima de 20% em
    quase metade delas. Projetar a partir do EBIT reportado, nesses casos, e
    projetar um evento como se fosse regime.

    De onde os numeros saem
    -----------------------

    A CVM padroniza os codigos, entao nao ha adivinhacao de rotulo::

        3.04.03  Perdas pela nao recuperabilidade de ativos (impairment)
        3.04.04  Outras receitas operacionais
        3.04.05  Outras despesas operacionais

        EBIT recorrente = EBIT - (3.04.03 + 3.04.04 + 3.04.05)

    Com o **sinal publicado**, e nao com magnitude: reversao de impairment entra
    positiva, perda entra negativa, e a subtracao cuida dos dois casos.

    A equivalencia patrimonial (``3.04.06``) fica **de fora da subtracao**, de
    proposito. Para uma holding ela e o negocio; para uma industria e resultado
    de coligada que nao gera caixa na controladora. Excluir por padrao acertaria
    numa e erraria na outra, entao ela aparece separada e quem le decide.
    """

    receita: pd.Series
    ebit: pd.Series
    ebit_recorrente: pd.Series
    impairment: pd.Series
    outras_receitas: pd.Series
    outras_despesas: pd.Series
    equivalencia: pd.Series
    lucro_bruto: pd.Series
    lucro_liquido: pd.Series

    @property
    def nao_recorrente(self) -> pd.Series:
        return self.ebit - self.ebit_recorrente

    @property
    def margem_ebit(self) -> pd.Series:
        return self.ebit / self.receita

    @property
    def margem_ebit_recorrente(self) -> pd.Series:
        return self.ebit_recorrente / self.receita

    @property
    def peso(self) -> float:
        """Quanto do EBIT, na mediana, veio do que nao se repete."""
        ebit = self.ebit.replace(0, np.nan)
        razao = (self.nao_recorrente / ebit).replace([np.inf, -np.inf], np.nan).dropna()
        return float(razao.abs().median()) if not razao.empty else float("nan")

    @property
    def relevante(self) -> bool:
        return bool(np.isfinite(self.peso) and self.peso >= 0.10)

    def anos_com_lucro_acima_do_bruto(self) -> list[int]:
        """Anos em que o lucro liquido superou o lucro bruto.

        Nao e erro contabil -- pode ser reversao de impairment, venda de ativo,
        ganho tributario ou judicial. E o sinal mais visivel de que o resultado
        daquele ano nao veio da operacao.
        """
        comparavel = pd.concat(
            [self.lucro_liquido, self.lucro_bruto], axis=1, keys=["ll", "bruto"]
        ).dropna()
        acima = comparavel[comparavel["ll"] > comparavel["bruto"]]
        return [int(a) for a in acima.index]

    @property
    def explicacao(self) -> str:
        if not np.isfinite(self.peso):
            return "Não há itens não recorrentes destacados na DRE."
        ultimo = self.nao_recorrente.dropna()
        if ultimo.empty:
            return "Não há itens não recorrentes destacados na DRE."
        return (
            f"Itens não recorrentes respondem por {self.peso:.1%} do EBIT na "
            f"mediana do período. No último ano foram {float(ultimo.iloc[-1]):,.1f}, "
            f"contra EBIT de {float(self.ebit.dropna().iloc[-1]):,.1f}."
        )


def ver_recorrente(analise: AnaliseHistorica) -> ResultadoRecorrente | None:
    """Separa o EBIT do que nao se repete, ou ``None`` sem EBIT para separar."""
    d = analise.demonstracoes
    ebit = d.serie("ebit")
    if ebit.dropna().empty:
        return None

    impairment = d.serie("impairment")
    outras_receitas = d.serie("outras_receitas_operacionais")
    outras_despesas = d.serie("outras_despesas_operacionais")

    nao_recorrente = (
        impairment.fillna(0)
        .add(outras_receitas.fillna(0), fill_value=0)
        .add(outras_despesas.fillna(0), fill_value=0)
    )
    return ResultadoRecorrente(
        receita=d.serie("receita_liquida"),
        ebit=ebit,
        ebit_recorrente=ebit.sub(nao_recorrente, fill_value=0),
        impairment=impairment,
        outras_receitas=outras_receitas,
        outras_despesas=outras_despesas,
        equivalencia=d.serie("equivalencia_patrimonial"),
        lucro_bruto=d.serie("lucro_bruto"),
        lucro_liquido=d.serie("lucro_liquido"),
    )

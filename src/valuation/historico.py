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


def _media_movel_de_saldo(serie: pd.Series) -> pd.Series:
    """Saldo medio do ano: media entre abertura e fechamento.

    O primeiro ano fica ``NaN`` por falta de saldo de abertura -- e uma ausencia
    honesta, nao um numero inventado a partir de um unico ponto.
    """
    return (serie + serie.shift(1)) / 2


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

    crescimento = receita / receita.shift(1) - 1
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
            d.serie("contas_receber") * DIAS_NO_ANO, receita
        ),
        "Prazo medio de estoque (dias)": _divisao_segura(
            d.serie("estoques") * DIAS_NO_ANO, cpv
        ),
        "Prazo medio de pagamento (dias)": _divisao_segura(
            d.serie("fornecedores") * DIAS_NO_ANO, cpv
        ),
        # Estrutura de capital
        "Divida liquida / EBITDA": _divisao_segura(divida_liquida, ebitda),
        "Divida bruta / Patrimonio liquido": _divisao_segura(divida_bruta, patrimonio),
        "Custo da divida efetivo": _divisao_segura(despesas_financeiras, divida_media),
    }

    indicadores["Ciclo de conversao de caixa (dias)"] = (
        indicadores["Prazo medio de recebimento (dias)"]
        .add(indicadores["Prazo medio de estoque (dias)"], fill_value=0)
        .sub(indicadores["Prazo medio de pagamento (dias)"], fill_value=0)
    )

    tabela = pd.DataFrame(indicadores).T
    tabela.columns = anos
    return AnaliseHistorica(demonstracoes=demonstracoes, indicadores=tabela)


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

    margem = analise.mediana("Margem EBITDA")
    if not np.isfinite(margem):
        margem = 0.15
        alertas.append("Sem margem EBITDA historica; adotei 15% como ponto de partida.")
    else:
        justificativas["margem_ebitda"] = (
            f"Mediana historica de {margem:.1%}, mantida constante no horizonte."
        )

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

    operacionais = PremissasOperacionais(
        receita_base=receita_base,
        crescimento_receita=crescimentos,
        margem_ebitda=[margem] * horizonte,
        depreciacao_pct_receita=[depreciacao_pct] * horizonte,
        capex_pct_receita=[capex_pct] * horizonte,
        capital_giro_pct_receita=[giro_pct] * horizonte,
        capital_giro_inicial=(
            float(d.capital_giro().dropna().iloc[-1])
            if d.capital_giro().notna().any()
            else None
        ),
        ano_base=d.ano_base or 0,
    )

    ponte = PonteValor(
        divida_bruta=float(np.nan_to_num(d.divida_bruta().dropna().iloc[-1]))
        if d.divida_bruta().notna().any()
        else 0.0,
        caixa=float(np.nan_to_num(d.valor("caixa_equivalentes"))),
        aplicacoes_financeiras=float(np.nan_to_num(d.valor("aplicacoes_financeiras"))),
        minoritarios=float(np.nan_to_num(d.valor("minoritarios"))),
    )
    justificativas["ponte"] = (
        f"Saldos do balanco de {d.ano_base}: divida bruta, caixa, aplicacoes e "
        "minoritarios."
    )

    divida_pl = analise.ultimo("Divida bruta / Patrimonio liquido")
    if not np.isfinite(divida_pl):
        divida_pl = 0.0
    kd = analise.mediana("Custo da divida efetivo")
    aliquota_hist = analise.mediana("Aliquota efetiva de IR")
    if np.isfinite(aliquota_hist) and abs(aliquota_hist - aliquota_ir) > 0.05:
        alertas.append(
            f"A aliquota efetiva historica ({aliquota_hist:.1%}) difere bastante da "
            f"nominal ({aliquota_ir:.1%}). Considere usar a efetiva na projecao."
        )

    custo_capital = PremissasCustoCapital(
        beta_alavancado_setor=1.0,
        divida_pl_setor=divida_pl,
        divida_pl_alvo=divida_pl,
        custo_divida_brl=float(kd) if np.isfinite(kd) and 0 < kd < 0.5 else None,
    )
    justificativas["custo_capital"] = (
        f"D/E de {divida_pl:.2f} vem do balanco do ultimo ano. "
        + (
            f"Kd de {kd:.1%} vem das despesas financeiras sobre a divida media."
            if np.isfinite(kd) and 0 < kd < 0.5
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

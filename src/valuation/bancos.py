"""Reconhecer um banco, e sugerir as premissas que ele pede.

O motor de FCFF/WACC não se aplica a instituição financeira, e o app precisa
saber disso **antes** de mostrar um número. Este módulo faz as duas pontas: diz
se a companhia é do plano financeiro, e monta a partir do histórico dela as
premissas do modelo de lucro residual (ver ``lucro_residual``).

A escolha de qual ROE projetar é a mesma de sempre — mediana histórica, que
resiste melhor a ano atípico —, e a de payout também. O que muda é o que se
projeta: não há margem EBITDA nem capex sobre receita num banco, há retorno
sobre patrimônio e quanto dele fica retido.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .lucro_residual import PremissasLucroResidual

# O aviso que ``cvm.py`` emite quando detecta o plano de contas financeiro. É
# por ele que o resto do app sabe, porque a informação não sobrevive no
# vocabulário canônico -- ela é sobre a origem, e não sobre uma conta.
MARCA_PLANO_FINANCEIRO = "instituicao financeira"

# Abaixo disto o histórico não sustenta uma mediana: dois pontos viram uma reta
# por qualquer par de anos, e a mediana de dois números é a média deles.
ANOS_MINIMOS = 3


def e_instituicao_financeira(demonstracoes) -> bool:
    """A companhia publica no plano de contas de banco ou seguradora?"""
    return any(MARCA_PLANO_FINANCEIRO in aviso for aviso in demonstracoes.avisos)


@dataclass(frozen=True)
class HistoricoDoBanco:
    """O que se lê do passado de uma instituição financeira.

    Três séries, e nada de margem ou capex: num banco elas não querem dizer o
    que querem dizer numa indústria.
    """

    patrimonio: pd.Series
    lucro: pd.Series
    roe: pd.Series
    payout: pd.Series
    anos: list[int]

    @property
    def roe_mediano(self) -> float:
        return float(self.roe.dropna().median()) if self.roe.notna().any() else float("nan")

    @property
    def payout_mediano(self) -> float:
        s = self.payout.dropna()
        return float(s.median()) if not s.empty else float("nan")

    @property
    def patrimonio_final(self) -> float:
        s = self.patrimonio.dropna()
        return float(s.iloc[-1]) if not s.empty else float("nan")

    def tabela(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "Patrimônio líquido": self.patrimonio,
                "Lucro líquido": self.lucro,
                "ROE": self.roe,
                "Payout": self.payout,
            }
        ).T


def ler_historico(demonstracoes) -> HistoricoDoBanco:
    """Patrimônio, lucro, ROE e payout, do que a companhia publicou.

    O ROE sai sobre o **patrimônio médio** do ano — abertura e fechamento sobre
    dois —, como o CFA manda e como o resto do app já calcula ROIC. Sobre o
    patrimônio final, um banco que capitalizou no meio do ano apareceria menos
    rentável do que foi.
    """
    anos = list(demonstracoes.anos)
    patrimonio = demonstracoes.serie("patrimonio_liquido").reindex(anos)
    lucro = demonstracoes.serie("lucro_liquido").reindex(anos)
    dividendos = demonstracoes.serie("dividendos_pagos").reindex(anos).abs()

    medio = (patrimonio + patrimonio.shift(1)) / 2
    roe = lucro / medio.replace(0, np.nan)
    payout = (dividendos / lucro.where(lucro > 0)).clip(0, 1)

    return HistoricoDoBanco(
        patrimonio=patrimonio,
        lucro=lucro,
        roe=roe.replace([np.inf, -np.inf], np.nan),
        payout=payout.replace([np.inf, -np.inf], np.nan),
        anos=anos,
    )


@dataclass(frozen=True)
class SugestaoDeBanco:
    """As premissas sugeridas, com o porquê de cada uma e o que não se sabe."""

    premissas: PremissasLucroResidual
    historico: HistoricoDoBanco
    justificativas: dict[str, str]
    alertas: list[str]


def sugerir_premissas_do_banco(
    demonstracoes, horizonte: int = 5, crescimento_perpetuo: float = 0.045
) -> SugestaoDeBanco:
    """Deriva do histórico o que o modelo de lucro residual precisa.

    **O ROE perpétuo fica igual ao Ke, e isso é decisão e não omissão.** Ele é o
    parâmetro que mais move o valor terminal, e a hipótese conservadora — a
    vantagem competitiva não sobrevive para sempre — é o padrão da literatura
    para instituição madura. Quem quiser afirmar vantagem perpétua digita, e a
    tela mostra o que isso custa.
    """
    historico = ler_historico(demonstracoes)
    justificativas: dict[str, str] = {}
    alertas: list[str] = []

    patrimonio = historico.patrimonio_final
    if not np.isfinite(patrimonio) or patrimonio <= 0:
        raise ValueError(
            "Nao ha patrimonio liquido no ultimo ano. O modelo de lucro residual "
            "ancora o valor nele, entao sem ele nao ha o que projetar."
        )

    roe = historico.roe_mediano
    if not np.isfinite(roe):
        roe = 0.12
        alertas.append(
            "Sem ROE historico calculavel; adotei 12% como ponto de partida. "
            "Confira antes de usar."
        )
    else:
        medidos = int(historico.roe.notna().sum())
        justificativas["roe"] = (
            f"Mediana historica de {roe:.1%}, sobre o patrimonio medio de cada ano, "
            f"em {medidos} exercicios."
        )
        if medidos < ANOS_MINIMOS:
            alertas.append(
                f"O ROE mediano vem de {medidos} exercicios. Abaixo de "
                f"{ANOS_MINIMOS} a mediana descreve os anos que entraram, e nao a "
                "instituicao."
            )

    payout = historico.payout_mediano
    if not np.isfinite(payout):
        payout = 0.40
        alertas.append(
            "A DFC nao trouxe dividendos pagos; adotei payout de 40%. Ele decide "
            "quanto do lucro fica retido e, com isso, o ritmo do patrimonio."
        )
    else:
        justificativas["payout"] = (
            f"Mediana historica de {payout:.0%} do lucro distribuido."
        )

    premissas = PremissasLucroResidual(
        patrimonio_inicial=patrimonio,
        roe=[roe] * horizonte,
        payout=[payout] * horizonte,
        crescimento_perpetuo=crescimento_perpetuo,
        roe_perpetuo=None,  # igual ao Ke: sem vantagem perpetua
    )
    justificativas["roe_perpetuo"] = (
        "Igual ao Ke, o que zera o valor terminal. Nao e omissao: e afirmar que a "
        "vantagem competitiva nao sobrevive para sempre, que e o padrao para "
        "instituicao madura. Mudar isso e a premissa que mais move o resultado."
    )

    alertas.append(
        "O modelo nao considera capital regulatorio. Um banco que cresce precisa "
        "de capital para sustentar o ativo ponderado por risco, e crescimento alto "
        "com payout alto pode ser inviavel por Basileia sem que a aritmetica "
        "reclame."
    )
    return SugestaoDeBanco(
        premissas=premissas,
        historico=historico,
        justificativas=justificativas,
        alertas=alertas,
    )


def beta_de_indiferenca(custo_capital, macro, roe: float) -> float:
    """O beta em que a instituição empata com o próprio custo de capital.

    Com o realavancamento desligado (ver
    ``PremissasCustoCapital.instituicao_financeira``), **o beta carrega o Ke
    sozinho** — e num banco o Ke decide o sinal do lucro residual. Abaixo deste
    beta a instituição cria valor sobre o livro; acima, destrói. O veredito
    inteiro do modelo gira em torno de um número que hoje é valor de referência
    embarcado, e não medido.

    Este número não conserta isso: **expõe**. Em vez de "o beta é 0,95, confie",
    a tela passa a dizer "com beta acima de X esta instituição destrói valor —
    julgue se X é plausível". É a mesma ideia do DCF reverso, aplicada ao
    parâmetro que aqui manda em tudo.

    O Ke é afim no beta::

        ke_usd = rf + beta * ERP + lambda * risco_pais + premio
        ke_brl = (1 + ke_usd) * (1 + infl_brl) / (1 + infl_usd) - 1

    então a inversão é fechada, e não precisa de busca.
    """
    if not np.isfinite(roe):
        return float("nan")
    erp = custo_capital.erp_maduro
    if not erp:
        return float("nan")

    # Desfaz a conversão de moeda para chegar ao Ke em USD equivalente ao ROE.
    ke_usd = (1 + roe) * (1 + macro.inflacao_usd) / (1 + macro.inflacao_brl) - 1
    sem_beta = (
        custo_capital.rf_usd
        + custo_capital.lambda_pais * custo_capital.risco_pais
        + custo_capital.premio_tamanho
    )
    return float((ke_usd - sem_beta) / erp)

"""Avaliacao relativa por multiplos de empresas comparaveis.

Multiplos de EV (EV/Receita, EV/EBITDA, EV/EBIT) produzem Enterprise Value e
exigem a ponte da divida liquida para chegar ao equity. Multiplos de equity
(P/L, P/VPA) ja produzem o valor do equity diretamente. Misturar os dois tipos
sem essa distincao e a fonte mais comum de erro em avaliacao relativa.

Denominadores nao positivos (EBITDA ou lucro negativo) geram multiplo ``NaN``
em vez de um numero sem significado economico, e sao excluidos das estatisticas
do peer group.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

# Multiplos de EV precisam da ponte da divida liquida; os de equity, nao.
MULTIPLOS_EV = ("EV/Receita", "EV/EBITDA", "EV/EBIT")
MULTIPLOS_EQUITY = ("P/L", "P/VPA")


@dataclass(frozen=True)
class Comparavel:
    """Uma empresa do peer group, com os dados de mercado e financeiros."""

    nome: str
    valor_mercado: float
    divida_liquida: float = 0.0
    receita: float = float("nan")
    ebitda: float = float("nan")
    ebit: float = float("nan")
    lucro_liquido: float = float("nan")
    patrimonio_liquido: float = float("nan")

    @property
    def enterprise_value(self) -> float:
        return self.valor_mercado + self.divida_liquida

    def multiplos(self) -> dict[str, float]:
        ev = self.enterprise_value
        return {
            "EV/Receita": _dividir(ev, self.receita),
            "EV/EBITDA": _dividir(ev, self.ebitda),
            "EV/EBIT": _dividir(ev, self.ebit),
            "P/L": _dividir(self.valor_mercado, self.lucro_liquido),
            "P/VPA": _dividir(self.valor_mercado, self.patrimonio_liquido),
        }


@dataclass(frozen=True)
class Alvo:
    """A empresa avaliada, com as mesmas metricas dos comparaveis."""

    nome: str
    receita: float = float("nan")
    ebitda: float = float("nan")
    ebit: float = float("nan")
    lucro_liquido: float = float("nan")
    patrimonio_liquido: float = float("nan")
    divida_liquida: float = 0.0
    acoes_em_circulacao: float | None = None

    def metrica(self, multiplo: str) -> float:
        return {
            "EV/Receita": self.receita,
            "EV/EBITDA": self.ebitda,
            "EV/EBIT": self.ebit,
            "P/L": self.lucro_liquido,
            "P/VPA": self.patrimonio_liquido,
        }[multiplo]


def _dividir(numerador: float, denominador: float) -> float:
    """Divisao que devolve NaN quando o denominador nao e economicamente valido."""
    if denominador is None or not np.isfinite(denominador) or denominador <= 0:
        return float("nan")
    return numerador / denominador


def tabela_comparaveis(comparaveis: list[Comparavel]) -> pd.DataFrame:
    """Uma linha por comparavel, uma coluna por multiplo."""
    if not comparaveis:
        raise ValueError("Informe ao menos um comparavel.")
    return pd.DataFrame(
        [c.multiplos() for c in comparaveis], index=[c.nome for c in comparaveis]
    )


def estatisticas(comparaveis: list[Comparavel]) -> pd.DataFrame:
    """Mediana, media, quartis e extremos de cada multiplo do peer group.

    A mediana e a referencia central preferida: com peer groups pequenos, a
    media e facilmente distorcida por um unico comparavel de multiplo extremo.
    """
    tabela = tabela_comparaveis(comparaveis)
    resumo = pd.DataFrame(
        {
            "n": tabela.count(),
            "Minimo": tabela.min(),
            "1o quartil": tabela.quantile(0.25),
            "Mediana": tabela.median(),
            "Media": tabela.mean(),
            "3o quartil": tabela.quantile(0.75),
            "Maximo": tabela.max(),
        }
    )
    return resumo


def avaliar_por_multiplos(
    alvo: Alvo,
    comparaveis: list[Comparavel],
    referencia: str = "Mediana",
) -> pd.DataFrame:
    """Valor implicito do alvo aplicando cada multiplo do peer group.

    ``referencia`` escolhe a estatistica aplicada: ``"Mediana"``, ``"Media"``,
    ``"1o quartil"`` ou ``"3o quartil"``.
    """
    resumo = estatisticas(comparaveis)
    if referencia not in resumo.columns:
        raise ValueError(
            f"referencia {referencia!r} invalida. Opcoes: "
            f"{[c for c in resumo.columns if c != 'n']}"
        )

    linhas = []
    for multiplo in MULTIPLOS_EV + MULTIPLOS_EQUITY:
        estatistica = resumo.loc[multiplo, referencia]
        metrica = alvo.metrica(multiplo)
        if not np.isfinite(estatistica) or not np.isfinite(metrica) or metrica <= 0:
            ev = equity = float("nan")
        elif multiplo in MULTIPLOS_EV:
            ev = estatistica * metrica
            equity = ev - alvo.divida_liquida
        else:
            equity = estatistica * metrica
            ev = equity + alvo.divida_liquida
        por_acao = (
            equity / alvo.acoes_em_circulacao
            if alvo.acoes_em_circulacao and np.isfinite(equity)
            else float("nan")
        )
        linhas.append(
            {
                "Multiplo": multiplo,
                f"{referencia} do setor": estatistica,
                "Metrica do alvo": metrica,
                "Enterprise Value": ev,
                "Equity Value": equity,
                "Valor por ação": por_acao,
            }
        )
    return pd.DataFrame(linhas).set_index("Multiplo")


def faixa_de_valor(
    alvo: Alvo,
    comparaveis: list[Comparavel],
    multiplos: tuple[str, ...] = ("EV/EBITDA",),
) -> pd.DataFrame:
    """Faixa de equity value entre o 1o e o 3o quartil dos multiplos escolhidos.

    E o formato que costuma ir para o comite: uma faixa defensavel, e nao um
    numero unico com falsa precisao.
    """
    resumo = estatisticas(comparaveis)
    linhas = []
    for multiplo in multiplos:
        if multiplo not in resumo.index:
            raise ValueError(f"multiplo desconhecido: {multiplo!r}")
        metrica = alvo.metrica(multiplo)
        valores = {}
        for rotulo in ("1o quartil", "Mediana", "3o quartil"):
            estatistica = resumo.loc[multiplo, rotulo]
            if not np.isfinite(estatistica) or not np.isfinite(metrica) or metrica <= 0:
                valores[rotulo] = float("nan")
            elif multiplo in MULTIPLOS_EV:
                valores[rotulo] = estatistica * metrica - alvo.divida_liquida
            else:
                valores[rotulo] = estatistica * metrica
        linhas.append({"Multiplo": multiplo, **valores})
    return pd.DataFrame(linhas).set_index("Multiplo")

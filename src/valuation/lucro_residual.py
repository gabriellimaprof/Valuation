"""Lucro residual: o modelo para quem tem dívida como matéria-prima.

**FCFF e WACC não se aplicam a banco nem a seguradora**, e o motivo não é
técnico, é econômico: para uma indústria a dívida financia o ativo e o custo dela
entra na taxa de desconto; para um banco a dívida (depósito, captação) **é o
insumo do negócio**, e o spread entre captar e emprestar é a receita. Descontar
um "fluxo para a firma" ao WACC de um banco soma ao valor o que ele ganha por
tomar dinheiro, e depois desconta por ele tomar dinheiro. São 19 das 467
companhias da base brasileira de 2024.

O modelo aqui é o de **lucro residual** (Ohlson), também chamado de lucro
econômico::

    Valor do equity = PL contábil + soma de (Lucro_t - Ke x PL_{t-1}) / (1+Ke)^t

A leitura é direta: **a empresa vale o patrimônio que tem, mais o valor presente
do que ela ganha acima do custo de capital sobre esse patrimônio.** Um banco que
entrega exatamente o Ke vale o próprio livro, e nem um centavo a mais.

Por que ele, e não um Gordon sobre dividendos:

- **O patrimônio contábil de um banco quer dizer alguma coisa.** O ativo é
  crédito e título marcado, não fábrica depreciada por convenção fiscal. A âncora
  contábil é forte justamente onde ela costuma ser fraca.
- **O valor terminal pesa muito menos.** No DCF o terminal costuma valer 60% a
  80% do total; aqui a maior parte já está no PL inicial, e o terminal carrega só
  o excesso perpétuo. Erro na premissa mais frágil custa menos.
- **A hipótese de regime tem nome:** ROE perpétuo igual ao Ke. Nesse caso o
  terminal é **zero**, e isso não é defeito -- é a afirmação de que a vantagem
  competitiva não sobrevive para sempre, que é o padrão da literatura para banco
  maduro.

O que este módulo **não** faz, e é honesto dizer: não modela capital
regulatório. Um banco que cresce precisa de capital para sustentar o ativo
ponderado por risco, e crescimento alto com payout alto pode ser inviável por
Basileia sem que a aritmética aqui reclame.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .erros import CombinacaoInviavel


@dataclass(frozen=True)
class PremissasLucroResidual:
    """O que descreve um banco: patrimônio, retorno sobre ele e o que distribui.

    ``roe`` e ``payout`` são listas por ano projetado. ``roe_perpetuo`` é o
    retorno de regime: deixá-lo igual ao Ke zera o valor terminal, que é a
    hipótese conservadora e o padrão da literatura para instituição madura.
    """

    patrimonio_inicial: float
    roe: list[float] = field(default_factory=list)
    payout: list[float] = field(default_factory=list)
    crescimento_perpetuo: float = 0.045
    roe_perpetuo: float | None = None

    def __post_init__(self) -> None:
        if self.patrimonio_inicial <= 0:
            raise ValueError(
                "O patrimonio inicial precisa ser positivo: o modelo de lucro "
                "residual ancora o valor nele."
            )
        if not self.roe:
            raise ValueError("Informe o ROE de ao menos um ano projetado.")
        if len(self.payout) != len(self.roe):
            raise ValueError(
                f"ROE tem {len(self.roe)} anos e payout tem {len(self.payout)}. "
                "Cada ano projetado precisa dos dois."
            )
        for p in self.payout:
            if not (0.0 <= p <= 1.0):
                raise ValueError(
                    f"Payout de {p:.0%} nao existe aqui: distribuir mais que o "
                    "lucro encolhe o patrimonio, e isso se modela com ROE negativo."
                )

    @property
    def horizonte(self) -> int:
        return len(self.roe)


@dataclass(frozen=True)
class ValuationLucroResidual:
    """O resultado, com as parcelas separadas para poder ser conferido."""

    patrimonio_inicial: float
    anos: list[int]
    patrimonio_abertura: np.ndarray
    lucro: np.ndarray
    dividendos: np.ndarray
    lucro_residual: np.ndarray
    valor_presente_residual: float
    valor_terminal: float
    valor_presente_terminal: float
    equity_value: float
    ke: float

    @property
    def peso_do_patrimonio(self) -> float:
        """Quanto do valor já está no livro, e não em expectativa.

        É a virtude do modelo: no DCF de uma indústria o valor terminal costuma
        valer 60% a 80% do total; aqui a âncora contábil carrega boa parte.
        """
        if not self.equity_value:
            return float("nan")
        return self.patrimonio_inicial / self.equity_value

    @property
    def peso_do_terminal(self) -> float:
        if not self.equity_value:
            return float("nan")
        return self.valor_presente_terminal / self.equity_value

    def tabela(self) -> pd.DataFrame:
        """A conta ano a ano, para conferir a mão."""
        return pd.DataFrame(
            {
                "Patrimônio (abertura)": self.patrimonio_abertura,
                "Lucro líquido": self.lucro,
                "Custo do capital próprio": -self.ke * self.patrimonio_abertura,
                "Lucro residual": self.lucro_residual,
                "Dividendos": self.dividendos,
            },
            index=[str(a) for a in self.anos],
        ).T


def avaliar_lucro_residual(
    premissas: PremissasLucroResidual, ke: float, ano_base: int = 0
) -> ValuationLucroResidual:
    """Desconta o lucro acima do custo de capital e soma ao patrimônio.

    O patrimônio de cada ano é o do anterior mais o lucro retido -- **clean
    surplus**, a hipótese que faz a identidade fechar. Ela não vale ao pé da
    letra: ajuste de avaliação patrimonial e resultado de hedge passam pelo PL
    sem passar pelo resultado, e são justamente as linhas que a DRA traz.
    """
    if not np.isfinite(ke) or ke <= 0:
        raise ValueError(f"Ke de {ke!r} nao desconta nada.")

    n = premissas.horizonte
    roe = np.asarray(premissas.roe, dtype=float)
    payout = np.asarray(premissas.payout, dtype=float)

    abertura = np.empty(n)
    lucro = np.empty(n)
    dividendos = np.empty(n)
    patrimonio = float(premissas.patrimonio_inicial)
    for i in range(n):
        abertura[i] = patrimonio
        lucro[i] = roe[i] * patrimonio
        dividendos[i] = payout[i] * lucro[i]
        patrimonio = patrimonio + lucro[i] - dividendos[i]

    # O custo do capital proprio incide sobre o patrimonio de **abertura**: o
    # lucro do ano foi ganho sobre o capital que estava la no comeco dele.
    residual = lucro - ke * abertura
    fatores = 1 / (1 + ke) ** np.arange(1, n + 1)
    vp_residual = float((residual * fatores).sum())

    g = premissas.crescimento_perpetuo
    roe_perp = premissas.roe_perpetuo if premissas.roe_perpetuo is not None else ke
    if g >= ke:
        raise CombinacaoInviavel(
            f"O crescimento perpetuo ({g:.2%}) precisa ficar abaixo do Ke "
            f"({ke:.2%}); caso contrario o valor terminal e infinito."
        )
    # Excesso perpetuo sobre o patrimonio de fechamento. Com ROE perpetuo igual
    # ao Ke isto da **zero**, e nao e defeito: e dizer que a vantagem nao
    # sobrevive para sempre.
    residual_perpetuo = (roe_perp - ke) * patrimonio
    vt = residual_perpetuo / (ke - g)
    vp_terminal = vt / (1 + ke) ** n

    return ValuationLucroResidual(
        patrimonio_inicial=float(premissas.patrimonio_inicial),
        anos=[ano_base + i + 1 for i in range(n)],
        patrimonio_abertura=abertura,
        lucro=lucro,
        dividendos=dividendos,
        lucro_residual=residual,
        valor_presente_residual=vp_residual,
        valor_terminal=float(vt),
        valor_presente_terminal=float(vp_terminal),
        equity_value=float(premissas.patrimonio_inicial + vp_residual + vp_terminal),
        ke=float(ke),
    )

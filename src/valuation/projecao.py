"""Projecao explicita da demonstracao de resultados e dos fluxos de caixa.

Definicoes usadas:

* ``EBIT = EBITDA - Depreciacao``
* ``NOPAT = EBIT * (1 - t)`` (imposto calculado sobre o EBIT, nao sobre o LAIR,
  porque o FCFF e desalavancado por construcao)
* ``FCFF = NOPAT + Depreciacao - Capex - Variacao do capital de giro``
* ``FCFE = FCFF - Juros * (1 - t) + Variacao da divida``

O capital de giro entra como *saldo* percentual da receita; a variacao anual e
derivada dele, o que evita o erro de tratar um estoque como fluxo.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .premissas import PremissasMacro, PremissasOperacionais

# Trava dos 30%: limite anual de compensacao de prejuizo fiscal no Brasil.
LIMITE_COMPENSACAO_PREJUIZO = 0.30


@dataclass(frozen=True)
class Projecao:
    """Resultado da projecao explicita, ano a ano."""

    anos: list[int]
    receita: np.ndarray
    ebitda: np.ndarray
    depreciacao: np.ndarray
    ebit: np.ndarray
    impostos: np.ndarray
    nopat: np.ndarray
    capex: np.ndarray
    capital_giro: np.ndarray
    variacao_capital_giro: np.ndarray
    fcff: np.ndarray
    arrendamento: np.ndarray | None = None
    variacao_arrendamento: np.ndarray | None = None
    juros: np.ndarray | None = None
    variacao_divida: np.ndarray | None = None
    fcfe: np.ndarray | None = None
    prejuizo_fiscal_saldo: np.ndarray | None = None

    @property
    def horizonte(self) -> int:
        return len(self.anos)

    def tabela(self) -> pd.DataFrame:
        """DataFrame com as linhas na ordem de um modelo de valuation."""
        linhas: dict[str, np.ndarray] = {
            "Receita liquida": self.receita,
            "EBITDA": self.ebitda,
            "(-) Depreciacao e amortizacao": -self.depreciacao,
            "EBIT": self.ebit,
            "(-) IR/CSLL sobre EBIT": -self.impostos,
            "NOPAT": self.nopat,
            "(+) Depreciacao e amortizacao": self.depreciacao,
            "(-) Capex": -self.capex,
            "(-) Variacao do capital de giro": -self.variacao_capital_giro,
        }
        if self.variacao_arrendamento is not None:
            linhas["(-) Adicoes de arrendamento"] = -self.variacao_arrendamento
        linhas["FCFF (fluxo para a firma)"] = self.fcff
        if self.fcfe is not None:
            linhas["(-) Juros apos IR"] = -self.juros * (1 - self._aliquota_implicita())
            linhas["(+) Variacao da divida"] = self.variacao_divida
            linhas["FCFE (fluxo para o acionista)"] = self.fcfe
        df = pd.DataFrame(linhas, index=self.anos).T
        df.columns = [f"Ano {a}" for a in self.anos]
        return df

    def _aliquota_implicita(self) -> float:
        """Recupera a aliquota efetiva usada, para reexibir os juros liquidos."""
        with np.errstate(divide="ignore", invalid="ignore"):
            razao = np.where(self.ebit != 0, self.impostos / self.ebit, np.nan)
        finitos = razao[np.isfinite(razao)]
        return float(finitos[0]) if finitos.size else 0.0

    def indicadores(self) -> pd.DataFrame:
        """Margens e taxas derivadas, uteis para checar se a projecao faz sentido."""
        crescimento = np.full(self.horizonte, np.nan)
        crescimento[1:] = self.receita[1:] / self.receita[:-1] - 1
        return pd.DataFrame(
            {
                "Crescimento da receita": crescimento,
                "Margem EBITDA": self.ebitda / self.receita,
                "Margem EBIT": self.ebit / self.receita,
                "Capex / Receita": self.capex / self.receita,
                "Capex / Depreciacao": np.where(
                    self.depreciacao != 0, self.capex / self.depreciacao, np.nan
                ),
                "Capital de giro / Receita": self.capital_giro / self.receita,
            },
            index=[f"Ano {a}" for a in self.anos],
        ).T


def calcular_impostos(
    ebit: np.ndarray,
    aliquota: float,
    prejuizo_acumulado: float = 0.0,
    limite_compensacao: float = LIMITE_COMPENSACAO_PREJUIZO,
) -> tuple[np.ndarray, np.ndarray]:
    """Imposto ano a ano, considerando prejuizo fiscal acumulado.

    Segue a regra brasileira da *trava dos 30%*: o prejuizo fiscal de exercicios
    anteriores pode ser compensado indefinidamente no tempo, mas em cada ano
    reduz no maximo 30% do lucro tributavel. Ignorar a trava superestima o caixa
    dos primeiros anos de uma empresa que vem de prejuizo -- exatamente os anos
    que mais pesam no valor presente.

    Devolve ``(impostos, saldo de prejuizo ao fim de cada ano)``.
    """
    if not 0 <= limite_compensacao <= 1:
        raise ValueError("limite_compensacao deve estar entre 0 e 1.")
    if prejuizo_acumulado < 0:
        raise ValueError("prejuizo_acumulado deve ser informado como valor positivo.")

    impostos = np.zeros(len(ebit))
    saldos = np.zeros(len(ebit))
    saldo = float(prejuizo_acumulado)

    for i, resultado in enumerate(ebit):
        if resultado <= 0:
            # Prejuizo do exercicio engrossa o saldo a compensar no futuro.
            saldo += float(-resultado)
        else:
            compensavel = min(saldo, limite_compensacao * float(resultado))
            saldo -= compensavel
            impostos[i] = (float(resultado) - compensavel) * aliquota
        saldos[i] = saldo

    return impostos, saldos


def projetar(
    operacionais: PremissasOperacionais,
    macro: PremissasMacro | None = None,
    divida_por_ano: list[float] | None = None,
    divida_inicial: float = 0.0,
    custo_divida: float = 0.0,
    prejuizo_fiscal_acumulado: float = 0.0,
) -> Projecao:
    """Constroi a projecao explicita a partir das premissas operacionais.

    O FCFE so e calculado quando ``divida_por_ano`` e informado (saldo de divida
    ao fim de cada ano projetado). Os juros de cada ano incidem sobre o saldo de
    abertura, isto e, o saldo do ano anterior.

    ``prejuizo_fiscal_acumulado`` ativa a compensacao de prejuizos anteriores,
    com a trava de 30% ao ano prevista na legislacao brasileira.
    """
    macro = macro or PremissasMacro()
    t = macro.aliquota_ir
    n = operacionais.horizonte

    receita = np.empty(n)
    anterior = operacionais.receita_base
    for i, g in enumerate(operacionais.crescimento_receita):
        anterior = anterior * (1 + g)
        receita[i] = anterior

    ebitda = receita * np.asarray(operacionais.margem_ebitda, dtype=float)
    depreciacao = receita * np.asarray(operacionais.depreciacao_pct_receita, dtype=float)
    capex = receita * np.asarray(operacionais.capex_pct_receita, dtype=float)
    ebit = ebitda - depreciacao
    # Prejuizo nao gera credito de imposto; quando ha prejuizo acumulado, ele
    # abate o lucro futuro respeitando a trava dos 30%.
    impostos, prejuizo_saldo = calcular_impostos(ebit, t, prejuizo_fiscal_acumulado)
    nopat = ebit - impostos

    pct_giro = np.asarray(operacionais.capital_giro_pct_receita, dtype=float)
    capital_giro = receita * pct_giro
    if operacionais.capital_giro_inicial is not None:
        giro_inicial = operacionais.capital_giro_inicial
    else:
        giro_inicial = operacionais.receita_base * pct_giro[0]
    variacao_capital_giro = np.diff(capital_giro, prepend=giro_inicial)

    # Adicoes de arrendamento sao investimento que nao passa pelo capex: o
    # contrato cria ativo de direito de uso e passivo na mesma hora. Sem esta
    # linha, uma rede que cresce abrindo pontos mostra FCFF que ela nao tem.
    arrendamento = variacao_arrendamento = None
    if operacionais.arrendamento_pct_receita is not None:
        pct_arrendamento = np.asarray(operacionais.arrendamento_pct_receita, dtype=float)
        arrendamento = receita * pct_arrendamento
        if operacionais.arrendamento_inicial is not None:
            arrendamento_inicial = operacionais.arrendamento_inicial
        else:
            arrendamento_inicial = operacionais.receita_base * pct_arrendamento[0]
        variacao_arrendamento = np.diff(arrendamento, prepend=arrendamento_inicial)

    fcff = nopat + depreciacao - capex - variacao_capital_giro
    if variacao_arrendamento is not None:
        fcff = fcff - variacao_arrendamento

    anos = [operacionais.ano_base + i + 1 for i in range(n)]

    juros = variacao_divida = fcfe = None
    if divida_por_ano is not None:
        if len(divida_por_ano) != n:
            raise ValueError(
                f"divida_por_ano tem {len(divida_por_ano)} anos, "
                f"mas a projecao tem {n}."
            )
        saldos = np.asarray(divida_por_ano, dtype=float)
        saldos_abertura = np.concatenate(([divida_inicial], saldos[:-1]))
        juros = saldos_abertura * custo_divida
        variacao_divida = np.diff(saldos, prepend=divida_inicial)
        fcfe = fcff - juros * (1 - t) + variacao_divida

    return Projecao(
        anos=anos,
        receita=receita,
        ebitda=ebitda,
        depreciacao=depreciacao,
        ebit=ebit,
        impostos=impostos,
        nopat=nopat,
        capex=capex,
        capital_giro=capital_giro,
        variacao_capital_giro=variacao_capital_giro,
        arrendamento=arrendamento,
        variacao_arrendamento=variacao_arrendamento,
        fcff=fcff,
        juros=juros,
        variacao_divida=variacao_divida,
        fcfe=fcfe,
        prejuizo_fiscal_saldo=prejuizo_saldo,
    )

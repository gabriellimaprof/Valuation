"""Na seguradora, o custo da operacao lancado em outras despesas nao e evento.

A Porto Seguro lanca "Despesas de seguro" (-21.614 em 2024) dentro de `3.04.05`,
"Outras despesas operacionais". O app trata a conta inteira como item nao
recorrente, e tirava o sinistro da margem: EBIT recorrente de 82% contra 8,8%
reportado, margem EBITDA sugerida de 82%, R$ 286 por acao.
"""

from __future__ import annotations

import pandas as pd
import pytest

from valuation.historico import analisar
from valuation.importacao import Demonstracoes
from valuation.importacao.aplicacoes import operacao_de_seguro_em_outros


def _demonstracoes(receita_rotulo: str, filhas: dict[str, tuple[str, float]]):
    """Uma companhia com EBIT de 31 sobre receita de 350, e `3.04.05` aberta."""
    total_outras = sum(v for _, v in filhas.values())
    linhas = {
        "1.02.01": ("Ativo Realizável a Longo Prazo", 0.0),
        "3.01": ("Receita de Venda de Bens e/ou Serviços", 350.0),
        "3.01.07": (receita_rotulo, 350.0),
        "3.04.05": ("Outras Despesas Operacionais", total_outras),
        **filhas,
    }
    arvore = pd.DataFrame(
        [
            {
                "codigo": codigo,
                "rotulo": rotulo,
                "demonstracao": "dre",
                "nivel": codigo.count(".") + 1,
                "ordem": tuple(int(p) for p in codigo.split(".")),
                2023: valor,
                2024: valor,
            }
            for codigo, (rotulo, valor) in linhas.items()
        ]
    )
    valores = pd.DataFrame(
        {
            ano: {
                "receita_liquida": 350.0,
                "ebit": 31.0,
                "depreciacao_amortizacao": 5.0,
                "patrimonio_liquido": 200.0,
                "outras_despesas_operacionais": total_outras,
            }
            for ano in (2023, 2024)
        }
    )
    return Demonstracoes(empresa="T", valores=valores, unidade="R$ mi", detalhe=arvore)


PORTO_SEGURO = {
    "3.04.05.08": ("Custos de aquisição - outros", -7.7),
    "3.04.05.09": ("Custos dos serviços prestados", -2.4),
    "3.04.05.10": ("Outras despesas operacionais", -33.2),
    "3.04.05.11": ("Despesas de seguro", -216.1),
    "3.04.05.12": ("Despesas líquidas com contratos de resseguros/retrocessões", -0.6),
}


def test_o_sinistro_da_seguradora_fica_na_margem_recorrente():
    d = _demonstracoes("Receita de Seguro", PORTO_SEGURO)
    operacao = operacao_de_seguro_em_outros(d.detalhe, [2024])
    assert operacao[2024] == pytest.approx(-7.7 - 2.4 - 216.1 - 0.6)

    margem = analisar(d).linha("Margem EBIT recorrente")[2024]
    # So a sublinha "Outras despesas operacionais" continua como evento:
    # (31 + 33,2) / 350 = 18,3%, e nao (31 + 260) / 350 = 83%.
    assert margem == pytest.approx((31.0 + 33.2) / 350.0)


def test_quem_nao_opera_seguro_nao_muda():
    """Uma industrial com "Seguros" em outras despesas é despesa com apólice."""
    d = _demonstracoes(
        "Receita de vendas",
        {
            "3.04.05.01": ("Seguros", -5.0),
            "3.04.05.02": ("Outras despesas operacionais", -20.0),
        },
    )
    assert operacao_de_seguro_em_outros(d.detalhe, [2024])[2024] == 0.0
    margem = analisar(d).linha("Margem EBIT recorrente")[2024]
    assert margem == pytest.approx((31.0 + 25.0) / 350.0)


def test_sem_arvore_nada_se_tira():
    assert operacao_de_seguro_em_outros(None, [2024])[2024] == 0.0

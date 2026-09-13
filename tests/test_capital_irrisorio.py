"""ROIC vazio onde o capital investido nao sustenta a divisao.

Abaixo de 5% da receita, o ROIC mede o denominador: a Porto Saude saia com 460%,
e uma mediana assim desligava o alerta de ROIC de perpetuidade acima do
historico. Medido na safra 2021-2025, o corte em giro de 20x pega 10 exercicios
de 4 companhias, e o primeiro abaixo e a BRQ em 2022, com 18,5x.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from valuation.historico import GIRO_DO_CAPITAL_IMPLAUSIVEL, analisar
from valuation.importacao import Demonstracoes


def _analise(patrimonio: float):
    valores = pd.DataFrame(
        {
            ano: {
                "receita_liquida": 1000.0,
                "custo_produtos_vendidos": 600.0,
                "ebit": 200.0,
                "depreciacao_amortizacao": 50.0,
                "ativo_total": 3000.0,
                "patrimonio_liquido": patrimonio,
                "lucro_liquido": 130.0,
            }
            for ano in (2022, 2023, 2024)
        }
    )
    return analisar(Demonstracoes(empresa="T", valores=valores, unidade="R$ mi"))


def test_capital_irrisorio_deixa_o_roic_vazio_e_diz_quando():
    # Capital de 30 contra receita de 1.000: giro de 33x.
    analise = _analise(patrimonio=30.0)
    assert analise.linha("ROIC").dropna().empty
    assert analise.linha("Giro do capital investido").dropna().empty
    assert analise.capital_irrisorio
    assert set(analise.capital_irrisorio) <= {2022, 2023, 2024}


def test_roic_alto_de_verdade_passa():
    """Giro de 12,5x, como a Whirlpool em 2024: alto, e verdadeiro."""
    analise = _analise(patrimonio=80.0)
    giro = analise.linha("Giro do capital investido").dropna()
    assert not giro.empty and (giro < GIRO_DO_CAPITAL_IMPLAUSIVEL).all()
    assert np.isfinite(analise.linha("ROIC").dropna()).all()
    assert analise.capital_irrisorio == ()


def test_o_diagnostico_diz_por_que_o_roic_sumiu():
    from valuation.diagnostico import _capital_irrisorio

    (achado,) = _capital_irrisorio(_analise(patrimonio=30.0))
    assert achado.codigo == "roic_de_capital_irrisorio"
    assert "5%" in achado.titulo
    assert _capital_irrisorio(_analise(patrimonio=800.0)) == []

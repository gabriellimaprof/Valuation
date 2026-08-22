"""Reconhecer um banco, e derivar do histórico dele o que o modelo pede.

O app precisa saber que a companhia é instituição financeira **antes** de
mostrar um número, porque o caminho de FCFF/WACC não se aplica a ela. E as
premissas que ela pede são outras: não há margem EBITDA nem capex sobre receita
num banco, há retorno sobre patrimônio e quanto dele fica retido.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from valuation.bancos import (
    e_instituicao_financeira,
    ler_historico,
    sugerir_premissas_do_banco,
)
from valuation.importacao import Demonstracoes
from valuation.importacao.cvm import importar_cvm
from valuation.lucro_residual import avaliar_lucro_residual

DADOS = Path(__file__).parent / "dados" / "cvm"


def _banco(**contas) -> Demonstracoes:
    """Um banco de brinquedo, com clean surplus fechando por construção."""
    anos = [2022, 2023, 2024]
    base = {
        "patrimonio_liquido": [1000.0, 1100.0, 1210.0],
        "lucro_liquido": [180.0, 198.0, 217.8],
        "dividendos_pagos": [-80.0, -88.0, -96.8],
    }
    base.update(contas)
    return Demonstracoes(
        empresa="Banco Teste",
        valores=pd.DataFrame(base, index=anos).T,
        avisos=["Esta companhia publica no plano de contas de instituicao financeira."],
    )


# ---------------------------------------------------------------------------
# Reconhecer
# ---------------------------------------------------------------------------


def test_o_aviso_do_importador_e_o_que_identifica_o_banco():
    """A informação é sobre a **origem**, e não sobre uma conta.

    Ela não sobrevive no vocabulário canônico — não há conta "é banco" —, então
    viaja no aviso que o leitor da CVM emite ao detectar o plano de contas.
    """
    assert e_instituicao_financeira(_banco())


def test_industria_nao_e_confundida_com_banco(catalogo=None):
    weg = importar_cvm(5410, [2024], cache=DADOS)
    assert not e_instituicao_financeira(weg)


# ---------------------------------------------------------------------------
# O que se le do passado
# ---------------------------------------------------------------------------


def test_o_roe_sai_sobre_o_patrimonio_medio():
    """Como o CFA manda, e como o resto do app já calcula ROIC.

    Sobre o patrimônio final, um banco que capitalizou no meio do ano apareceria
    menos rentável do que foi.
    """
    historico = ler_historico(_banco())
    # 2023: 198 / ((1000 + 1100) / 2) = 18,86%
    assert float(historico.roe[2023]) == pytest.approx(198.0 / 1050.0)
    # O primeiro ano não tem abertura, então não tem ROE.
    assert not np.isfinite(historico.roe[2022])


def test_o_payout_sai_dos_dividendos_pagos_da_dfc():
    historico = ler_historico(_banco())
    assert float(historico.payout[2023]) == pytest.approx(88.0 / 198.0)


def test_payout_nao_passa_de_cem_por_cento():
    """Distribuir reserva de anos anteriores é possível, e não é payout do ano.

    Deixar passar de 100% faria o patrimônio projetado encolher por uma conta que
    descreve o passado, e não a política.
    """
    historico = ler_historico(_banco(dividendos_pagos=[-80.0, -400.0, -96.8]))
    assert float(historico.payout[2023]) == pytest.approx(1.0)


def test_prejuizo_nao_vira_payout_negativo():
    """Dividendo sobre lucro negativo não quer dizer nada."""
    historico = ler_historico(_banco(lucro_liquido=[180.0, -50.0, 217.8]))
    assert not np.isfinite(historico.payout[2023])


# ---------------------------------------------------------------------------
# A sugestao
# ---------------------------------------------------------------------------


def test_a_sugestao_parte_do_patrimonio_do_ultimo_ano():
    sugestao = sugerir_premissas_do_banco(_banco())
    assert sugestao.premissas.patrimonio_inicial == pytest.approx(1210.0)


def test_o_roe_sugerido_e_a_mediana_historica():
    sugestao = sugerir_premissas_do_banco(_banco())
    historico = ler_historico(_banco())
    assert sugestao.premissas.roe[0] == pytest.approx(historico.roe_mediano)
    assert "roe" in sugestao.justificativas


def test_o_roe_perpetuo_nasce_igual_ao_ke():
    """Não é omissão: é afirmar que a vantagem não sobrevive para sempre.

    É o parâmetro que mais move o valor terminal, e a hipótese conservadora é o
    padrão da literatura para instituição madura. Quem quiser afirmar vantagem
    perpétua digita.
    """
    sugestao = sugerir_premissas_do_banco(_banco())
    assert sugestao.premissas.roe_perpetuo is None
    assert "roe_perpetuo" in sugestao.justificativas

    resultado = avaliar_lucro_residual(sugestao.premissas, ke=0.145)
    assert resultado.valor_presente_terminal == pytest.approx(0.0, abs=1e-9)


def test_o_capital_regulatorio_e_declarado_como_ausente():
    """O que o modelo não faz precisa estar escrito onde ele é usado.

    Crescimento alto com payout alto pode ser inviável por Basileia sem que a
    aritmética reclame.
    """
    sugestao = sugerir_premissas_do_banco(_banco())
    assert any("capital regulatorio" in a for a in sugestao.alertas)


def test_historico_curto_vira_alerta():
    """Mediana de dois números é a média deles, e não descreve a instituição."""
    curto = Demonstracoes(
        empresa="Banco Novo",
        valores=pd.DataFrame(
            {
                "patrimonio_liquido": [1000.0, 1100.0],
                "lucro_liquido": [180.0, 198.0],
                "dividendos_pagos": [-80.0, -88.0],
            },
            index=[2023, 2024],
        ).T,
        avisos=["plano de contas de instituicao financeira"],
    )
    sugestao = sugerir_premissas_do_banco(curto)
    assert any("exercicios" in a for a in sugestao.alertas)


def test_sem_patrimonio_o_modelo_recusa():
    """Sem âncora não há modelo: ele **é** o patrimônio mais o excesso."""
    sem_pl = Demonstracoes(
        empresa="Banco Vazio",
        valores=pd.DataFrame(
            {"lucro_liquido": [10.0, 12.0]}, index=[2023, 2024]
        ).T,
        avisos=["instituicao financeira"],
    )
    with pytest.raises(ValueError, match="patrimonio liquido"):
        sugerir_premissas_do_banco(sem_pl)


# ---------------------------------------------------------------------------
# Contra os bancos de verdade
# ---------------------------------------------------------------------------


def test_banco_que_nao_ganha_o_custo_de_capital_vale_menos_que_o_livro():
    """A afirmação que dá sentido ao modelo, num caso concreto.

    Medido com Ke de 14,5% sobre a mediana 2020-2024: Itaú e BB, com ROE perto de
    18%, saem acima de 1,1x o valor de livro; o Bradesco, com ROE de 12,1% —
    abaixo do Ke —, sai a **0,91x**. Um banco que não entrega o custo de capital
    destrói valor sobre o patrimônio que tem, e o modelo diz isso sem que
    ninguém precise afirmar.
    """
    ke = 0.145
    acima = sugerir_premissas_do_banco(_banco())  # ROE ~18%
    assert avaliar_lucro_residual(acima.premissas, ke=ke).equity_value > 1210.0

    abaixo = sugerir_premissas_do_banco(
        _banco(lucro_liquido=[100.0, 110.0, 121.0])  # ROE ~10,5%
    )
    resultado = avaliar_lucro_residual(abaixo.premissas, ke=ke)
    assert resultado.equity_value < abaixo.premissas.patrimonio_inicial

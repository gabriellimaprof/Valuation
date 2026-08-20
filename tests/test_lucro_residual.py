"""O modelo de lucro residual, para banco e seguradora.

FCFF e WACC não se aplicam a eles: para um banco a dívida é o insumo do negócio,
e descontar um "fluxo para a firma" ao WACC soma ao valor o que ele ganha por
tomar dinheiro e depois desconta por ele tomar dinheiro. São 19 das 467
companhias da base de 2024.

O que estes testes travam são as duas identidades que dão sentido ao modelo, e
que uma implementação distraída quebra sem avisar: **ROE igual ao Ke tem que
devolver o valor de livro**, e **lucro residual tem que dar o mesmo que desconto
de dividendos** quando o patrimônio fecha pelo lucro retido.
"""

from __future__ import annotations

import numpy as np
import pytest

from valuation.erros import CombinacaoInviavel
from valuation.lucro_residual import (
    PremissasLucroResidual,
    avaliar_lucro_residual,
)


def _premissas(**ajustes) -> PremissasLucroResidual:
    base = {
        "patrimonio_inicial": 1000.0,
        "roe": [0.18] * 5,
        "payout": [0.40] * 5,
        "crescimento_perpetuo": 0.045,
    }
    base.update(ajustes)
    return PremissasLucroResidual(**base)


# ---------------------------------------------------------------------------
# As duas identidades
# ---------------------------------------------------------------------------


def test_roe_igual_ao_ke_devolve_o_valor_de_livro():
    """A afirmação central do modelo, e o teste que pega quase todo erro.

    Um banco que entrega exatamente o custo de capital vale o próprio livro, e
    nem um centavo a mais. Se a conta do custo do capital próprio incidir sobre o
    patrimônio errado — o de fechamento em vez do de abertura, por exemplo —,
    isto deixa de valer e nada mais denuncia.
    """
    resultado = avaliar_lucro_residual(
        _premissas(roe=[0.14] * 5, roe_perpetuo=0.14), ke=0.14
    )
    assert resultado.equity_value == pytest.approx(1000.0)
    assert resultado.valor_presente_residual == pytest.approx(0.0, abs=1e-9)
    assert resultado.valor_presente_terminal == pytest.approx(0.0, abs=1e-9)


def test_lucro_residual_e_desconto_de_dividendos_dao_o_mesmo():
    """A identidade de Ohlson, conferida numericamente.

    Com ``roe_perpetuo`` igual ao Ke o excesso perpétuo é zero, então em ``n`` a
    empresa vale o patrimônio contábil daquele momento. Descontar os dividendos
    do horizonte mais esse patrimônio tem que dar o mesmo que o patrimônio
    inicial mais os lucros residuais descontados.
    """
    ke = 0.14
    premissas = _premissas(roe_perpetuo=ke)
    resultado = avaliar_lucro_residual(premissas, ke=ke)

    n = premissas.horizonte
    fatores = 1 / (1 + ke) ** np.arange(1, n + 1)
    patrimonio_final = float(
        resultado.patrimonio_abertura[-1]
        + resultado.lucro[-1]
        - resultado.dividendos[-1]
    )
    por_dividendos = float(
        (resultado.dividendos * fatores).sum() + patrimonio_final / (1 + ke) ** n
    )
    assert resultado.equity_value == pytest.approx(por_dividendos)


# ---------------------------------------------------------------------------
# A aritmética ano a ano
# ---------------------------------------------------------------------------


def test_o_patrimonio_cresce_pelo_lucro_retido():
    """Clean surplus: PL do ano é o do anterior mais o que não foi distribuído."""
    resultado = avaliar_lucro_residual(_premissas(), ke=0.14)
    for i in range(1, len(resultado.anos)):
        esperado = (
            resultado.patrimonio_abertura[i - 1]
            + resultado.lucro[i - 1]
            - resultado.dividendos[i - 1]
        )
        assert resultado.patrimonio_abertura[i] == pytest.approx(esperado)


def test_o_custo_do_capital_incide_sobre_o_patrimonio_de_abertura():
    """O lucro do ano foi ganho sobre o capital que estava lá no começo dele."""
    ke = 0.14
    resultado = avaliar_lucro_residual(_premissas(), ke=ke)
    esperado = resultado.lucro - ke * resultado.patrimonio_abertura
    assert resultado.lucro_residual == pytest.approx(esperado)


def test_o_valor_e_a_soma_das_tres_parcelas():
    resultado = avaliar_lucro_residual(_premissas(), ke=0.14)
    assert resultado.equity_value == pytest.approx(
        resultado.patrimonio_inicial
        + resultado.valor_presente_residual
        + resultado.valor_presente_terminal
    )


# ---------------------------------------------------------------------------
# A perpetuidade, e o que ela assume
# ---------------------------------------------------------------------------


def test_roe_perpetuo_igual_ao_ke_zera_o_terminal():
    """Não é defeito: é dizer que a vantagem não sobrevive para sempre.

    É o padrão da literatura para instituição madura, e é o padrão aqui —
    ``roe_perpetuo`` ausente cai no Ke.
    """
    ke = 0.14
    sem_premissa = avaliar_lucro_residual(_premissas(), ke=ke)
    explicito = avaliar_lucro_residual(_premissas(roe_perpetuo=ke), ke=ke)
    assert sem_premissa.valor_presente_terminal == pytest.approx(0.0, abs=1e-9)
    assert sem_premissa.equity_value == pytest.approx(explicito.equity_value)


def test_vantagem_perpetua_vale_dinheiro_e_destruicao_custa():
    """O terminal vai nos dois sentidos, e o sinal é o do excesso."""
    ke = 0.14
    ganha = avaliar_lucro_residual(_premissas(roe_perpetuo=0.17), ke=ke)
    perde = avaliar_lucro_residual(_premissas(roe_perpetuo=0.11), ke=ke)
    assert ganha.valor_presente_terminal > 0
    assert perde.valor_presente_terminal < 0
    assert ganha.equity_value > perde.equity_value


def test_o_patrimonio_carrega_a_maior_parte_do_valor():
    """A virtude do modelo, e a razão de usá-lo aqui.

    No DCF de uma indústria o valor terminal costuma valer 60% a 80% do total;
    a premissa mais frágil carrega quase tudo. Aqui a âncora contábil segura a
    maior parte, e erro na perpetuidade custa menos.
    """
    resultado = avaliar_lucro_residual(_premissas(), ke=0.14)
    assert resultado.peso_do_patrimonio > 0.70
    assert resultado.peso_do_terminal == pytest.approx(0.0, abs=1e-9)


def test_crescimento_acima_do_ke_e_recusado():
    """Mesma regra do DCF: acima disso o valor terminal é infinito."""
    with pytest.raises(CombinacaoInviavel):
        avaliar_lucro_residual(
            _premissas(crescimento_perpetuo=0.16, roe_perpetuo=0.20), ke=0.14
        )


# ---------------------------------------------------------------------------
# O que o modelo recusa a modelar
# ---------------------------------------------------------------------------


def test_patrimonio_negativo_e_recusado():
    """Sem patrimônio positivo não há âncora, e o modelo inteiro se apoia nela."""
    with pytest.raises(ValueError, match="patrimonio inicial"):
        PremissasLucroResidual(patrimonio_inicial=-10.0, roe=[0.1], payout=[0.5])


def test_payout_e_roe_precisam_ter_o_mesmo_numero_de_anos():
    with pytest.raises(ValueError, match="payout"):
        PremissasLucroResidual(
            patrimonio_inicial=100.0, roe=[0.1, 0.1], payout=[0.5]
        )


def test_payout_acima_de_cem_por_cento_e_recusado():
    """Distribuir mais que o lucro encolhe o PL, e isso se modela com ROE negativo."""
    with pytest.raises(ValueError, match="Payout"):
        PremissasLucroResidual(
            patrimonio_inicial=100.0, roe=[0.1], payout=[1.4]
        )


def test_ke_invalido_e_recusado():
    with pytest.raises(ValueError, match="Ke"):
        avaliar_lucro_residual(_premissas(), ke=0.0)


def test_a_tabela_traz_a_conta_para_conferir_a_mao():
    resultado = avaliar_lucro_residual(_premissas(), ke=0.14)
    tabela = resultado.tabela()
    assert list(tabela.index) == [
        "Patrimônio (abertura)",
        "Lucro líquido",
        "Custo do capital próprio",
        "Lucro residual",
        "Dividendos",
    ]
    # Lucro residual = lucro + custo do capital (que já vem negativo).
    assert tabela.loc["Lucro residual"].to_numpy() == pytest.approx(
        tabela.loc["Lucro líquido"].to_numpy()
        + tabela.loc["Custo do capital próprio"].to_numpy()
    )

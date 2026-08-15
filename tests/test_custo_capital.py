"""Testes do custo de capital."""

from __future__ import annotations

import pytest

from valuation import (
    PremissasCustoCapital,
    PremissasMacro,
    calcular_custo_capital,
    converter_taxa,
    desalavancar_beta,
    realavancar_beta,
)
from valuation.custo_capital import pesos_estrutura_capital


def test_hamada_ida_e_volta():
    """Desalavancar e realavancar na mesma estrutura devolve o beta original."""
    beta = 1.32
    desalavancado = desalavancar_beta(beta, divida_pl=0.6, aliquota_ir=0.34)
    assert realavancar_beta(desalavancado, 0.6, 0.34) == pytest.approx(beta)


def test_beta_desalavancado_e_menor_que_o_alavancado():
    assert desalavancar_beta(1.2, divida_pl=0.5, aliquota_ir=0.34) < 1.2


def test_beta_sem_divida_nao_muda():
    assert desalavancar_beta(0.9, divida_pl=0.0, aliquota_ir=0.34) == pytest.approx(0.9)


def test_conversao_de_moeda_por_diferencial_de_inflacao():
    # 10% em USD, com inflacao de 4% no BRL e 2% no USD.
    taxa_brl = converter_taxa(0.10, inflacao_destino=0.04, inflacao_origem=0.02)
    assert taxa_brl == pytest.approx(1.10 * 1.04 / 1.02 - 1)
    assert taxa_brl > 0.10  # inflacao local maior eleva a taxa nominal


def test_conversao_e_reversivel():
    ida = converter_taxa(0.12, 0.04, 0.023)
    assert converter_taxa(ida, 0.023, 0.04) == pytest.approx(0.12)


def test_pesos_da_estrutura_de_capital_somam_um():
    peso_divida, peso_equity = pesos_estrutura_capital(0.5)
    assert peso_divida == pytest.approx(1 / 3)
    assert peso_equity == pytest.approx(2 / 3)
    assert peso_divida + peso_equity == pytest.approx(1.0)


def test_capm_com_risco_pais(macro):
    """Confere o Ke contra a conta feita a mao, passo a passo."""
    premissas = PremissasCustoCapital(
        rf_usd=0.045,
        erp_maduro=0.045,
        risco_pais=0.025,
        beta_alavancado_setor=1.05,
        divida_pl_setor=0.45,
        divida_pl_alvo=0.50,
        spread_credito=0.025,
    )
    resultado = calcular_custo_capital(premissas, macro)

    beta_u = 1.05 / (1 + 0.66 * 0.45)
    beta_l = beta_u * (1 + 0.66 * 0.50)
    ke_usd = 0.045 + beta_l * 0.045 + 0.025
    ke_brl = (1 + ke_usd) * 1.04 / 1.023 - 1

    assert resultado.beta_desalavancado == pytest.approx(beta_u)
    assert resultado.beta_realavancado == pytest.approx(beta_l)
    assert resultado.ke_usd == pytest.approx(ke_usd)
    assert resultado.ke_brl == pytest.approx(ke_brl)


def test_wacc_pondera_ke_e_kd_apos_impostos(macro):
    premissas = PremissasCustoCapital(
        beta_desalavancado=0.8, divida_pl_alvo=1.0, custo_divida_brl=0.14
    )
    resultado = calcular_custo_capital(premissas, macro)

    assert resultado.peso_divida == pytest.approx(0.5)
    assert resultado.kd_liquido_brl == pytest.approx(0.14 * 0.66)
    assert resultado.wacc_brl == pytest.approx(
        0.5 * resultado.ke_brl + 0.5 * 0.14 * 0.66
    )


def test_wacc_sem_divida_e_igual_ao_ke(macro):
    premissas = PremissasCustoCapital(beta_desalavancado=1.0, divida_pl_alvo=0.0)
    resultado = calcular_custo_capital(premissas, macro)
    assert resultado.wacc_brl == pytest.approx(resultado.ke_brl)


def test_mais_divida_reduz_o_wacc_ate_certo_ponto(macro):
    """O beneficio fiscal da divida derruba o WACC nos primeiros niveis de alavancagem."""
    sem_divida = calcular_custo_capital(
        PremissasCustoCapital(beta_desalavancado=0.8, divida_pl_alvo=0.0), macro
    )
    com_divida = calcular_custo_capital(
        PremissasCustoCapital(beta_desalavancado=0.8, divida_pl_alvo=0.4), macro
    )
    assert com_divida.wacc_brl < sem_divida.wacc_brl
    # ... mas o custo do equity sobe, porque o acionista assume mais risco.
    assert com_divida.ke_brl > sem_divida.ke_brl


def test_lambda_modula_a_exposicao_ao_risco_pais(macro):
    base = PremissasCustoCapital(beta_desalavancado=1.0, risco_pais=0.03, lambda_pais=1.0)
    exportadora = PremissasCustoCapital(
        beta_desalavancado=1.0, risco_pais=0.03, lambda_pais=0.4
    )
    ke_base = calcular_custo_capital(base, macro).ke_usd
    ke_exp = calcular_custo_capital(exportadora, macro).ke_usd
    assert ke_base - ke_exp == pytest.approx(0.6 * 0.03)


def test_kd_sintetico_soma_risco_pais_e_spread(macro):
    premissas = PremissasCustoCapital(
        beta_desalavancado=1.0, rf_usd=0.045, risco_pais=0.025, spread_credito=0.03
    )
    resultado = calcular_custo_capital(premissas, macro)
    kd_usd = 0.045 + 0.025 + 0.03
    assert resultado.kd_bruto_brl == pytest.approx(
        (1 + kd_usd) * 1.04 / 1.023 - 1
    )


def test_beta_obrigatorio():
    with pytest.raises(ValueError, match="beta"):
        PremissasCustoCapital(beta_alavancado_setor=None, beta_desalavancado=None)


def test_percentual_em_vez_de_decimal_e_rejeitado():
    """Digitar 34 no lugar de 0.34 e o erro de premissa mais comum e mais caro."""
    with pytest.raises(ValueError, match="decimais"):
        PremissasMacro(aliquota_ir=34)

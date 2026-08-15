"""Testes da projecao de fluxos."""

from __future__ import annotations

import numpy as np
import pytest

from valuation import PremissasMacro, PremissasOperacionais, projetar


def test_receita_cresce_de_forma_composta(operacionais, macro):
    proj = projetar(operacionais, macro)
    assert proj.receita[0] == pytest.approx(1000 * 1.10)
    assert proj.receita[1] == pytest.approx(1000 * 1.10 * 1.08)
    assert proj.receita[2] == pytest.approx(1000 * 1.10 * 1.08 * 1.06)


def test_identidade_do_fcff(operacionais, macro):
    """FCFF = NOPAT + D&A - Capex - Variacao do capital de giro, ano a ano."""
    proj = projetar(operacionais, macro)
    esperado = (
        proj.nopat + proj.depreciacao - proj.capex - proj.variacao_capital_giro
    )
    assert proj.fcff == pytest.approx(esperado)


def test_imposto_incide_sobre_o_ebit(operacionais, macro):
    proj = projetar(operacionais, macro)
    assert proj.impostos == pytest.approx(proj.ebit * 0.34)
    assert proj.nopat == pytest.approx(proj.ebit * 0.66)


def test_prejuizo_nao_gera_credito_de_imposto(macro):
    """Com EBIT negativo o imposto e zero, nunca um credito positivo no fluxo."""
    operacionais = PremissasOperacionais(
        receita_base=1000.0,
        crescimento_receita=[0.0],
        margem_ebitda=[0.02],
        depreciacao_pct_receita=[0.08],  # depreciacao acima do EBITDA -> EBIT < 0
        capex_pct_receita=[0.05],
        capital_giro_pct_receita=[0.10],
    )
    proj = projetar(operacionais, macro)
    assert proj.ebit[0] < 0
    assert proj.impostos[0] == 0.0
    assert proj.nopat[0] == pytest.approx(proj.ebit[0])


def test_capital_de_giro_e_saldo_e_a_variacao_e_derivada(macro):
    """O percentual informado descreve o estoque; o fluxo e a diferenca entre estoques."""
    operacionais = PremissasOperacionais(
        receita_base=1000.0,
        crescimento_receita=[0.10, 0.10],
        margem_ebitda=[0.20, 0.20],
        depreciacao_pct_receita=[0.05, 0.05],
        capex_pct_receita=[0.05, 0.05],
        capital_giro_pct_receita=[0.10, 0.10],
    )
    proj = projetar(operacionais, macro)

    assert proj.capital_giro[0] == pytest.approx(1100 * 0.10)
    assert proj.capital_giro[1] == pytest.approx(1210 * 0.10)
    # Ano 1 parte do saldo inicial implicito de 1000 * 10% = 100.
    assert proj.variacao_capital_giro[0] == pytest.approx(110 - 100)
    assert proj.variacao_capital_giro[1] == pytest.approx(121 - 110)


def test_receita_estavel_nao_consome_capital_de_giro(macro):
    operacionais = PremissasOperacionais(
        receita_base=1000.0,
        crescimento_receita=[0.0, 0.0],
        margem_ebitda=[0.20, 0.20],
        depreciacao_pct_receita=[0.05, 0.05],
        capex_pct_receita=[0.05, 0.05],
        capital_giro_pct_receita=[0.15, 0.15],
    )
    proj = projetar(operacionais, macro)
    assert proj.variacao_capital_giro == pytest.approx(np.zeros(2))


def test_capital_de_giro_inicial_explicito_e_respeitado(macro):
    operacionais = PremissasOperacionais(
        receita_base=1000.0,
        crescimento_receita=[0.0],
        margem_ebitda=[0.20],
        depreciacao_pct_receita=[0.05],
        capex_pct_receita=[0.05],
        capital_giro_pct_receita=[0.10],
        capital_giro_inicial=50.0,
    )
    proj = projetar(operacionais, macro)
    assert proj.variacao_capital_giro[0] == pytest.approx(100 - 50)


def test_fcfe_desconta_juros_e_soma_variacao_da_divida(operacionais, macro):
    proj = projetar(
        operacionais,
        macro,
        divida_por_ano=[500.0, 550.0, 600.0],
        divida_inicial=500.0,
        custo_divida=0.12,
    )
    # Os juros incidem sobre o saldo de abertura de cada ano.
    assert proj.juros == pytest.approx(np.array([500.0, 500.0, 550.0]) * 0.12)
    assert proj.variacao_divida == pytest.approx(np.array([0.0, 50.0, 50.0]))
    assert proj.fcfe == pytest.approx(
        proj.fcff - proj.juros * 0.66 + proj.variacao_divida
    )


def test_sem_divida_o_fcfe_nao_e_calculado(operacionais, macro):
    proj = projetar(operacionais, macro)
    assert proj.fcfe is None


def test_divida_com_numero_errado_de_anos_e_rejeitada(operacionais, macro):
    with pytest.raises(ValueError, match="divida_por_ano"):
        projetar(operacionais, macro, divida_por_ano=[100.0])


def test_listas_de_tamanhos_diferentes_sao_rejeitadas():
    with pytest.raises(ValueError, match="tamanhos diferentes"):
        PremissasOperacionais(
            receita_base=1000.0,
            crescimento_receita=[0.1, 0.1],
            margem_ebitda=[0.2],
            depreciacao_pct_receita=[0.05, 0.05],
            capex_pct_receita=[0.05, 0.05],
            capital_giro_pct_receita=[0.1, 0.1],
        )


def test_tabela_tem_as_linhas_do_modelo(operacionais, macro):
    tabela = projetar(operacionais, macro).tabela()
    assert "FCFF (fluxo para a firma)" in tabela.index
    assert list(tabela.columns) == ["Ano 1", "Ano 2", "Ano 3"]

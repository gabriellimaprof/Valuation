"""Testes da avaliacao relativa por multiplos."""

from __future__ import annotations

import numpy as np
import pytest

from valuation import (
    Alvo,
    Comparavel,
    avaliar_por_multiplos,
    estatisticas,
    faixa_de_valor,
    tabela_comparaveis,
)


def test_enterprise_value_soma_a_divida_liquida():
    peer = Comparavel(nome="X", valor_mercado=1000.0, divida_liquida=500.0)
    assert peer.enterprise_value == pytest.approx(1500.0)


def test_caixa_liquido_reduz_o_enterprise_value():
    peer = Comparavel(nome="X", valor_mercado=1000.0, divida_liquida=-200.0)
    assert peer.enterprise_value == pytest.approx(800.0)


def test_multiplo_calculado():
    peer = Comparavel(
        nome="X", valor_mercado=1000.0, divida_liquida=500.0, ebitda=150.0
    )
    assert peer.multiplos()["EV/EBITDA"] == pytest.approx(10.0)


def test_ebitda_negativo_vira_nan():
    """Um multiplo com denominador negativo nao tem significado economico."""
    peer = Comparavel(nome="X", valor_mercado=1000.0, ebitda=-50.0)
    assert np.isnan(peer.multiplos()["EV/EBITDA"])


def test_ebitda_zero_vira_nan():
    peer = Comparavel(nome="X", valor_mercado=1000.0, ebitda=0.0)
    assert np.isnan(peer.multiplos()["EV/EBITDA"])


def test_comparavel_com_prejuizo_fica_fora_das_estatisticas_de_pl(comparaveis):
    """O peer com prejuizo some do P/L, mas continua contando nos multiplos de EV."""
    tabela = tabela_comparaveis(comparaveis)
    assert np.isnan(tabela.loc["Delta", "P/L"])

    resumo = estatisticas(comparaveis)
    assert resumo.loc["P/L", "n"] == 3
    assert resumo.loc["EV/EBITDA", "n"] == 4


def test_mediana_do_peer_group(comparaveis):
    resumo = estatisticas(comparaveis)
    ev_ebitda = tabela_comparaveis(comparaveis)["EV/EBITDA"]
    assert resumo.loc["EV/EBITDA", "Mediana"] == pytest.approx(ev_ebitda.median())
    assert resumo.loc["EV/EBITDA", "Minimo"] <= resumo.loc["EV/EBITDA", "Mediana"]
    assert resumo.loc["EV/EBITDA", "Mediana"] <= resumo.loc["EV/EBITDA", "Maximo"]


def test_multiplo_de_ev_passa_pela_ponte_da_divida(alvo, comparaveis):
    tabela = avaliar_por_multiplos(alvo, comparaveis)
    linha = tabela.loc["EV/EBITDA"]
    assert linha["Enterprise Value"] == pytest.approx(
        linha["Mediana do setor"] * alvo.ebitda
    )
    assert linha["Equity Value"] == pytest.approx(
        linha["Enterprise Value"] - alvo.divida_liquida
    )


def test_multiplo_de_equity_nao_passa_pela_ponte(alvo, comparaveis):
    """P/L ja produz equity; somar a divida de novo seria dupla contagem."""
    linha = avaliar_por_multiplos(alvo, comparaveis).loc["P/L"]
    assert linha["Equity Value"] == pytest.approx(
        linha["Mediana do setor"] * alvo.lucro_liquido
    )
    assert linha["Enterprise Value"] == pytest.approx(
        linha["Equity Value"] + alvo.divida_liquida
    )


def test_valor_por_acao(alvo, comparaveis):
    linha = avaliar_por_multiplos(alvo, comparaveis).loc["EV/EBITDA"]
    assert linha["Valor por acao"] == pytest.approx(linha["Equity Value"] / 150.0)


def test_alvo_com_metrica_invalida_devolve_nan(comparaveis):
    alvo_com_prejuizo = Alvo(nome="Y", ebitda=200.0, lucro_liquido=-10.0)
    tabela = avaliar_por_multiplos(alvo_com_prejuizo, comparaveis)
    assert np.isnan(tabela.loc["P/L", "Equity Value"])
    assert np.isfinite(tabela.loc["EV/EBITDA", "Equity Value"])


def test_referencia_alternativa_muda_o_valor(alvo, comparaveis):
    mediana = avaliar_por_multiplos(alvo, comparaveis, "Mediana")
    terceiro = avaliar_por_multiplos(alvo, comparaveis, "3o quartil")
    assert (
        terceiro.loc["EV/EBITDA", "Equity Value"]
        >= mediana.loc["EV/EBITDA", "Equity Value"]
    )


def test_referencia_invalida_e_rejeitada(alvo, comparaveis):
    with pytest.raises(ValueError, match="referencia"):
        avaliar_por_multiplos(alvo, comparaveis, "Moda")


def test_faixa_de_valor_e_crescente(alvo, comparaveis):
    faixa = faixa_de_valor(alvo, comparaveis, ("EV/EBITDA",)).loc["EV/EBITDA"]
    assert faixa["1o quartil"] <= faixa["Mediana"] <= faixa["3o quartil"]


def test_peer_group_vazio_e_rejeitado():
    with pytest.raises(ValueError, match="ao menos um comparavel"):
        tabela_comparaveis([])

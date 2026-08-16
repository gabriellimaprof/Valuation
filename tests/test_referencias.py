"""A base medida, e o que ela serve para dizer.

O modulo existe por causa de uma pergunta do dono do projeto: os cortes de
leitura sao absolutos ou contra pares? A resposta e os dois, e estes testes
guardam a parte que da para verificar -- que o percentil sai certo nas pontas,
no meio e fora da tabela, e que ele nunca extrapola.
"""

from __future__ import annotations

import numpy as np
import pytest

from valuation import referencias


def test_a_mediana_da_base_cai_no_percentil_50():
    _, valores = referencias.BASE["Conversao de caixa (FCO / EBITDA)"]
    mediana = valores[referencias.QUANTIS.index(0.50)]
    assert referencias.posicao("Conversao de caixa (FCO / EBITDA)", mediana) == pytest.approx(0.50)


def test_o_percentil_cresce_com_o_valor():
    indicador = "Margem EBITDA"
    anterior = -1.0
    for valor in (-0.5, 0.0, 0.10, 0.20, 0.50, 2.0):
        p = referencias.posicao(indicador, valor)
        assert p >= anterior
        anterior = p


def test_fora_da_tabela_nao_extrapola():
    """Cauda de distribuicao com margem de 300% nao se aproxima por reta."""
    assert referencias.posicao("Margem EBITDA", -50.0) == pytest.approx(0.05)
    assert referencias.posicao("Margem EBITDA", 50.0) == pytest.approx(0.95)


def test_indicador_desconhecido_e_valor_invalido_devolvem_ausencia():
    assert np.isnan(referencias.posicao("Indicador Inventado", 0.5))
    assert np.isnan(referencias.posicao("Margem EBITDA", float("nan")))
    assert referencias.descrever("Indicador Inventado", 0.5) == ""


def test_a_descricao_nomeia_as_pontas_em_vez_de_dar_percentil():
    assert "5% menores" in referencias.descrever("Margem EBITDA", -10.0)
    assert "5% maiores" in referencias.descrever("Margem EBITDA", 10.0)
    assert "percentil" in referencias.descrever("Margem EBITDA", 0.143)


def test_a_tabela_traz_o_n_de_cada_indicador():
    tabela = referencias.tabela()
    assert "n" in tabela.columns
    assert (tabela["n"] > 300).all(), "amostra pequena demais para servir de referencia"
    assert set(tabela.index) == set(referencias.BASE)


def test_gerar_referencias_reproduz_o_formato_do_modulo():
    """Refazer a medicao tem que ser um comando, nao trabalho manual."""
    import pandas as pd

    perfis = pd.DataFrame({"Margem EBITDA": np.linspace(0.0, 1.0, 101)})
    codigo = referencias.gerar_referencias(perfis)

    assert codigo.startswith("BASE: dict[str, tuple[int, tuple[float, ...]]] = {")
    assert '"Margem EBITDA": (101, (' in codigo
    # O bloco gerado tem que ser Python valido.
    ambiente: dict = {}
    exec(codigo.replace("BASE: dict[str, tuple[int, tuple[float, ...]]]", "BASE"), ambiente)
    assert ambiente["BASE"]["Margem EBITDA"][0] == 101


def test_a_qualidade_cita_a_posicao_na_base():
    """O sinal de conversao passa a dizer onde o numero cai no mercado."""
    from pathlib import Path

    from valuation.historico import analisar
    from valuation.importacao.cvm import importar_cvm
    from valuation.qualidade import avaliar_qualidade

    dados = Path(__file__).parent / "dados" / "cvm"
    analise = analisar(importar_cvm(5410, [2023, 2024], cache=dados))
    conversao = next(s for s in avaliar_qualidade(analise).sinais if s.codigo == "conversao")

    assert "percentil" in conversao.detalhe or "5%" in conversao.detalhe
    assert "companhias brasileiras" in conversao.detalhe

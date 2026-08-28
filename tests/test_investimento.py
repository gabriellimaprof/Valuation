"""A seção de investimento aberta por natureza.

A pergunta que originou isto: *"existem coisas lançadas no FCI que não são
capex, como resgates e aplicações em TVM"*. São, e em volume — e o app tinha
`capex` como conta única, com o resto da seção sem nome.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from valuation.importacao import Demonstracoes
from valuation.investimento import compor_investimento


def _com_arvore(linhas: list[tuple[str, str, float]], total: float):
    """Monta `Demonstracoes` com árvore publicada, como a CVM entrega."""
    detalhe = pd.DataFrame(
        [
            {
                "codigo": codigo,
                "rotulo": rotulo,
                "demonstracao": "dfc",
                "nivel": codigo.count(".") + 1,
                "ordem": codigo,
                2024: valor,
            }
            for codigo, rotulo, valor in linhas
        ]
    )
    valores = pd.DataFrame({2024: {"fluxo_investimento": total}})
    return Demonstracoes(empresa="Teste", valores=valores, detalhe=detalhe)


def test_tvm_nao_entra_no_capex_e_aparece_como_delta():
    """Aplicar em título é mover caixa de bolso, não investir.

    Medido no DFP consolidado de 2024: **53,5% das companhias** movimentam TVM
    dentro da seção de investimento, e a regra de capex já as recusava — mas
    elas ficavam num balde sem nome.
    """
    composicao = compor_investimento(
        _com_arvore(
            [
                ("6.02.01", "Aquisição de imobilizado", -100.0),
                ("6.02.02", "Aplicações financeiras", -500.0),
                ("6.02.03", "Resgate de aplicações financeiras", 620.0),
            ],
            total=20.0,
        )
    )
    assert composicao is not None
    assert composicao.imobilizado == pytest.approx(-100.0)
    # O delta, e nao as duas pernas: e o que de fato deixou o caixa disponivel.
    assert composicao.tvm_liquido == pytest.approx(120.0)
    assert composicao.capex == pytest.approx(-100.0)
    assert composicao.fecha


def test_o_fluxo_positivo_pode_esconder_capex():
    """Lido pelo FCI, a companhia "não investiu"; pelo capex, gastou.

    É o caso que a decomposição existe para desfazer, e ele não é raro: o TVM
    **inverte o sinal do fluxo de investimento em 28 companhias** da base de
    2024 — a EZ Tec publica +30,4 e teria −1.535,6 sem os resgates.
    """
    composicao = compor_investimento(
        _com_arvore(
            [
                ("6.02.01", "Aquisição de imobilizado", -703.0),
                ("6.02.02", "Resgates de títulos e valores mobiliários", 1041.0),
            ],
            total=338.0,
        )
    )
    assert composicao.total_publicado > 0, "o fluxo publicado é positivo"
    assert composicao.capex < 0, "e ainda assim houve capex"
    assert composicao.tvm_liquido == pytest.approx(1041.0)


def test_participacao_nao_e_capex():
    """Comprar empresa consome o mesmo caixa e não repõe ativo operacional.

    Projetar manutenção a partir de um ano com aquisição a superestima para
    sempre — por isso participação tem balde próprio, e não entra em `capex`.
    """
    composicao = compor_investimento(
        _com_arvore(
            [
                ("6.02.01", "Aquisição de imobilizado", -100.0),
                ("6.02.02", "Aquisição de empresa - combinação de negócios", -900.0),
                ("6.02.03", "Aquisição de participação societária - coligadas", -50.0),
            ],
            total=-1050.0,
        )
    )
    assert composicao.capex == pytest.approx(-100.0)
    assert composicao.participacoes == pytest.approx(-950.0)


def test_venda_de_imobilizado_nao_reduz_o_capex():
    """Capex líquido de desinvestimento subestima o desembolso de manutenção."""
    composicao = compor_investimento(
        _com_arvore(
            [
                ("6.02.01", "Aquisição de imobilizado", -100.0),
                ("6.02.02", "Recebimento na venda de ativo imobilizado", 30.0),
            ],
            total=-70.0,
        )
    )
    assert composicao.capex == pytest.approx(-100.0), "o capex é o desembolso"
    assert composicao.outros_nao_capex == pytest.approx(30.0)


def test_so_a_linha_mais_externa_entra():
    """Somar pai e filha conta o mesmo desembolso duas vezes."""
    composicao = compor_investimento(
        _com_arvore(
            [
                ("6.02.01", "Imobilizado", -100.0),
                ("6.02.01.01", "Aquisição de máquinas", -60.0),
                ("6.02.01.02", "Aquisição de edificações", -40.0),
            ],
            total=-100.0,
        )
    )
    assert composicao.imobilizado == pytest.approx(-100.0)
    assert composicao.fecha


def test_o_residuo_material_e_declarado():
    """Decomposição que não reconstrói o total descreve outra companhia.

    Ela fecha por construção — `nao_classificado` absorve o resíduo —, então o
    que `fecha` responde é se o resíduo é **material**. Medido na base: 443 das
    447 companhias com árvore ficam abaixo de 1%.
    """
    composicao = compor_investimento(
        _com_arvore([("6.02.01", "Aquisição de imobilizado", -100.0)], total=-500.0)
    )
    assert not composicao.fecha
    assert composicao.nao_classificado == pytest.approx(-400.0)
    assert composicao.soma == pytest.approx(composicao.total_publicado)


def test_sem_arvore_publicada_nao_ha_composicao():
    """A abertura não existe em conta canônica: ou há árvore, ou não há peça."""
    valores = pd.DataFrame({2024: {"fluxo_investimento": -100.0}})
    assert compor_investimento(Demonstracoes(empresa="X", valores=valores)) is None

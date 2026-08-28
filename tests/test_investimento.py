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


def test_venda_de_ativo_nao_reduz_o_capex_mas_entra_no_caixa():
    """As duas coisas são verdade ao mesmo tempo, e o app precisa das duas.

    Capex líquido de desinvestimento subestima o desembolso de manutenção — por
    isso a venda não abate o capex. **Mas o dinheiro entrou**, e ignorá-lo
    subestima o caixa que a companhia gerou.

    Medido no DFP consolidado, 2021 a 2024: 180 companhias têm venda de ativo no
    FCI e **114 (63%) a repetem em três dos quatro exercícios** — não é evento
    pontual na maioria. Em 34 de 161 medidas ela passa de 10% do fluxo livre: na
    Ultrapar são R$ 1.386,3 mi contra R$ 682,8 mi de FCL.
    """
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
    # Linha propria, e nao diluida em "outros": e o numero que o analista soma.
    assert composicao.venda_de_ativos == pytest.approx(30.0)
    assert composicao.outros_nao_capex == pytest.approx(0.0)

    # E as duas leituras do caixa livre, sem escolher entre elas.
    sem, com = composicao.caixa_livre(fluxo_operacional=250.0)
    assert sem == pytest.approx(150.0)   # 250 − 100 de capex
    assert com == pytest.approx(180.0)   # mais os 30 que entraram


def test_as_duas_leituras_do_caixa_livre_coincidem_sem_venda():
    """Sem reciclagem de ativo, não há por que a leitura mudar."""
    composicao = compor_investimento(
        _com_arvore([("6.02.01", "Aquisição de imobilizado", -100.0)], total=-100.0)
    )
    sem, com = composicao.caixa_livre(fluxo_operacional=250.0)
    assert sem == pytest.approx(com)


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


def test_entrada_nao_e_so_venda_de_imobilizado():
    """Venda de participação, dividendo e juro recebido também geram caixa.

    A primeira versão só marcava entrada dentro do balde de imobilizado, e por
    isso a **Ultrapar saía com venda zero**: a linha dela é "Caixa gerado com a
    venda de investimento e bens", que caía em participações sem que ninguém
    notasse que era entrada. Direção é eixo próprio, não detalhe de uma natureza.
    """
    composicao = compor_investimento(
        _com_arvore(
            [
                ("6.02.01", "Aquisição de imobilizado", -100.0),
                ("6.02.02", "Alienação de investimentos em coligadas", 400.0),
                ("6.02.03", "Dividendos recebidos", 40.0),
                ("6.02.04", "Redução de capital em controladas", 10.0),
            ],
            total=350.0,
        )
    )
    assert composicao.capex == pytest.approx(-100.0)
    # Reducao de capital em controlada e **retorno de investimento**, e cai no
    # mesmo balde da alienacao: as duas devolvem capital que estava na investida.
    assert composicao.venda_de_investimentos == pytest.approx(410.0)
    assert composicao.proventos_recebidos == pytest.approx(40.0)
    assert composicao.outras_entradas == pytest.approx(0.0)
    # O que importa para o caixa e a soma delas.
    assert composicao.entradas == pytest.approx(450.0)
    assert composicao.fecha

    sem, com = composicao.caixa_livre(fluxo_operacional=1000.0)
    assert sem == pytest.approx(900.0)
    assert com == pytest.approx(1350.0)


def test_recorrencia_separa_reciclagem_de_evento():
    """A frequência é a única evidência que os dados oferecem, e ela sugere.

    Companhia que recicla ativo como parte do negócio — shopping, locadora,
    incorporadora — gera caixa ali todo ano, e ler o fluxo livre sem isso a
    subestima. Quem vendeu a sede uma vez tem o oposto.

    Medido no DFP consolidado de 2021 a 2024: das 180 companhias com venda de
    ativo no FCI, **114 (63%) a repetem em três dos quatro exercícios**.
    """
    import numpy as np

    from valuation.investimento import recorrencia_das_entradas

    detalhe = pd.DataFrame(
        [
            {
                "codigo": "6.02.01",
                "rotulo": "Dividendos recebidos",
                "demonstracao": "dfc",
                "nivel": 3,
                "ordem": "6.02.01",
                2022: 30.0,
                2023: 35.0,
                2024: 40.0,
            },
            {
                "codigo": "6.02.02",
                "rotulo": "Recebimento na venda de ativo imobilizado",
                "demonstracao": "dfc",
                "nivel": 3,
                "ordem": "6.02.02",
                2022: 0.0,
                2023: 0.0,
                2024: 500.0,
            },
        ]
    )
    valores = pd.DataFrame(
        {a: {"fluxo_investimento": 0.0} for a in (2022, 2023, 2024)}
    )
    d = Demonstracoes(empresa="X", valores=valores, detalhe=detalhe)

    por_natureza = {r.natureza: r for r in recorrencia_das_entradas(d)}
    proventos = por_natureza["Dividendos e juros recebidos"]
    assert proventos.anos_com == 3 and proventos.recorre
    assert "parte do negócio" in proventos.leitura

    venda = por_natureza["Venda de ativo (imobilizado, intangível)"]
    assert venda.anos_com == 1 and not venda.recorre
    assert "evento" in venda.leitura

    # Natureza que nunca apareceu nao vira linha vazia.
    assert "Venda de investimentos (participações)" not in por_natureza


def test_rotulo_que_cita_ativo_fixo_e_capex_mesmo_dizendo_investimento():
    """A palavra "investimento" atravessa as duas naturezas, e a ordem decide.

    Alargar participações para o "investimento" solto foi necessário -- "Alienação
    de investimentos" e "Baixa de investimentos" enchiam o balde genérico --, mas
    capturou linhas que **são** capex e citam a palavra de passagem. Medido contra
    a base: a concordância com a conta somada caiu justamente nas duas abaixo, e
    o capex delas foi a zero.

    Rótulo que cita ativo fixo **é** ativo fixo; só quando não cita nenhum é que
    "investimento" sozinho significa participação.
    """
    dem = _com_arvore(
        [
            ("6.02", "Caixa das atividades de investimento", -5_720.3),
            ("6.02.08", "Adições ao imobilizado, intangível e investimento", -5_492.7),
            ("6.02.03", "Adições ao ativo imobilizado para investimento", -227.6),
        ],
        total=-5_720.3,
    )
    composicao = compor_investimento(dem, 2024)

    assert composicao.capex == pytest.approx(-5_720.3)
    assert composicao.participacoes == 0.0


def test_investimento_sozinho_continua_sendo_participacao():
    """O contrapeso do teste acima: sem ativo fixo no rótulo, a palavra vale."""
    dem = _com_arvore(
        [
            ("6.02", "Caixa das atividades de investimento", 300.0),
            ("6.02.01", "Alienação de investimentos", 300.0),
        ],
        total=300.0,
    )
    composicao = compor_investimento(dem, 2024)

    assert composicao.capex == 0.0
    assert composicao.venda_de_investimentos == pytest.approx(300.0)

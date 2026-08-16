"""Testes da comparacao entre duas versoes do mesmo valuation.

A regra que importa: as parcelas tem que somar o movimento inteiro. Uma ponte
que nao fecha e pior que ponte nenhuma, porque parece explicar o que nao
explica.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from valuation import avaliar
from valuation.comparacao import comparar


def test_versoes_iguais_nao_tem_movimento(empresa_exemplo):
    resultado = comparar(empresa_exemplo, empresa_exemplo)
    assert resultado.movimentos == []
    assert resultado.variacao == pytest.approx(0.0)
    assert resultado.fecha()


def test_uma_premissa_explica_o_movimento_inteiro(empresa_exemplo):
    depois = replace(
        empresa_exemplo,
        perpetuidade=replace(
            empresa_exemplo.perpetuidade, crescimento_perpetuo=0.035
        ),
    )
    resultado = comparar(empresa_exemplo, depois)

    assert len(resultado.movimentos) == 1
    movimento = resultado.movimentos[0]
    assert movimento.caminho == "perpetuidade.crescimento_perpetuo"
    assert movimento.antes == pytest.approx(0.045)
    assert movimento.depois == pytest.approx(0.035)
    # Crescer menos para sempre vale menos.
    assert movimento.efeito < 0
    assert movimento.efeito == pytest.approx(resultado.variacao)
    assert resultado.fecha()


def test_a_ponte_fecha_com_varias_premissas(empresa_exemplo):
    """Com premissas que interagem, as parcelas ainda somam o total."""
    depois = replace(
        empresa_exemplo,
        perpetuidade=replace(
            empresa_exemplo.perpetuidade, crescimento_perpetuo=0.03
        ),
        operacionais=replace(
            empresa_exemplo.operacionais,
            margem_ebitda=[0.25, 0.25, 0.25],
            capex_pct_receita=[0.08, 0.075, 0.07],
        ),
        ponte=replace(empresa_exemplo.ponte, divida_bruta=1200.0),
    )
    resultado = comparar(empresa_exemplo, depois)

    assert len(resultado.movimentos) >= 4
    assert resultado.fecha(), (
        f"parcelas somam {sum(m.efeito for m in resultado.movimentos)}, "
        f"variacao e {resultado.variacao}"
    )
    assert abs(resultado.nao_atribuido) < abs(resultado.variacao) * 1e-6 + 1.0


def test_as_pontas_batem_com_avaliar(empresa_exemplo):
    """Os extremos da ponte sao os valores das duas versoes, sem aproximacao."""
    depois = replace(empresa_exemplo, ponte=replace(empresa_exemplo.ponte, caixa=900.0))
    resultado = comparar(empresa_exemplo, depois)

    assert resultado.valor_antes == pytest.approx(avaliar(empresa_exemplo).equity_value)
    assert resultado.valor_depois == pytest.approx(avaliar(depois).equity_value)


def test_nome_e_unidade_nao_contam_como_mudanca(empresa_exemplo):
    """Renomear a empresa nao e mudanca de premissa."""
    depois = replace(empresa_exemplo, nome="Outro Nome S.A.", unidade="R$ mil")
    assert comparar(empresa_exemplo, depois).movimentos == []


def test_movimentos_ordenados_pelo_que_mais_moveu(empresa_exemplo):
    depois = replace(
        empresa_exemplo,
        perpetuidade=replace(empresa_exemplo.perpetuidade, crescimento_perpetuo=0.02),
        ponte=replace(empresa_exemplo.ponte, contingencias=61.0),
    )
    resultado = comparar(empresa_exemplo, depois)
    efeitos = [abs(m.efeito) for m in resultado.por_efeito]
    assert efeitos == sorted(efeitos, reverse=True)
    # Mexer em g move muito mais que mexer em uma contingencia de 1.
    assert resultado.por_efeito[0].caminho == "perpetuidade.crescimento_perpetuo"


def test_variacao_relativa(empresa_exemplo):
    depois = replace(empresa_exemplo, ponte=replace(empresa_exemplo.ponte, caixa=1250.0))
    resultado = comparar(empresa_exemplo, depois)
    esperado = resultado.variacao / abs(resultado.valor_antes)
    assert resultado.variacao_relativa == pytest.approx(esperado)


def test_premissa_inviavel_no_meio_nao_derruba_a_comparacao(empresa_exemplo):
    """g acima do WACC num passo intermediario vira efeito NaN, nao excecao."""
    depois = replace(
        empresa_exemplo,
        perpetuidade=replace(empresa_exemplo.perpetuidade, crescimento_perpetuo=0.99),
    )
    resultado = comparar(empresa_exemplo, depois)
    assert len(resultado.movimentos) == 1
    assert not np.isfinite(resultado.valor_depois) or resultado.valor_depois == 0
    # Nao levantou excecao, que e o ponto.


def test_lista_de_premissas_anuais_conta_como_uma_mudanca(empresa_exemplo):
    depois = replace(
        empresa_exemplo,
        operacionais=replace(
            empresa_exemplo.operacionais, crescimento_receita=[0.12, 0.08, 0.06]
        ),
    )
    resultado = comparar(empresa_exemplo, depois)
    caminhos = [m.caminho for m in resultado.movimentos]
    assert caminhos == ["operacionais.crescimento_receita"]
    assert resultado.movimentos[0].antes == [0.10, 0.08, 0.06]


def test_convencoes_sao_respeitadas(empresa_exemplo):
    """Comparar sob meio de ano tem que bater com avaliar sob meio de ano."""
    depois = replace(empresa_exemplo, ponte=replace(empresa_exemplo.ponte, caixa=400.0))
    resultado = comparar(empresa_exemplo, depois, meio_de_ano=False)
    assert resultado.valor_antes == pytest.approx(
        avaliar(empresa_exemplo, meio_de_ano=False).equity_value
    )

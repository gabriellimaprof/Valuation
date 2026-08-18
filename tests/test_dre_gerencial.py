"""A DRE na forma em que o analista a monta.

A CVM publica a DRE numa arvore que serve para fiscalizar, nao para modelar:
``3.04`` e um bloco unico -- "Despesas/Receitas Operacionais" -- que junta SG&A,
impairment, outras receitas, outras despesas e equivalencia patrimonial. Quem
projeta precisa dos cinco separados, porque tres deles nao se repetem e um nao e
operacional.

A ponte montada aqui e a do dono do projeto::

    ROL - Custos = LB
    LB - SG&A + equivalencia + outros = EBIT
    EBIT + D&A = EBITDA
    EBITDA + ajustes = EBITDA ajustado
    EBIT +/- resultado financeiro = LAIR
    LAIR - impostos = LL

O teste que importa e um so, e vale para qualquer companhia: **cada subtotal
tem que bater com a soma das linhas acima dele**. A ponte e montada por
subtracao em varios pontos -- SG&A sai do bloco 3.04, derivativos saem por
residuo do resultado financeiro --, e subtracao com sinal trocado produz uma
DRE que parece certa e nao fecha.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from valuation.importacao import Demonstracoes

DADOS = Path(__file__).parent / "dados" / "cvm"


@pytest.fixture(scope="module")
def weg() -> Demonstracoes:
    from valuation.importacao.cvm import importar_cvm

    return importar_cvm(5410, [2023, 2024], cache=DADOS)


def _dre(**contas) -> Demonstracoes:
    base = {
        "receita_liquida": 1000.0,
        "custo_produtos_vendidos": 600.0,
        "lucro_bruto": 400.0,
        "despesas_operacionais": 200.0,
        "ebit": 200.0,
        "depreciacao_amortizacao": 50.0,
        "resultado_financeiro": -30.0,
        "receitas_financeiras": 20.0,
        "despesas_financeiras": 50.0,
        "lucro_antes_impostos": 170.0,
        "imposto_corrente": -40.0,
        "imposto_diferido": -10.0,
        "lucro_liquido": 120.0,
    }
    base.update(contas)
    return Demonstracoes(empresa="Teste", valores=pd.DataFrame({2024: base}))


# ---------------------------------------------------------------------------
# A ponte fecha
# ---------------------------------------------------------------------------


def test_todos_os_subtotais_fecham_num_caso_limpo():
    conferencia = _dre().conferir_dre_gerencial()
    assert (conferencia.fillna(0) < 1e-9).all().all(), conferencia.to_string()


def test_a_ordem_das_linhas_e_a_da_especificacao():
    dre = _dre().dre_gerencial()
    esperado = [
        "Receita líquida",
        "(−) Custos",
        "= Lucro bruto",
        "(−) SG&A",
        "(+/−) Equivalência patrimonial",
        "(+/−) Outros",
        "= EBIT",
        "(+) D&A",
        "= EBITDA",
        "(−) Itens não recorrentes",
        "= EBITDA ajustado",
        "(+) Receitas financeiras",
        "(−) Despesas financeiras",
        "(+/−) Derivativos e câmbio",
        "= LAIR",
        "IR corrente",
        "IR diferido",
        "= Operações continuadas",
        "(+/−) Operações descontinuadas",
        "= Lucro líquido consolidado",
        "(−) Não controladores",
        "= Controladores",
    ]
    assert list(dre.index) == esperado


def test_o_sga_sai_por_subtracao_do_bloco_3_04():
    """3.04 junta SG&A com impairment, outras e equivalencia.

    As contas 3.04.01 e 3.04.02 so existem em 297 e 454 das 467 companhias;
    3.04 existe em todas. Por isso o SG&A e obtido tirando do bloco o que nao e
    SG&A, e nao somando as duas filhas.
    """
    dre = _dre(
        despesas_operacionais=200.0,
        impairment=-30.0,
        outras_receitas_operacionais=50.0,
        outras_despesas_operacionais=-20.0,
        equivalencia_patrimonial=10.0,
    ).dre_gerencial()

    # bloco (magnitude 200) + (-30 + 50 - 20) + 10 = 210 de SG&A
    assert dre.loc["(−) SG&A", 2024] == pytest.approx(-210.0)
    assert dre.loc["(+/−) Outros", 2024] == pytest.approx(0.0)
    assert dre.loc["(+/−) Equivalência patrimonial", 2024] == pytest.approx(10.0)


def test_o_ebitda_ajustado_tira_o_que_nao_se_repete():
    dre = _dre(outras_receitas_operacionais=60.0, ebit=200.0).dre_gerencial()
    assert dre.loc["= EBITDA", 2024] == pytest.approx(250.0)
    assert dre.loc["= EBITDA ajustado", 2024] == pytest.approx(190.0)


def test_derivativos_saem_por_residuo_do_resultado_financeiro():
    """Nao ha codigo padronizado; quando a companhia abre, cai em codigo livre."""
    dre = _dre(
        resultado_financeiro=-45.0, receitas_financeiras=20.0, despesas_financeiras=50.0
    ).dre_gerencial()
    # -45 - 20 + 50 = -15 de derivativos e cambio
    assert dre.loc["(+/−) Derivativos e câmbio", 2024] == pytest.approx(-15.0)

    sem = _dre().dre_gerencial()
    assert sem.loc["(+/−) Derivativos e câmbio", 2024] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Os dois erros de sinal que a ponte revelou
# ---------------------------------------------------------------------------


def test_imposto_diferido_credito_nao_vira_despesa():
    """Na WEG de 2023 o diferido foi credito de R$ 404,8 mi.

    Guardado como magnitude, ele somava com o corrente e a ponte dava
    R$ 1.532,7 mi de imposto contra os R$ 723,2 mi publicados. Nenhuma outra
    verificacao acusava.
    """
    dre = _dre(
        lucro_antes_impostos=170.0,
        imposto_corrente=-60.0,
        imposto_diferido=10.0,  # credito
        lucro_liquido=120.0,
    ).dre_gerencial()

    assert dre.loc["IR corrente", 2024] == pytest.approx(-60.0)
    assert dre.loc["IR diferido", 2024] == pytest.approx(10.0)
    assert dre.loc["= Operações continuadas", 2024] == pytest.approx(120.0)


def test_operacoes_descontinuadas_entram_na_ponte():
    """LAIR menos impostos da o resultado **continuado**, nao o consolidado."""
    dre = _dre(
        lucro_antes_impostos=170.0,
        imposto_corrente=-40.0,
        imposto_diferido=-10.0,
        operacoes_descontinuadas=30.0,
        lucro_liquido=150.0,
    ).dre_gerencial()

    assert dre.loc["= Operações continuadas", 2024] == pytest.approx(120.0)
    assert dre.loc["= Lucro líquido consolidado", 2024] == pytest.approx(150.0)
    conferencia = _dre(
        lucro_antes_impostos=170.0,
        imposto_corrente=-40.0,
        imposto_diferido=-10.0,
        operacoes_descontinuadas=30.0,
        lucro_liquido=150.0,
    ).conferir_dre_gerencial()
    assert (conferencia.fillna(0) < 1e-9).all().all()


def test_controladores_e_o_consolidado_menos_minoritarios():
    dre = _dre(lucro_liquido=120.0, lucro_nao_controladores=20.0).dre_gerencial()
    assert dre.loc["= Controladores", 2024] == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# Contra a companhia real
# ---------------------------------------------------------------------------


def test_a_ponte_fecha_na_weg(weg):
    conferencia = weg.conferir_dre_gerencial()
    pior = float(np.nanmax(conferencia.to_numpy(dtype=float)))
    assert pior < 1e-9, conferencia.to_string()


def test_os_numeros_da_weg_batem_com_a_dre_publicada(weg):
    dre = weg.dre_gerencial()
    assert dre.loc["Receita líquida", 2024] == pytest.approx(37_986_941_000.0)
    assert dre.loc["= EBIT", 2024] == pytest.approx(7_690_528_000.0)
    assert dre.loc["= EBITDA", 2024] == pytest.approx(8_503_013_000.0)
    # O EBITDA ajustado tira os itens que nao se repetem, entao supera o EBITDA
    # quando eles foram perda -- que e o caso da WEG.
    assert dre.loc["= EBITDA ajustado", 2024] > dre.loc["= EBITDA", 2024]


def test_os_subtotais_sao_declarados_para_a_tela(weg):
    """A tela destaca os subtotais; a regra fica num lugar so."""
    dre = weg.dre_gerencial()
    for nome in weg.SUBTOTAIS_DRE:
        assert nome in dre.index


def test_holding_com_bloco_operacional_positivo_fecha():
    """Numa holding a equivalencia supera as despesas e 3.04 fica **positivo**.

    ``despesas_operacionais`` e guardada como magnitude, entao o sinal se perde
    e o SG&A saía com a ordem de grandeza do lucro de coligadas -- na Itausa,
    R$ 14 bi. O bloco passa a vir de ``EBIT - lucro bruto``, que e identidade.
    """
    holding = _dre(
        receita_liquida=100.0,
        custo_produtos_vendidos=60.0,
        lucro_bruto=40.0,
        despesas_operacionais=1000.0,  # magnitude de um bloco POSITIVO
        equivalencia_patrimonial=1050.0,
        ebit=1040.0,
        depreciacao_amortizacao=0.0,
        resultado_financeiro=0.0,
        receitas_financeiras=0.0,
        despesas_financeiras=0.0,
        lucro_antes_impostos=1040.0,
        imposto_corrente=-40.0,
        imposto_diferido=0.0,
        lucro_liquido=1000.0,
    )
    dre = holding.dre_gerencial()
    # SG&A de verdade: 40 - 1040 + 1050 = 50 de despesa
    assert dre.loc["(−) SG&A", 2024] == pytest.approx(-50.0)
    conferencia = holding.conferir_dre_gerencial()
    assert (conferencia.fillna(0) < 1e-9).all().all(), conferencia.to_string()


def test_a_ponte_acusa_demonstracao_que_nao_reconcilia():
    """A Azul publicou 3.11.01 positivo com 3.11 negativo, em 2024.

    Nao e erro de leitura: a demonstracao dela nao fecha consigo mesma. A ponte
    tem que **acusar**, e nao consertar em silencio -- consertar esconderia do
    analista que a companhia publicou algo inconsistente.
    """
    inconsistente = _dre(lucro_liquido=-900.0, lucro_controladores=+910.0)
    conferencia = inconsistente.conferir_dre_gerencial()
    assert conferencia.loc["Controladores", 2024] > 0.5

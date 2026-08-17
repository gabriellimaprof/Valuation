"""O que se repete, e o que aconteceu uma vez.

Reversao de impairment, venda de ativo, ganho tributario e ganho judicial
entram na DRE **do SG&A para baixo**, e podem fazer EBIT, LAIR e lucro liquido
superarem o lucro bruto. Isso e contabilmente correto e economicamente
enganoso: nada disso se repete no ano seguinte.

Medido na base de 2024, 165 de 172 companhias tem item nao recorrente diferente
de zero, com peso mediano de 17,4% do EBIT. Projetar margem a partir do EBIT
reportado, nessa metade da base, e projetar o evento.

Um cuidado que os testes travam: o ajuste vai **nos dois sentidos**. Quando o
item foi uma perda -- impairment na Vale --, a margem recorrente e maior que a
reportada, e nao menor.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from valuation import avaliar
from valuation.casos_especiais import ver_recorrente
from valuation.diagnostico import diagnosticar
from valuation.historico import analisar
from valuation.importacao import Demonstracoes

DADOS = Path(__file__).parent / "dados" / "cvm"


def _dre(**contas) -> Demonstracoes:
    base = {
        "receita_liquida": 1000.0,
        "custo_produtos_vendidos": 600.0,
        "lucro_bruto": 400.0,
        "ebit": 200.0,
        "lucro_liquido": 120.0,
        "ativo_total": 2000.0,
        "patrimonio_liquido": 900.0,
    }
    base.update(contas)
    return Demonstracoes(empresa="Teste", valores=pd.DataFrame({2023: base, 2024: base}))


# ---------------------------------------------------------------------------
# A separacao
# ---------------------------------------------------------------------------


def test_ganho_nao_recorrente_sai_do_ebit():
    """Ganho de R$ 80 no EBIT de R$ 200: o recorrente e R$ 120."""
    visao = ver_recorrente(analisar(_dre(outras_receitas_operacionais=80.0)))
    assert visao.ebit_recorrente[2024] == pytest.approx(120.0)
    assert visao.margem_ebit_recorrente[2024] == pytest.approx(0.12)
    assert visao.peso == pytest.approx(0.40)


def test_perda_nao_recorrente_aumenta_o_recorrente():
    """O ajuste vai nos dois sentidos -- e o caso da Vale, com impairment.

    Se o item foi perda, o resultado que se repete e **melhor** que o
    reportado. Um ajuste que so soubesse tirar ganho subestimaria a empresa.
    """
    visao = ver_recorrente(analisar(_dre(impairment=-150.0)))
    assert visao.ebit_recorrente[2024] == pytest.approx(350.0)
    assert visao.margem_ebit_recorrente[2024] > visao.margem_ebit[2024]


def test_impairment_e_outras_somam_com_o_sinal_publicado():
    visao = ver_recorrente(
        analisar(
            _dre(
                impairment=-50.0,
                outras_receitas_operacionais=90.0,
                outras_despesas_operacionais=-30.0,
            )
        )
    )
    # -50 + 90 - 30 = +10 de ganho liquido nao recorrente
    assert visao.nao_recorrente[2024] == pytest.approx(10.0)
    assert visao.ebit_recorrente[2024] == pytest.approx(190.0)


def test_sem_itens_destacados_o_recorrente_e_o_reportado():
    visao = ver_recorrente(analisar(_dre()))
    assert visao.ebit_recorrente[2024] == pytest.approx(visao.ebit[2024])
    assert not visao.relevante


def test_sem_ebit_nao_ha_o_que_separar():
    vazia = Demonstracoes(
        empresa="X", valores=pd.DataFrame({2024: {"receita_liquida": 1000.0}})
    )
    assert ver_recorrente(analisar(vazia)) is None


def test_a_equivalencia_fica_de_fora_da_subtracao():
    """Para holding e o negocio; para industria e resultado que nao gera caixa.

    Excluir por padrao acertaria numa e erraria na outra, entao ela aparece
    separada.
    """
    visao = ver_recorrente(analisar(_dre(equivalencia_patrimonial=300.0)))
    assert visao.ebit_recorrente[2024] == pytest.approx(200.0)
    assert visao.equivalencia[2024] == pytest.approx(300.0)


def test_os_anos_com_lucro_acima_do_bruto_sao_listados():
    visao = ver_recorrente(analisar(_dre(lucro_liquido=500.0)))
    assert visao.anos_com_lucro_acima_do_bruto() == [2023, 2024]

    normal = ver_recorrente(analisar(_dre()))
    assert normal.anos_com_lucro_acima_do_bruto() == []


# ---------------------------------------------------------------------------
# Os indicadores
# ---------------------------------------------------------------------------


def test_a_margem_recorrente_entra_no_historico():
    analise = analisar(_dre(outras_receitas_operacionais=80.0))
    assert "Margem EBIT recorrente" in analise.indicadores.index
    assert "Itens nao recorrentes / EBIT" in analise.indicadores.index
    assert analise.mediana("Margem EBIT recorrente") == pytest.approx(0.12)


def test_sem_itens_o_indicador_nao_aparece():
    """Indicador que existe sempre, mesmo valendo zero, e ruido na tabela."""
    analise = analisar(_dre())
    assert "Margem EBIT recorrente" not in analise.indicadores.index


# ---------------------------------------------------------------------------
# O diagnostico
# ---------------------------------------------------------------------------


def test_ebit_dependente_de_nao_recorrente_vira_alerta(empresa_exemplo):
    analise = analisar(_dre(outras_receitas_operacionais=80.0))
    codigos = {a.codigo for a in diagnosticar(avaliar(empresa_exemplo), analise=analise).achados}
    assert "ebit_depende_de_nao_recorrente" in codigos


def test_lucro_acima_do_bruto_e_informacao_e_nao_erro(empresa_exemplo):
    """Contabilmente pode acontecer; o achado explica, nao acusa."""
    analise = analisar(_dre(lucro_liquido=500.0))
    achado = next(
        a
        for a in diagnosticar(avaliar(empresa_exemplo), analise=analise).achados
        if a.codigo == "lucro_acima_do_lucro_bruto"
    )
    assert achado.severidade == "informacao"
    assert "não indica erro" in achado.detalhe
    assert "impairment" in achado.detalhe


def test_a_causa_aponta_equivalencia_quando_e_o_caso(empresa_exemplo):
    """Itausa tem lucro liquido acima do bruto porque vive de coligadas."""
    analise = analisar(_dre(lucro_liquido=500.0, equivalencia_patrimonial=400.0))
    achado = next(
        a
        for a in diagnosticar(avaliar(empresa_exemplo), analise=analise).achados
        if a.codigo == "lucro_acima_do_lucro_bruto"
    )
    assert "equivalência patrimonial" in achado.detalhe


def test_pouco_nao_recorrente_nao_gera_alerta(empresa_exemplo):
    analise = analisar(_dre(outras_receitas_operacionais=5.0))
    codigos = {a.codigo for a in diagnosticar(avaliar(empresa_exemplo), analise=analise).achados}
    assert "ebit_depende_de_nao_recorrente" not in codigos


# ---------------------------------------------------------------------------
# Contra a base real
# ---------------------------------------------------------------------------


def test_companhia_de_verdade_com_impairment():
    """A leitura tem que vir dos codigos padronizados, sem adivinhar rotulo."""
    from valuation.importacao.cvm import importar_cvm

    cache = Path.home() / ".cache" / "valuation" / "cvm"
    if not (cache / "dfp_cia_aberta_2024.zip").exists():
        pytest.skip("cache da CVM sem o zip de 2024")

    analise = analisar(importar_cvm(4170, [2023, 2024], cache=cache))  # Vale
    visao = ver_recorrente(analise)
    assert visao is not None
    assert np.isfinite(visao.peso)
    # Na Vale o item foi perda: a margem recorrente supera a reportada.
    assert visao.margem_ebit_recorrente.dropna().iloc[-1] > visao.margem_ebit.dropna().iloc[-1]

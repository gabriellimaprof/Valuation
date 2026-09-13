"""O setor do cadastro da CVM vira setor do app, e o derivativo se le da arvore."""

from __future__ import annotations

import pandas as pd
import pytest

from valuation.dados_setoriais import (
    BETA_DESALAVANCADO_SEM_SETOR,
    POR_NOME,
    setor_do_cadastro,
)
from valuation.importacao.aplicacoes import derivativos_no_balanco


@pytest.mark.parametrize(
    ("cadastro", "setor"),
    [
        ("Metalurgia e Siderurgia", "Siderurgia e metalurgia"),  # CSN
        ("Emp. Adm. Part. - Energia Elétrica", "Energia eletrica"),
        ("Serviços Médicos", "Farmaceutico e saude"),
        ("Comércio (Atacado e Varejo)", "Varejo"),
    ],
)
def test_o_setor_do_cadastro_se_traduz(cadastro, setor):
    assert setor_do_cadastro(cadastro).nome == setor


@pytest.mark.parametrize(
    "cadastro",
    [
        "",
        None,
        "Emp. Adm. Part. - Sem Setor Principal",
        "Hospedagem e Turismo",
        # Financeiro no cadastro nao vira banco: isso trocaria o metodo inteiro.
        "Intermediação Financeira",
        "Emp. Adm. Part. - Bancos",
    ],
)
def test_sem_par_ou_financeiro_fica_sem_setor(cadastro):
    assert setor_do_cadastro(cadastro) is None


def test_o_beta_sem_setor_e_a_mediana_da_tabela_e_nao_um():
    naos_financeiros = sorted(
        s.beta_desalavancado for s in POR_NOME.values() if not s.financeiro
    )
    assert min(naos_financeiros) <= BETA_DESALAVANCADO_SEM_SETOR <= max(naos_financeiros)
    assert BETA_DESALAVANCADO_SEM_SETOR != 1.0


def _arvore(linhas: dict[str, tuple[str, float]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "codigo": codigo,
                "rotulo": rotulo,
                "demonstracao": "bp",
                "nivel": codigo.count(".") + 1,
                "ordem": tuple(int(p) for p in codigo.split(".")),
                2024: valor,
            }
            for codigo, (rotulo, valor) in linhas.items()
        ]
    )


def test_o_swap_da_localiza_se_le_do_ativo_e_do_passivo():
    """2.164,4 a receber e 104,3 a pagar: os 2.060 que ela abate."""
    arvore = _arvore(
        {
            "1.01.08.03.01": ("Instrumentos derivativos - swap", 572.0),
            "1.02.01.10.02": ("Instrumentos derivativos - swap", 1592.4),
            "2.01.05.02.03": ("Instrumentos derivativos - swap", 91.1),
            "2.02.02.02.04": ("Instrumentos derivativos - swap", 13.2),
        }
    )
    ativo, passivo = derivativos_no_balanco(arvore)
    assert ativo == pytest.approx(2164.4)
    assert passivo == pytest.approx(104.3)


def test_a_reserva_de_hedge_do_patrimonio_nao_e_derivativo_a_pagar():
    """Klabin: a reserva em `2.03` aparecia como 1.989 de passivo."""
    arvore = _arvore(
        {
            "2.03.08.01": ("Hedge de fluxo de caixa - derivativos", -1988.8),
            "2.01.05.02.01": ("Instrumentos financeiros derivativos", 50.0),
        }
    )
    assert derivativos_no_balanco(arvore) == (0.0, pytest.approx(50.0))


def test_pai_e_filha_nao_se_somam_duas_vezes():
    arvore = _arvore(
        {
            "1.01.08.03": ("Instrumentos financeiros derivativos", 300.0),
            "1.01.08.03.01": ("Derivativos - swap cambial", 200.0),
            "1.01.08.03.02": ("Derivativos - NDF", 100.0),
        }
    )
    assert derivativos_no_balanco(arvore) == (pytest.approx(300.0), 0.0)

"""A planilha oficial de betas do Damodaran carrega de verdade.

O modulo recomenda carregá-la para trabalho formal, e ela nunca carregou: o
leitor so olhava a primeira aba, e na edicao de 2026-01 a tabela mora em
"Industry Averages", depois de "Explanation & FAQs". O teste monta uma planilha
com essa ordem, sem rede.
"""

from __future__ import annotations

import pandas as pd
import pytest

from valuation.dados_setoriais import carregar_betas_damodaran


def test_a_tabela_na_segunda_aba_e_encontrada(tmp_path):
    caminho = tmp_path / "betaemerg.xlsx"
    explicacao = pd.DataFrame({"Variable": ["Beta", "D/E Ratio"], "Explanation": ["...", "..."]})
    cabecalho = [["Date updated:", "2026-01-05"], ["Created by:", "Aswath Damodaran"]]
    tabela = pd.DataFrame(
        {
            "Industry Name": ["Steel", "Utility (Water)"],
            "Number of firms": [320, 60],
            "Beta ": [1.05, 0.62],
            "Unlevered beta corrected for cash": [0.80, 0.41],
        }
    )
    with pd.ExcelWriter(caminho) as escritor:
        explicacao.to_excel(escritor, sheet_name="Explanation & FAQs", index=False)
        pd.DataFrame(cabecalho).to_excel(
            escritor, sheet_name="Industry Averages", index=False, header=False
        )
        tabela.to_excel(
            escritor, sheet_name="Industry Averages", index=False, startrow=len(cabecalho) + 1
        )

    lida = carregar_betas_damodaran(caminho)
    assert list(lida.index) == ["Steel", "Utility (Water)"]
    assert lida.loc["Steel", "Unlevered beta corrected for cash"] == pytest.approx(0.80)


def test_planilha_que_nao_e_de_betas_e_recusada(tmp_path):
    caminho = tmp_path / "outra.xlsx"
    pd.DataFrame({"a": [1]}).to_excel(caminho, index=False)
    with pytest.raises(ValueError, match="Industry Name"):
        carregar_betas_damodaran(caminho)


def test_setores_da_planilha_agrega_pelas_empresas():
    """Siderurgia e so "Steel"; Bens de capital pondera Machinery e Electrical."""
    from valuation.dados_setoriais import setores_da_planilha

    tabela = pd.DataFrame(
        {
            "Number of firms": [300, 100, 500],
            "D/E Ratio": [0.5, 0.2, 0.1],
            "Unlevered beta corrected for cash": [0.9, 1.2, 1.4],
            "Average: 2021-26": [1.0, 1.0, 1.2],
        },
        index=["Steel", "Machinery", "Electrical Equipment"],
    )
    setores = setores_da_planilha(tabela)
    assert setores["Siderurgia e metalurgia"] == (pytest.approx(1.0), pytest.approx(0.5))
    beta, endividamento = setores["Bens de capital"]
    assert beta == pytest.approx((100 * 1.0 + 500 * 1.2) / 600)
    assert endividamento == pytest.approx((100 * 0.2 + 500 * 0.1) / 600)


def test_a_tabela_embarcada_e_a_da_edicao_2026_01():
    """Os dois setores financeiros ficaram de fora de proposito."""
    from valuation.dados_setoriais import ATUALIZADO_EM, INDUSTRIAS_DAMODARAN, POR_NOME

    assert ATUALIZADO_EM == "2026-01"
    assert "Bancos e servicos financeiros" not in INDUSTRIAS_DAMODARAN
    assert "Seguros" not in INDUSTRIAS_DAMODARAN
    assert set(INDUSTRIAS_DAMODARAN) <= set(POR_NOME)


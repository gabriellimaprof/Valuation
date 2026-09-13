"""A ponte sugerida abate o TVM de longo prazo, e a seguradora fica de fora.

Na ponte a pergunta nao e "e caixa?", e sim "e do acionista, e algum fluxo ja o
conta?". O titulo de longo prazo e do acionista e o rendimento dele fica abaixo
do EBIT, de onde o FCFF parte. Conferido em 2024: Ultrapar, Cyrela, Embraer e
Petrobras publicam a divida liquida abatendo-o -- na Petrobras, 323.489
publicados contra 323.211 da ampla e 326.816 da padrao.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from valuation.importacao.aplicacoes import (
    CAIXA,
    NAO_E_CAIXA,
    longo_prazo_que_abate,
    opera_seguro,
    titulos,
)

DADOS = Path(__file__).parent / "dados" / "cvm"


def _arvore(linhas: dict[str, tuple[str, float]]):
    todas = {"1.02.01": ("Ativo Realizável a Longo Prazo", 0.0), **linhas}
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
            for codigo, (rotulo, valor) in todas.items()
        ]
    )


# ---------------------------------------------------------------------------
# A sugestao
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def weg():
    from valuation.importacao.cvm import importar_cvm

    return importar_cvm(5410, [2024, 2025], cache=DADOS).escalar(1e6, "R$ milhões")


def test_a_ponte_sugerida_abate_o_titulo_de_longo_prazo(weg):
    from valuation.historico import analisar, sugerir_premissas

    sugestao = sugerir_premissas(analisar(weg))
    assert sugestao.ponte.aplicacoes_longo_prazo == pytest.approx(14.263)
    assert "entrou" in sugestao.justificativas["ponte"]
    # E a divida liquida da ponte e a ampla da data-base.
    assert sugestao.ponte.divida_liquida == pytest.approx(
        float(weg.divida_liquida_ampla()[2025]), abs=1e-6
    )


def test_sem_arvore_a_ponte_sugerida_fica_na_padrao():
    """Planilha não tem árvore, e ali a padrão é o único número que existe."""
    from valuation.historico import analisar, sugerir_premissas
    from valuation.importacao import Demonstracoes

    valores = pd.DataFrame(
        {
            ano: {
                "receita_liquida": 1000.0, "custo_produtos_vendidos": 600.0,
                "ebit": 200.0, "depreciacao_amortizacao": 50.0,
                "ativo_total": 3000.0, "patrimonio_liquido": 1000.0,
                "divida_curto_prazo": 200.0, "divida_longo_prazo": 800.0,
                "caixa_equivalentes": 100.0, "impostos": -50.0, "lair": 150.0,
                "lucro_liquido": 100.0,
            }
            for ano in (2022, 2023, 2024)
        }
    )
    planilha = Demonstracoes(empresa="T", valores=valores, unidade="R$ mi")
    sugestao = sugerir_premissas(analisar(planilha))
    assert sugestao.ponte.aplicacoes_longo_prazo == 0.0
    assert "entrou" not in sugestao.justificativas["ponte"]


def test_a_divida_liquida_da_ponte_cai_na_padrao_so_sem_arvore(weg):
    from valuation.importacao import Demonstracoes

    pd.testing.assert_series_equal(
        weg.divida_liquida_da_ponte(), weg.divida_liquida_ampla(), check_names=False
    )
    valores = pd.DataFrame(
        {2024: {"divida_curto_prazo": 100.0, "caixa_equivalentes": 30.0}}
    )
    planilha = Demonstracoes(empresa="T", valores=valores, unidade="R$ mi")
    assert planilha.divida_liquida_da_ponte()[2024] == pytest.approx(70.0)


# ---------------------------------------------------------------------------
# A seguradora
# ---------------------------------------------------------------------------


PORTO_SEGURO = {
    "1.02.01.03": ("Aplicações Financeiras Avaliadas ao Custo Amortizado", 8986.0),
    "3.01.01": ("Prêmios de seguros emitidos e contraprestações líquidas", 30000.0),
    "3.04.05.03": ("Sinistros retidos - bruto", -15000.0),
}


def test_a_carteira_da_seguradora_nao_abate_a_divida():
    """Porto Seguro: R$ 11 bi em contas que só dizem "custo amortizado".

    O rótulo da linha não denuncia; a demonstração, sim — prêmio na receita e
    sinistro no custo.
    """
    arvore = _arvore(PORTO_SEGURO)
    assert opera_seguro(arvore)
    (linha,) = titulos(arvore, 2024)
    assert linha.classe == NAO_E_CAIXA
    assert "segurados" in linha.motivo
    assert longo_prazo_que_abate(arvore, [2024])[2024] == 0.0


def test_o_titulo_declarado_livre_continua_caixa_na_seguradora():
    """Bradsaúde separa "Aplicações livres" (400) das garantidoras (139)."""
    arvore = _arvore(
        {
            "1.02.01.03": ("Aplicações Financeiras Avaliadas ao Custo Amortizado", 539.0),
            "1.02.01.03.01": ("Aplicações Garantidoras de Provisões Técnicas", 139.0),
            "1.02.01.03.02": ("Aplicações livres", 400.0),
            "3.01.01": ("Contraprestações Líquidas/Prêmios Retidos", 5000.0),
            "3.02.06": ("Sinistros", -3000.0),
        }
    )
    classes = {l.rotulo: l.classe for l in titulos(arvore, 2024)}
    assert classes["Aplicações livres"] == CAIXA
    assert classes["Aplicações Garantidoras de Provisões Técnicas"] == NAO_E_CAIXA
    assert longo_prazo_que_abate(arvore, [2024])[2024] == pytest.approx(400.0)


def test_a_provisao_tecnica_no_passivo_basta():
    """Hapvida: a DRE não usa as palavras, o passivo usa."""
    arvore = _arvore(
        {
            "1.02.01.02": ("Aplicações Financeiras Avaliadas a Valor Justo através "
                           "de Outros Resultados Abrangentes", 481.0),
            "2.01.06.02.04": ("Provisões técnicas de operações de assistência à saúde",
                              2000.0),
        }
    )
    assert opera_seguro(arvore)
    assert longo_prazo_que_abate(arvore, [2024])[2024] == 0.0


@pytest.mark.parametrize(
    "linha",
    [
        # Os falsos positivos medidos quando cada metade da regra valia sozinha.
        ("2.01.05.02.11", "Contraprestação a Pagar à Clientes"),  # Frasle
        ("2.03.02.08", "Premio de opção de ações"),  # Mills
        ("2.01.06.02.06", "Contraprestação contingente"),  # EDP
        ("3.01.01", "Receita de prêmios de fidelidade"),  # receita sem sinistro
    ],
)
def test_premio_e_contraprestacao_soltos_nao_fazem_seguradora(linha):
    codigo, rotulo = linha
    arvore = _arvore(
        {
            "1.02.01.01": ("Aplicações Financeiras Avaliadas a Valor Justo através "
                           "do Resultado", 107.0),
            codigo: (rotulo, 50.0),
        }
    )
    assert not opera_seguro(arvore)
    assert longo_prazo_que_abate(arvore, [2024])[2024] == pytest.approx(107.0)

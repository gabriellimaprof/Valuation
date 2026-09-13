"""O TVM que nao e caixa, no diagnostico e na reconciliacao com o release."""

from __future__ import annotations

import pandas as pd

from valuation.historico import analisar
from valuation.importacao import Demonstracoes


def _analise(linhas: dict[str, tuple[str, float]], arrendamento: float = 0.0):
    arvore = pd.DataFrame(
        [
            {
                "codigo": codigo,
                "rotulo": rotulo,
                "demonstracao": "bp",
                "nivel": codigo.count(".") + 1,
                "ordem": tuple(int(p) for p in codigo.split(".")),
                2024: valor,
            }
            for codigo, (rotulo, valor) in {
                "1.02.01": ("Ativo Realizável a Longo Prazo", 0.0),
                **linhas,
            }.items()
        ]
    )
    valores = pd.DataFrame(
        {
            ano: {
                "receita_liquida": 1000.0,
                "custo_produtos_vendidos": 600.0,
                "ebit": 200.0,
                "depreciacao_amortizacao": 50.0,
                "ativo_total": 3000.0,
                "patrimonio_liquido": 1000.0,
                "divida_curto_prazo": 200.0,
                "divida_longo_prazo": 800.0,
                "caixa_equivalentes": 100.0,
                "arrendamento_curto_prazo": arrendamento * 0.1,
                "arrendamento_longo_prazo": arrendamento * 0.9,
            }
            for ano in (2023, 2024)
        }
    )
    return analisar(
        Demonstracoes(empresa="T", valores=valores, unidade="R$ milhões", detalhe=arvore)
    )


USIMINAS = {
    "1.01.02.01": ("Aplicações Financeiras Avaliadas a Valor Justo através do "
                   "Resultado", 300.0),
    "1.01.02.01.03": ("Aplicações Financeiras Avaliadas a Valor Justo através do "
                      "resultado - Ações Usiminas", 300.0),
}


def test_participacao_no_circulante_vira_achado():
    """CSN: "Ações Usiminas" dentro do TVM circulante, que a dívida líquida abate.

    O app **avisa e não corrige** -- a CVM publicou a linha como aplicação.
    """
    from valuation.diagnostico import _titulos_que_nao_sao_caixa

    (achado,) = _titulos_que_nao_sao_caixa(_analise(USIMINAS))
    assert achado.codigo == "tvm_circulante_que_nao_e_caixa"
    assert "Ações Usiminas" in achado.detalhe
    assert "Ativos não operacionais" in achado.acao
    assert "300,0" in achado.titulo


def test_linha_irrisoria_nao_vira_achado():
    """B3: R$ 2 mi de derivativo num balanço de bilhões é ruído, não leitura."""
    from valuation.diagnostico import _titulos_que_nao_sao_caixa

    pequeno = {
        "1.01.02.01": ("Aplicações Financeiras", 2.0),
        "1.01.02.01.04": ("Instrumentos Financeiros Derivativos", 2.0),
    }
    assert _titulos_que_nao_sao_caixa(_analise(pequeno)) == []


def test_sem_arvore_nao_ha_achado():
    from valuation.diagnostico import _titulos_que_nao_sao_caixa

    valores = pd.DataFrame(
        {2024: {"receita_liquida": 1000.0, "ebit": 200.0,
                "divida_curto_prazo": 100.0, "caixa_equivalentes": 50.0}}
    )
    analise = analisar(Demonstracoes(empresa="T", valores=valores, unidade="R$ mi"))
    assert _titulos_que_nao_sao_caixa(analise) == []


def test_a_reconciliacao_aponta_a_ampla():
    """A segunda parcela da diferença com o release é a que a ampla já abate."""
    from valuation.diagnostico import _ponte_com_o_release

    analise = _analise(
        {"1.02.01.01": ("Aplicações Financeiras Avaliadas a Valor Justo através do "
                        "Resultado", 250.0)},
        arrendamento=300.0,
    )
    texto = _ponte_com_o_release(analise)
    assert "300,0" in texto  # arrendamento
    assert "250,0" in texto  # TVM de longo prazo
    assert "ampla" in texto


def test_derivativo_de_longo_prazo_nao_entra_na_reconciliacao():
    """Simpar: o derivativo não é a parcela que a companhia abate como caixa."""
    from valuation.diagnostico import _ponte_com_o_release

    analise = _analise(
        {
            "1.02.01.02": ("Aplicações Financeiras Avaliadas a Valor Justo através de "
                           "Outros Resultados Abrangentes", 400.0),
            "1.02.01.02.02": ("Instrumentos financeiros derivativos", 400.0),
        },
        arrendamento=300.0,
    )
    texto = _ponte_com_o_release(analise)
    # Nao e a parcela da aplicacao de longo prazo, que a ampla abate...
    assert "aplicação financeira de longo prazo" not in texto
    assert "ampla" not in texto
    # ...e sim a do derivativo, que nenhuma das duas dividas liquidas abate.
    assert "derivativo líquido de 400,0" in texto

"""Testes da leitura de qualidade dos lucros.

A regra que estrutura: o veredito e o pior sinal, e nao a media. Boa conversao
nao cancela juro capitalizado -- sao problemas diferentes, e quem le precisa
ver os dois.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from valuation.historico import AnaliseHistorica, analisar
from valuation.importacao.cvm import importar_cvm
from valuation.qualidade import (
    ATENCAO,
    BOM,
    RUIM,
    SEM_DADOS,
    avaliar_qualidade,
)

DADOS = Path(__file__).parent / "dados" / "cvm"


def _analise(**medianas) -> AnaliseHistorica:
    """Analise sintetica: cada indicador com o mesmo valor nos dois anos."""
    from valuation.importacao import Demonstracoes

    tabela = pd.DataFrame({2023: dict(medianas), 2024: dict(medianas)})
    vazio = Demonstracoes(
        empresa="Teste",
        valores=pd.DataFrame({2023: {"receita_liquida": 1.0}, 2024: {"receita_liquida": 1.0}}),
    )
    return AnaliseHistorica(demonstracoes=vazio, indicadores=tabela)


def test_conversao_alta_e_boa():
    q = avaliar_qualidade(_analise(**{"Conversao de caixa (FCO / EBITDA)": 1.05}))
    conversao = next(s for s in q.sinais if s.codigo == "conversao")
    assert conversao.veredito == BOM


def test_conversao_baixa_sem_crescimento_e_ruim():
    q = avaliar_qualidade(
        _analise(
            **{
                "Conversao de caixa (FCO / EBITDA)": 0.08,
                "Crescimento da receita": 0.02,
            }
        )
    )
    conversao = next(s for s in q.sinais if s.codigo == "conversao")
    assert conversao.veredito == RUIM
    assert q.veredito == RUIM


def test_conversao_baixa_com_crescimento_e_so_atencao():
    """Empresa que cresce rapido prende caixa no giro; isso nao e defeito."""
    q = avaliar_qualidade(
        _analise(
            **{
                "Conversao de caixa (FCO / EBITDA)": 0.08,
                "Crescimento da receita": 0.30,
            }
        )
    )
    conversao = next(s for s in q.sinais if s.codigo == "conversao")
    assert conversao.veredito == ATENCAO
    assert "crescendo" in conversao.detalhe


def test_juro_que_nao_sai_do_caixa_e_atencao():
    """Descolamento acima do P75 da base, com Kd ainda plausivel."""
    q = avaliar_qualidade(
        _analise(
            **{
                "Conversao de caixa (FCO / EBITDA)": 1.0,
                "Custo da divida efetivo": 0.22,
                "Custo da divida pelo caixa": 0.03,
            }
        )
    )
    juros = next(s for s in q.sinais if s.codigo == "juros")
    assert juros.veredito == ATENCAO
    assert "25% maiores" in juros.detalhe
    # E o veredito geral nao pode ser "bom" so porque a conversao esta boa.
    assert q.veredito == ATENCAO


def test_descolamento_normal_do_mercado_nao_vira_acusacao():
    """A mediana brasileira descola 8,2 p.p.; isso nao pode acusar ninguem.

    O corte anterior era 2 p.p. e disparava em 82,3% das 368 companhias que
    publicam os dois numeros. Sinal que dispara em quatro de cada cinco nao
    dirige atencao: gasta ela.
    """
    q = avaliar_qualidade(
        _analise(
            **{
                "Conversao de caixa (FCO / EBITDA)": 1.0,
                "Custo da divida efetivo": 0.14,
                "Custo da divida pelo caixa": 0.06,
            }
        )
    )
    juros = next(s for s in q.sinais if s.codigo == "juros")
    assert juros.veredito == BOM
    assert "8,2 p.p." in juros.detalhe


def test_despesa_financeira_alta_demais_nao_e_medivel():
    """Denominador minusculo faz a razao deixar de ser custo de divida.

    E o caso da WEG: caixa liquido, pouca divida, e uma linha de despesa
    financeira que carrega cambio de todo o passivo. Acusar por artefato de
    denominador e pior do que dizer que nao da para medir.
    """
    q = avaliar_qualidade(
        _analise(
            **{
                "Conversao de caixa (FCO / EBITDA)": 1.0,
                "Custo da divida efetivo": 0.45,
                "Custo da divida pelo caixa": 0.04,
            }
        )
    )
    juros = next(s for s in q.sinais if s.codigo == "juros")
    assert juros.veredito == SEM_DADOS
    assert "não é custo de dívida" in juros.detalhe


def test_o_pior_sinal_manda():
    q = avaliar_qualidade(
        _analise(
            **{
                "Conversao de caixa (FCO / EBITDA)": 0.05,
                "Crescimento da receita": 0.01,
                "Custo da divida efetivo": 0.10,
                "Custo da divida pelo caixa": 0.10,
            }
        )
    )
    assert q.veredito == RUIM
    assert q.por_severidade[0].veredito == RUIM


def test_sem_dfc_nao_finge_veredito():
    q = avaliar_qualidade(_analise(**{"Margem EBIT": 0.20}))
    assert q.veredito == SEM_DADOS
    assert "Faltam dados" in q.resumo


def test_giro_que_libera_caixa_e_bom():
    q = avaliar_qualidade(
        _analise(
            **{
                "Conversao de caixa (FCO / EBITDA)": 1.0,
                "Investimento em giro (DFC) / Receita": -0.03,
            }
        )
    )
    giro = next(s for s in q.sinais if s.codigo == "giro")
    assert giro.veredito == BOM


def test_todo_sinal_tem_icone_e_explicacao():
    q = avaliar_qualidade(_analise(**{"Conversao de caixa (FCO / EBITDA)": 0.95}))
    for sinal in q.sinais:
        assert sinal.icone
        assert sinal.titulo


# ---------------------------------------------------------------------------
# Contra dado real
# ---------------------------------------------------------------------------


def test_weg_tem_lucro_que_vira_caixa():
    """A WEG converte bem e nao tem juro descolado: o veredito nao pode ser ruim."""
    weg = importar_cvm(5410, [2023, 2024], cache=DADOS)
    q = avaliar_qualidade(analisar(weg))

    assert q.veredito in {BOM, ATENCAO}
    assert q.conversao_mediana > 0.7
    codigos = {s.codigo for s in q.sinais}
    assert codigos == {"conversao", "giro", "juros"}


def test_o_corte_de_conversao_fraca_nao_pode_acusar_metade_do_mercado():
    """Calibracao medida: 0,60 acusava 47,3% das 423 companhias da base.

    A mediana brasileira converte 64% do EBITDA em caixa -- nao por falta de
    qualidade, mas porque o FCO e liquido de imposto e, em dois tercos das
    companhias, tambem de juros, enquanto o EBITDA e antes dos dois. Um corte
    que classifica o tipico como fraco gasta a atencao do leitor.
    """
    from valuation.qualidade import CONVERSAO_BOA, CONVERSAO_FRACA
    from valuation import referencias

    mediana_da_base = referencias.BASE["Conversao de caixa (FCO / EBITDA)"][1][3]
    assert CONVERSAO_FRACA < mediana_da_base, "o corte de 'fraca' pegaria a mediana"
    # E "boa" continua sendo uma barra alta: o quartil superior da base.
    assert referencias.posicao("Conversao de caixa (FCO / EBITDA)", CONVERSAO_BOA) > 0.70


def test_a_conversao_explica_que_parte_da_distancia_e_estrutural():
    q = avaliar_qualidade(_analise(**{"Conversao de caixa (FCO / EBITDA)": 0.64}))
    conversao = next(s for s in q.sinais if s.codigo == "conversao")
    assert "líquido de imposto" in conversao.detalhe
    assert "estrutural" in conversao.detalhe


def test_a_reclassificacao_do_juro_aparece_no_sinal():
    """Quem comparar com a demonstracao publicada vai ver diferenca."""
    import pandas as pd

    from valuation.historico import analisar
    from valuation.importacao import Demonstracoes

    valores = pd.DataFrame(
        {
            2023: {
                "receita_liquida": 1000.0, "ebit": 150.0, "depreciacao_amortizacao": 50.0,
                "fluxo_operacional": 180.0, "juros_pagos_no_financiamento": 20.0,
            },
            2024: {
                "receita_liquida": 1100.0, "ebit": 165.0, "depreciacao_amortizacao": 55.0,
                "fluxo_operacional": 200.0, "juros_pagos_no_financiamento": 22.0,
            },
        }
    )
    sinal = next(
        s
        for s in avaliar_qualidade(analisar(Demonstracoes(empresa="X", valores=valores))).sinais
        if s.codigo == "conversao"
    )
    assert "financiamento no período" in sinal.detalhe
    assert "mudou de classificação" not in sinal.detalhe


def test_companhia_que_troca_de_classificacao_e_apontada():
    """A WEG fez isso entre 2022 e 2023: a serie dela nao era comparavel consigo."""
    import pandas as pd

    from valuation.historico import analisar
    from valuation.importacao import Demonstracoes

    valores = pd.DataFrame(
        {
            2023: {
                "receita_liquida": 1000.0, "ebit": 150.0, "depreciacao_amortizacao": 50.0,
                "fluxo_operacional": 180.0, "juros_pagos_no_financiamento": 20.0,
            },
            2024: {
                "receita_liquida": 1100.0, "ebit": 165.0, "depreciacao_amortizacao": 55.0,
                "fluxo_operacional": 200.0,
            },
        }
    )
    sinal = next(
        s
        for s in avaliar_qualidade(analisar(Demonstracoes(empresa="X", valores=valores))).sinais
        if s.codigo == "conversao"
    )
    assert "em 2023" in sinal.detalhe
    assert "nem consigo mesma" in sinal.detalhe

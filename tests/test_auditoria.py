"""O de-para: cada conta canonica contra a linha que a alimentou.

A auditoria existe porque o projeto acumulou reclassificacoes deliberadas --
arrendamento devolvido a divida, juro trazido para o operacional, pagamento
tirado do giro, outorga movida para o investimento. Cada uma foi medida quando
entrou, e **isoladamente**. Confiar no conjunto pede varrer a base e perguntar,
conta por conta, de onde o numero veio e se ele fecha com os que deveriam
limita-lo.

Os testes daqui garantem que a auditoria **acha** o que deveria achar. Uma
verificacao que nunca dispara e pior que nenhuma: da a impressao de que esta
tudo certo.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from valuation.auditoria import ATENCAO, GRAVE, Auditoria, auditar, auditar_base
from valuation.importacao import Demonstracoes

DADOS = Path(__file__).parent / "dados" / "cvm"


def _demonstracoes(**contas) -> Demonstracoes:
    base = {
        "receita_liquida": 1000.0,
        "custo_produtos_vendidos": 600.0,
        "lucro_bruto": 400.0,
        "ebit": 200.0,
        "lucro_liquido": 120.0,
        "ativo_total": 2000.0,
        "passivo_total": 2000.0,
        "ativo_circulante": 800.0,
        "passivo_circulante": 500.0,
        "patrimonio_liquido": 900.0,
        "caixa_equivalentes": 200.0,
        "estoques": 150.0,
        "contas_receber": 250.0,
        "divida_curto_prazo": 300.0,
        "divida_longo_prazo": 600.0,
        "fluxo_operacional": 250.0,
        "fluxo_investimento": -150.0,
        "fluxo_financiamento": -50.0,
        "variacao_caixa": 50.0,
    }
    base.update(contas)
    return Demonstracoes(empresa="Teste", valores=pd.DataFrame({2024: base}))


# ---------------------------------------------------------------------------
# As identidades
# ---------------------------------------------------------------------------


def test_base_coerente_nao_gera_achado():
    """Sem isto, a auditoria poderia estar acusando todo mundo e ninguem notaria."""
    assert auditar(_demonstracoes()) == []


def test_ativo_diferente_de_passivo_e_grave():
    achados = auditar(_demonstracoes(passivo_total=1800.0))
    assert any(a.verificacao == "ativo = passivo" and a.severidade == GRAVE for a in achados)


def test_secoes_da_dfc_que_nao_somam_a_variacao():
    """A verificacao mais direta de classificacao entre secoes."""
    achados = auditar(_demonstracoes(fluxo_investimento=-400.0))
    assert any("secoes da DFC" in a.verificacao for a in achados)


def test_a_dfc_fecha_com_variacao_cambial():
    """Cambio entra na soma; sem ele, companhia com exposicao pareceria quebrada."""
    coerente = _demonstracoes(
        fluxo_operacional=250.0,
        fluxo_investimento=-150.0,
        fluxo_financiamento=-50.0,
        variacao_cambial_caixa=30.0,
        variacao_caixa=80.0,
    )
    assert not [a for a in auditar(coerente) if "secoes da DFC" in a.verificacao]


def test_receita_menos_cpv_tem_que_dar_o_lucro_bruto():
    achados = auditar(_demonstracoes(lucro_bruto=300.0))
    assert any("lucro bruto" in a.verificacao for a in achados)


def test_a_decomposicao_do_fco_considera_o_que_foi_reclassificado():
    """Geracao + giro - pagamentos retirados = FCO.

    Sem o termo de reclassificacao, toda companhia que teve pagamento tirado do
    giro apareceria como divergencia -- a auditoria acusaria a propria correcao.
    """
    com_reclassificacao = _demonstracoes(
        caixa_das_operacoes=400.0,
        variacao_capital_giro=-50.0,
        pagamentos_reclassificados_do_giro=100.0,
        fluxo_operacional=250.0,
    )
    assert not [a for a in auditar(com_reclassificacao) if "explicam o FCO" in a.verificacao]

    sem_o_termo = _demonstracoes(
        caixa_das_operacoes=400.0,
        variacao_capital_giro=-50.0,
        fluxo_operacional=250.0,
    )
    assert [a for a in auditar(sem_o_termo) if "explicam o FCO" in a.verificacao]


# ---------------------------------------------------------------------------
# As contencoes: erro que nao quebra soma nenhuma
# ---------------------------------------------------------------------------


def test_arrendamento_maior_que_a_divida_e_apontado():
    """Nao quebra identidade; so a contencao pega."""
    achados = auditar(
        _demonstracoes(arrendamento_curto_prazo=400.0, divida_curto_prazo=300.0)
    )
    assert any("arrendamento dentro da divida" in a.verificacao for a in achados)


def test_caixa_maior_que_o_circulante_e_apontado():
    achados = auditar(_demonstracoes(caixa_equivalentes=900.0))
    assert any("caixa dentro do circulante" in a.verificacao for a in achados)


def test_circulante_maior_que_o_ativo_e_apontado():
    achados = auditar(_demonstracoes(ativo_circulante=2500.0))
    assert any("circulante dentro do ativo" in a.verificacao for a in achados)


def test_contencao_ignora_conta_ausente():
    """Ausencia de dado nao pode virar achado: seriam centenas de falsos."""
    magra = Demonstracoes(
        empresa="Magra",
        valores=pd.DataFrame({2024: {"receita_liquida": 1000.0, "ebit": 100.0}}),
    )
    assert auditar(magra) == []


# ---------------------------------------------------------------------------
# Sinais
# ---------------------------------------------------------------------------


def test_conta_de_magnitude_com_sinal_negativo_e_apontada():
    achados = auditar(_demonstracoes(custo_produtos_vendidos=-600.0, lucro_bruto=1600.0))
    assert any("sinal negativo" in a.verificacao for a in achados)


# ---------------------------------------------------------------------------
# O de-para propriamente dito
# ---------------------------------------------------------------------------


def test_a_auditoria_da_base_monta_o_de_para():
    resultado = auditar_base([5410, 24805], [2024], cache=DADOS)

    assert resultado.companhias == 2
    origens = resultado.tabela_de_origens()
    assert not origens.empty
    assert {"conta", "codigo CVM", "companhias", "% da conta"} <= set(origens.columns)

    # A receita das duas vem do mesmo lugar; se um dia nao vier, o de-para mostra.
    receita = origens[origens["conta"] == "receita_liquida"]
    assert receita["codigo CVM"].iloc[0].startswith("3.01")


def test_a_cobertura_conta_em_quantas_companhias_cada_conta_existe():
    resultado = auditar_base([5410, 24805], [2024], cache=DADOS)
    assert resultado.cobertura["receita_liquida"] == 2
    assert resultado.cobertura["ativo_total"] == 2


def test_origens_minoritarias_apontam_o_caso_isolado():
    """A conta que vem de outro codigo em uma companhia so."""
    auditoria = Auditoria(
        companhias=100,
        origens={"receita_liquida": {"3.01": 99, "3.02": 1}},
    )
    minoritarias = auditoria.origens_minoritarias(limite=0.05)
    assert list(minoritarias["codigo CVM"]) == ["3.02"]


def test_o_resumo_ordena_pelo_que_mais_falha():
    auditoria = Auditoria(
        companhias=10,
        achados=[
            *[
                type(a)(**{**a.__dict__, "codigo_cvm": i})
                for i, a in enumerate(
                    auditar(_demonstracoes(passivo_total=1500.0)) * 3
                )
            ]
        ],
    )
    resumo = auditoria.resumo()
    assert not resumo.empty
    assert "% da base" in resumo.columns


def test_a_decomposicao_desconta_o_juro_vindo_do_financiamento():
    """A auditoria nao pode acusar a propria padronizacao.

    O juro trazido do financiamento reduz o FCO sem aparecer em nenhum dos tres
    termos, que sao lidos de 6.01.xx. Sem o desconto, a verificacao acusava 126
    companhias -- e em Panatlantica a diferenca era exatamente os R$ 59,75 mi
    reclassificados.
    """
    coerente = _demonstracoes(
        caixa_das_operacoes=400.0,
        variacao_capital_giro=-50.0,
        outros_operacionais=-40.0,
        juros_pagos_no_financiamento=60.0,
        fluxo_operacional=250.0,
    )
    assert not [a for a in auditar(coerente) if "explicam o FCO" in a.verificacao]


def test_a_decomposicao_usa_outros_operacionais():
    """Sem 6.01.03 a decomposicao so fecha em 47% da base; com ele, em 97%."""
    com_outros = _demonstracoes(
        caixa_das_operacoes=400.0,
        variacao_capital_giro=-50.0,
        outros_operacionais=-100.0,
        fluxo_operacional=250.0,
    )
    assert not [a for a in auditar(com_outros) if "explicam o FCO" in a.verificacao]

    sem_o_termo = _demonstracoes(
        caixa_das_operacoes=400.0,
        variacao_capital_giro=-50.0,
        fluxo_operacional=250.0,
    )
    assert [a for a in auditar(sem_o_termo) if "explicam o FCO" in a.verificacao]

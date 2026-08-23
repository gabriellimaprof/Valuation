"""As formulas publicadas descrevem o que o motor calcula.

"Ha varios jeitos de chegar no ROIC" -- e ha. O denominador pode ser capital de
abertura, de fechamento ou medio; o numerador pode usar aliquota nominal ou
efetiva; o capital investido pode ou nao incluir o caixa. Mostrar o numero sem
dizer qual dos jeitos foi usado obriga quem le a confiar ou a reimplementar a
conta, e as duas coisas sao piores que mostrar a formula.

O risco de escrever a formula num texto separado do codigo e ela envelhecer
calada: a conta muda, o texto fica, e o app passa a mentir com confianca. Estes
testes ligam os dois.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from valuation.formulas import FORMULAS, formula
from valuation.historico import analisar
from valuation.importacao.cvm import importar_cvm

DADOS = Path(__file__).parent / "dados" / "cvm"


@pytest.fixture(scope="module")
def analise():
    weg = importar_cvm(5410, [2023, 2024], cache=DADOS).escalar(1e6, "R$ milhões")
    return analisar(weg)


def test_todo_indicador_publicado_tem_formula(analise):
    """Indicador na tela sem verbete e a pergunta do usuario sem resposta."""
    sem_verbete = [i for i in analise.indicadores.index if i not in FORMULAS]
    assert not sem_verbete, sem_verbete


def test_nao_ha_verbete_orfao(analise):
    """Formula de indicador que nao existe mais e texto envelhecendo calado."""
    # A analise da WEG nao produz todo indicador possivel -- liquidez depende da
    # arvore publicada --, entao a conferencia e sobre o conjunto que ela cobre
    # mais os de liquidez, que sao declarados na tela.
    from app.paginas.historico import LIQUIDEZ

    conhecidos = set(analise.indicadores.index) | set(LIQUIDEZ)
    orfaos = [i for i in FORMULAS if i not in conhecidos]
    assert not orfaos, orfaos


def test_o_roic_declara_as_tres_escolhas_que_mudam_o_numero():
    """Aliquota, composicao do capital e capital medio -- as tres, por escrito."""
    verbete = formula("ROIC")
    assert verbete is not None
    assert "NOPAT" in verbete.formula
    assert "médio" in verbete.formula
    for escolha in ("efetiva", "Dívida líquida + Patrimônio líquido", "abertura"):
        assert escolha in verbete.formula or escolha in verbete.convencao, escolha


def test_o_roic_publicado_bate_com_a_formula_publicada(analise):
    """A conta escrita no verbete, refeita a mao, tem que dar o mesmo numero.

    E o teste que impede o verbete de envelhecer: se alguem trocar o capital
    medio pelo de fechamento em `historico.py` e esquecer o texto, isto quebra.
    """
    d = analise.demonstracoes
    ano = d.ano_base
    anterior = d.anos[d.anos.index(ano) - 1]

    ebit = d.valor("ebit", ano)
    aliquota = min(
        max(d.valor("impostos", ano) / d.valor("lucro_antes_impostos", ano), 0.0), 1.0
    )
    nopat = ebit * (1 - aliquota)

    divida = d.divida_bruta()

    def capital(a: int) -> float:
        divida_liquida = (
            float(divida[a])
            - d.valor("caixa_equivalentes", a)
            - d.valor("aplicacoes_financeiras", a)
        )
        return divida_liquida + d.valor("patrimonio_liquido", a)

    capital_medio = (capital(anterior) + capital(ano)) / 2
    a_mao = nopat / capital_medio

    do_app = float(analise.indicadores.loc["ROIC", ano])
    assert do_app == pytest.approx(a_mao, rel=1e-9)


def test_a_conversao_operacional_e_a_final_tem_verbetes_diferentes():
    """As duas medem coisas diferentes, e o texto precisa dizer qual e qual."""
    operacional = formula("Conversao operacional (CGO / EBITDA)")
    final = formula("Conversao de caixa (FCO / EBITDA)")
    assert operacional is not None and final is not None
    assert "antes de capital de giro" in operacional.convencao
    assert "líquido de capital de giro" in final.convencao


def test_toda_formula_tem_conta_escrita():
    for nome, verbete in FORMULAS.items():
        assert verbete.formula.strip(), nome

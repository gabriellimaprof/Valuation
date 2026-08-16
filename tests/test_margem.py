"""Margem de seguranca e DCF reverso.

Duas coisas precisam estar certas aqui, e as duas ja custaram dinheiro a alguem.

A primeira e o denominador: margem sobre o **valor** e potencial sobre o
**preco** sao numeros diferentes da mesma distancia, e trocar um pelo outro
infla a folga percebida. Comprar a 70 o que vale 100 e 30% de margem e 42,9% de
potencial -- quem exige 30% e recebe o segundo numero acha que tem folga e nao
tem.

A segunda e a inversao: a premissa implicita tem que reproduzir o preco quando
devolvida ao modelo. Se nao reproduz, a tabela inteira e decoracao.
"""

from __future__ import annotations

import numpy as np
import pytest

from valuation import avaliar, substituir
from valuation.margem import (
    CARO,
    COM_MARGEM,
    JUSTO,
    expectativas_implicitas,
    margem_de_seguranca,
    margem_por_premissa,
    premissa_implicita,
    valor_de_referencia,
)


# ---------------------------------------------------------------------------
# Os dois denominadores
# ---------------------------------------------------------------------------


def test_margem_e_potencial_sao_a_mesma_distancia_com_bases_diferentes():
    m = margem_de_seguranca(valor=100.0, preco=70.0)
    assert m.margem == pytest.approx(0.30)
    assert m.potencial == pytest.approx(0.428571, abs=1e-6)
    assert m.potencial > m.margem, "trocar um pelo outro infla a folga percebida"


def test_preco_igual_ao_valor_zera_a_margem():
    m = margem_de_seguranca(valor=100.0, preco=100.0)
    assert m.margem == pytest.approx(0.0)
    assert m.veredito == JUSTO


def test_preco_acima_do_valor_da_margem_negativa_e_veredito_caro():
    m = margem_de_seguranca(valor=100.0, preco=125.0)
    assert m.margem < 0
    assert m.veredito == CARO
    assert "acima do valor" in m.resumo()


def test_o_veredito_respeita_a_margem_exigida():
    assert margem_de_seguranca(100.0, 65.0, exigida=0.30).veredito == COM_MARGEM
    assert margem_de_seguranca(100.0, 75.0, exigida=0.30).veredito == JUSTO
    # Quem exige menos aceita o mesmo preco.
    assert margem_de_seguranca(100.0, 75.0, exigida=0.20).veredito == COM_MARGEM


def test_preco_maximo_devolve_a_margem_exigida():
    m = margem_de_seguranca(100.0, 90.0, exigida=0.25)
    conferencia = margem_de_seguranca(m.valor, m.preco_maximo, exigida=0.25)
    assert conferencia.margem == pytest.approx(0.25)
    assert conferencia.veredito == COM_MARGEM


def test_preco_invalido_e_recusado():
    with pytest.raises(ValueError, match="positivo"):
        margem_de_seguranca(100.0, 0.0)
    with pytest.raises(ValueError, match="decimal"):
        margem_de_seguranca(100.0, 70.0, exigida=30)


# ---------------------------------------------------------------------------
# A inversao
# ---------------------------------------------------------------------------


def test_a_premissa_implicita_reproduz_o_preco_quando_devolvida_ao_modelo(empresa_exemplo):
    """A unica verificacao que importa: a resposta tem que fechar de volta."""
    alvo = avaliar(empresa_exemplo).equity_value * 0.80

    implicita = premissa_implicita(empresa_exemplo, alvo, "operacionais.margem_ebitda")
    assert np.isfinite(implicita)

    conferencia = avaliar(
        substituir(empresa_exemplo, "operacionais.margem_ebitda", implicita)
    ).equity_value
    assert conferencia == pytest.approx(alvo, rel=1e-4)


def test_preco_menor_exige_premissa_pior(empresa_exemplo):
    base = avaliar(empresa_exemplo).equity_value
    caminho = "operacionais.margem_ebitda"
    atual = float(np.median(empresa_exemplo.operacionais.margem_ebitda))

    assert premissa_implicita(empresa_exemplo, base * 0.9, caminho) < atual
    assert premissa_implicita(empresa_exemplo, base * 1.1, caminho) > atual


def test_a_inversao_funciona_no_sentido_contrario(empresa_exemplo):
    """Capex e risco-pais destroem valor: preco menor pede premissa maior."""
    base = avaliar(empresa_exemplo).equity_value
    atual = float(np.median(empresa_exemplo.operacionais.capex_pct_receita))

    implicita = premissa_implicita(
        empresa_exemplo, base * 0.85, "operacionais.capex_pct_receita"
    )
    assert implicita > atual

    conferencia = avaliar(
        substituir(empresa_exemplo, "operacionais.capex_pct_receita", implicita)
    ).equity_value
    assert conferencia == pytest.approx(base * 0.85, rel=1e-4)


def test_preco_inalcancavel_devolve_nan_em_vez_de_inventar(empresa_exemplo):
    """Dizer "nao existe" e melhor do que devolver a borda da faixa.

    Nenhuma margem EBITDA plausivel entrega cem vezes o valor calculado. A
    resposta honesta e a ausencia de resposta.
    """
    alvo = avaliar(empresa_exemplo).equity_value * 100
    assert np.isnan(premissa_implicita(empresa_exemplo, alvo, "operacionais.margem_ebitda"))


def test_a_inversao_atravessa_regiao_impossivel(empresa_exemplo):
    """Crescimento perpetuo acima do desconto e inviavel, e a busca passa por la.

    Se a varredura parasse na primeira combinacao invalida, o g nunca seria
    inversivel -- e ele e justamente a premissa que mais move valor terminal.
    """
    alvo = avaliar(empresa_exemplo).equity_value * 0.7
    implicita = premissa_implicita(
        empresa_exemplo, alvo, "perpetuidade.crescimento_perpetuo"
    )
    assert np.isfinite(implicita)
    conferencia = avaliar(
        substituir(empresa_exemplo, "perpetuidade.crescimento_perpetuo", implicita)
    ).equity_value
    assert conferencia == pytest.approx(alvo, rel=1e-4)


def test_inverter_o_g_solta_a_ancora_e_por_isso_funciona(empresa_exemplo):
    """Ancorado, o g e derivado; para invertelo e preciso solta-lo, e solta."""
    ancorada = substituir(empresa_exemplo, "perpetuidade.ancora", "pib_nominal")
    alvo = avaliar(ancorada).equity_value * 0.7

    implicita = premissa_implicita(
        ancorada, alvo, "perpetuidade.crescimento_perpetuo"
    )
    assert np.isfinite(implicita)
    assert implicita < ancorada.perpetuidade.crescimento_perpetuo


# ---------------------------------------------------------------------------
# A tabela que vai para a tela e para o relatorio
# ---------------------------------------------------------------------------


def test_expectativas_implicitas_cobrem_as_premissas_que_movem_valor(empresa_exemplo):
    preco = avaliar(empresa_exemplo).equity_value * 0.85
    tabela = expectativas_implicitas(empresa_exemplo, preco)

    assert "Margem EBITDA" in tabela.index
    assert "Crescimento perpétuo" in tabela.index
    assert {"No modelo", "Implícita no preço", "Diferença", "caminho"} <= set(tabela.columns)

    # Preco abaixo do valor: as premissas de receita tem que piorar.
    assert tabela.loc["Margem EBITDA", "Diferença"] < 0


def test_no_proprio_valor_as_implicitas_batem_com_as_do_modelo(empresa_exemplo):
    """Sancao da tabela inteira: preco igual ao valor nao pede mudanca nenhuma."""
    preco = avaliar(empresa_exemplo).equity_value
    tabela = expectativas_implicitas(empresa_exemplo, preco).dropna(subset=["Diferença"])

    assert not tabela.empty
    assert tabela["Diferença"].abs().max() < 1e-3


def test_margem_por_premissa_ordena_pela_folga(empresa_exemplo):
    preco = avaliar(empresa_exemplo).equity_value * 0.85
    tabela = margem_por_premissa(empresa_exemplo, preco).dropna(subset=["Diferença"])

    folgas = tabela["Diferença"].abs().tolist()
    assert folgas == sorted(folgas), "a premissa mais apertada tem que vir primeiro"


def test_valor_de_referencia_recusa_por_acao_sem_acoes(empresa_exemplo):
    from valuation.erros import CombinacaoInviavel

    resultado = avaliar(substituir(empresa_exemplo, "ponte.acoes_em_circulacao", None))
    with pytest.raises(CombinacaoInviavel, match="ações"):
        valor_de_referencia(resultado, por_acao=True)

    valor, chave = valor_de_referencia(resultado, por_acao=False)
    assert chave == "equity_value"
    assert valor == pytest.approx(resultado.equity_value)


def test_a_inversao_por_acao_usa_a_metrica_certa(empresa_exemplo):
    resultado = avaliar(empresa_exemplo)
    preco = float(resultado.valor_por_acao) * 0.9

    implicita = premissa_implicita(
        empresa_exemplo, preco, "operacionais.margem_ebitda", metrica="valor_por_acao"
    )
    conferencia = avaliar(
        substituir(empresa_exemplo, "operacionais.margem_ebitda", implicita)
    ).valor_por_acao
    assert conferencia == pytest.approx(preco, rel=1e-4)

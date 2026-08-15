"""Testes do retorno esperado do acionista (TSR) e sua decomposicao."""

from __future__ import annotations

import numpy as np
import pytest

from valuation import avaliar
from valuation.erros import CombinacaoInviavel
from valuation.retorno import (
    decompor_ponte_ev,
    decompor_tsr,
    multiplo_de_saida_do_dcf,
    projetar_acionista,
    tir,
    valor_presente_liquido,
)

# ---------------------------------------------------------------------------
# TIR
# ---------------------------------------------------------------------------


def test_tir_de_um_ano():
    assert tir(np.array([-100.0, 110.0])) == pytest.approx(0.10, abs=1e-9)


def test_tir_de_multiplos_anos():
    # 100 investidos, 10 de cupom por 3 anos e 100 de volta: TIR = 10%
    assert tir(np.array([-100.0, 10.0, 10.0, 110.0])) == pytest.approx(0.10, abs=1e-8)


def test_tir_zera_o_vpl():
    fluxos = np.array([-250.0, 60.0, 80.0, 90.0, 120.0])
    taxa = tir(fluxos)
    assert valor_presente_liquido(taxa, fluxos) == pytest.approx(0.0, abs=1e-7)


def test_tir_negativa():
    assert tir(np.array([-100.0, 80.0])) == pytest.approx(-0.20, abs=1e-9)


def test_tir_sem_troca_de_sinal_e_rejeitada():
    """Investimento sem desembolso nao tem taxa de retorno definida."""
    with pytest.raises(CombinacaoInviavel, match="nao trocam de sinal"):
        tir(np.array([100.0, 110.0]))


def test_tir_com_fluxo_nao_finito():
    with pytest.raises(ValueError, match="nao finitos"):
        tir(np.array([-100.0, float("nan")]))


def test_tir_precisa_de_dois_fluxos():
    with pytest.raises(ValueError, match="dois fluxos"):
        tir(np.array([-100.0]))


# ---------------------------------------------------------------------------
# Decomposicao do TSR: casos isolados, com conta fechada na mao
# ---------------------------------------------------------------------------


def test_apenas_crescimento_de_lucro():
    """Sem dividendo e sem re-rating, o TSR e exatamente o crescimento do lucro."""
    d = decompor_tsr(
        preco_entrada=100.0,
        lucro_entrada=10.0,
        lucro_saida=10.0 * 1.08**5,
        dividendos=[0.0] * 5,
    )
    assert d.contribuicao_crescimento == pytest.approx(0.08)
    assert d.contribuicao_multiplo == pytest.approx(0.0)
    assert d.contribuicao_dividendos == pytest.approx(0.0, abs=1e-9)
    assert d.tsr == pytest.approx(0.08, abs=1e-9)


def test_apenas_dividendo():
    """Lucro estável e múltiplo estável: todo o retorno vem do dividendo."""
    d = decompor_tsr(
        preco_entrada=100.0,
        lucro_entrada=10.0,
        lucro_saida=10.0,
        dividendos=[8.0] * 5,
    )
    assert d.contribuicao_crescimento == pytest.approx(0.0)
    assert d.contribuicao_multiplo == pytest.approx(0.0)
    assert d.tsr == pytest.approx(0.08, abs=1e-9)
    assert d.contribuicao_dividendos == pytest.approx(0.08, abs=1e-9)


def test_apenas_expansao_de_multiplo():
    """Empresa parada, mercado pagando mais: o retorno e puro re-rating."""
    d = decompor_tsr(
        preco_entrada=100.0,
        lucro_entrada=10.0,   # P/L de entrada = 10x
        lucro_saida=10.0,
        dividendos=[0.0] * 4,
        multiplo_saida=15.0,
    )
    assert d.contribuicao_crescimento == pytest.approx(0.0)
    assert d.contribuicao_multiplo == pytest.approx(1.5**0.25 - 1)
    assert d.tsr == pytest.approx(1.5**0.25 - 1, abs=1e-9)


def test_contracao_de_multiplo_reduz_o_retorno():
    """Comprar caro e vender barato tira retorno mesmo com lucro crescendo."""
    com_contracao = decompor_tsr(
        preco_entrada=200.0,
        lucro_entrada=10.0,   # entra a 20x
        lucro_saida=10.0 * 1.10**5,
        dividendos=[0.0] * 5,
        multiplo_saida=12.0,  # sai a 12x
    )
    assert com_contracao.contribuicao_multiplo < 0
    assert com_contracao.tsr < 0.10


def test_multiplo_de_entrada_vem_do_preco_pago():
    d = decompor_tsr(
        preco_entrada=150.0, lucro_entrada=10.0, lucro_saida=12.0, dividendos=[0.0] * 3
    )
    assert d.multiplo_entrada == pytest.approx(15.0)
    assert d.multiplo_saida == pytest.approx(15.0)  # sem re-rating por padrão


# ---------------------------------------------------------------------------
# A identidade fecha
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "preco,lucro_0,lucro_n,multiplo_saida,dividendos",
    [
        (100.0, 10.0, 16.0, None, [4.0, 4.5, 5.0, 5.5, 6.0]),
        (200.0, 10.0, 14.0, 12.0, [3.0, 3.0, 3.0, 3.0, 3.0]),
        (80.0, 8.0, 9.0, 14.0, [0.0, 0.0, 0.0]),
        (500.0, 25.0, 60.0, 30.0, [10.0] * 7),
        (100.0, 20.0, 18.0, 4.0, [1.0, 1.0]),   # tudo piorando
    ],
)
def test_decomposicao_soma_exatamente_o_tsr(
    preco, lucro_0, lucro_n, multiplo_saida, dividendos
):
    """A soma das parcelas precisa reconstituir a TIR ate a ultima casa."""
    d = decompor_tsr(
        preco_entrada=preco,
        lucro_entrada=lucro_0,
        lucro_saida=lucro_n,
        dividendos=dividendos,
        multiplo_saida=multiplo_saida,
    )
    assert d.fecha()
    assert d.residuo == pytest.approx(0.0, abs=1e-9)


def test_termo_cruzado_e_o_produto_das_duas_taxas():
    """O termo cruzado nao e um resíduo: e exatamente g_lucro x g_multiplo."""
    d = decompor_tsr(
        preco_entrada=100.0,
        lucro_entrada=10.0,
        lucro_saida=10.0 * 1.20**5,
        dividendos=[0.0] * 5,
        multiplo_saida=10.0 * 1.30,
    )
    esperado = d.contribuicao_crescimento * d.contribuicao_multiplo
    assert d.contribuicao_cruzada == pytest.approx(esperado)
    assert d.contribuicao_cruzada > 0.005  # relevante nesse caso, não desprezível


def test_retorno_de_preco_e_multiplicativo():
    d = decompor_tsr(
        preco_entrada=100.0,
        lucro_entrada=10.0,
        lucro_saida=20.0,
        dividendos=[0.0] * 5,
        multiplo_saida=15.0,
    )
    esperado = (1 + d.contribuicao_crescimento) * (1 + d.contribuicao_multiplo) - 1
    assert d.retorno_de_preco == pytest.approx(esperado)
    # E confere contra o preco de saida diretamente.
    assert d.preco_saida == pytest.approx(20.0 * 15.0)


def test_tabela_tem_todas_as_fontes_e_o_total():
    d = decompor_tsr(
        preco_entrada=100.0, lucro_entrada=10.0, lucro_saida=15.0, dividendos=[5.0] * 5
    )
    tabela = d.tabela()
    assert "Crescimento do lucro" in tabela.index
    assert "Dividendos" in tabela.index
    assert "Expansão/contração de múltiplo" in tabela.index
    assert "TSR esperado (TIR)" in tabela.index
    assert tabela.loc["TSR esperado (TIR)", "Contribuição a.a."] == pytest.approx(d.tsr)


def test_dividend_yield_de_entrada():
    d = decompor_tsr(
        preco_entrada=100.0, lucro_entrada=10.0, lucro_saida=12.0, dividendos=[6.0, 6.5]
    )
    assert d.dividend_yield_de_entrada == pytest.approx(0.06)


def test_lucro_de_entrada_negativo_e_rejeitado():
    with pytest.raises(CombinacaoInviavel, match="EV/EBITDA"):
        decompor_tsr(
            preco_entrada=100.0, lucro_entrada=-5.0, lucro_saida=10.0, dividendos=[0.0]
        )


def test_preco_de_entrada_invalido():
    with pytest.raises(ValueError, match="preco_entrada"):
        decompor_tsr(
            preco_entrada=0.0, lucro_entrada=10.0, lucro_saida=12.0, dividendos=[1.0]
        )


def test_lucro_de_saida_negativo_nao_quebra():
    """Empresa que vira prejuizo: crescimento indefinido, mas a TIR ainda existe."""
    d = decompor_tsr(
        preco_entrada=100.0,
        lucro_entrada=10.0,
        lucro_saida=1.0,
        dividendos=[2.0, 2.0, 2.0],
    )
    assert np.isfinite(d.tsr)
    assert d.tsr < 0


# ---------------------------------------------------------------------------
# Projecao dos fluxos do acionista
# ---------------------------------------------------------------------------


def test_juros_incidem_sobre_o_saldo_de_abertura(empresa_exemplo):
    resultado = avaliar(empresa_exemplo)
    acionista = projetar_acionista(
        resultado.projecao,
        divida_inicial=900.0,
        custo_divida=0.12,
        payout=0.5,
        amortizar_divida=False,
    )
    assert acionista.divida_abertura[0] == pytest.approx(900.0)
    assert acionista.juros[0] == pytest.approx(900.0 * 0.12)
    # Sem amortizacao, a divida nao se move.
    assert acionista.divida_fechamento[-1] == pytest.approx(900.0)


def test_lucro_liquido_desconta_juros_do_ebit(empresa_exemplo):
    resultado = avaliar(empresa_exemplo)
    acionista = projetar_acionista(
        resultado.projecao, divida_inicial=900.0, custo_divida=0.12, aliquota_ir=0.34
    )
    esperado_lair = resultado.projecao.ebit[0] - acionista.juros[0]
    assert acionista.lucro_antes_impostos[0] == pytest.approx(esperado_lair)
    assert acionista.lucro_liquido[0] == pytest.approx(esperado_lair * 0.66)


def test_amortizacao_reduz_a_divida(empresa_exemplo):
    resultado = avaliar(empresa_exemplo)
    acionista = projetar_acionista(
        resultado.projecao,
        divida_inicial=900.0,
        custo_divida=0.12,
        payout=0.0,
        amortizar_divida=True,
    )
    assert acionista.divida_fechamento[-1] < 900.0
    assert (acionista.amortizacao >= 0).all()
    # A divida nunca fica negativa: amortizar mais do que se deve nao faz sentido.
    assert (acionista.divida_fechamento >= 0).all()


def test_desalavancagem_eleva_os_juros_decrescentes(empresa_exemplo):
    resultado = avaliar(empresa_exemplo)
    acionista = projetar_acionista(
        resultado.projecao, divida_inicial=900.0, custo_divida=0.12, payout=0.0
    )
    assert acionista.juros[-1] < acionista.juros[0]


def test_dividendo_limitado_pelo_caixa_disponivel(empresa_exemplo):
    """Empresa nao distribui dividendo que nao tem em caixa."""
    resultado = avaliar(empresa_exemplo)
    acionista = projetar_acionista(
        resultado.projecao,
        divida_inicial=900.0,
        custo_divida=0.12,
        payout=1.0,
        amortizar_divida=False,
    )
    assert (acionista.dividendos <= np.maximum(acionista.caixa_disponivel, 0) + 1e-9).all()


def test_politica_fcfe_distribui_todo_o_caixa(empresa_exemplo):
    resultado = avaliar(empresa_exemplo)
    acionista = projetar_acionista(
        resultado.projecao,
        divida_inicial=900.0,
        custo_divida=0.12,
        politica="fcfe",
        amortizar_divida=False,
    )
    esperado = np.maximum(acionista.caixa_disponivel, 0)
    assert acionista.dividendos == pytest.approx(esperado)


def test_prejuizo_fiscal_reduz_o_imposto(empresa_exemplo):
    resultado = avaliar(empresa_exemplo)
    sem = projetar_acionista(
        resultado.projecao, divida_inicial=900.0, custo_divida=0.12
    )
    com = projetar_acionista(
        resultado.projecao,
        divida_inicial=900.0,
        custo_divida=0.12,
        prejuizo_fiscal_acumulado=300.0,
    )
    assert com.impostos[0] < sem.impostos[0]
    assert com.lucro_liquido[0] > sem.lucro_liquido[0]


def test_politica_invalida(empresa_exemplo):
    resultado = avaliar(empresa_exemplo)
    with pytest.raises(ValueError, match="politica"):
        projetar_acionista(
            resultado.projecao, divida_inicial=0.0, custo_divida=0.1, politica="magica"
        )


def test_payout_fora_da_faixa(empresa_exemplo):
    resultado = avaliar(empresa_exemplo)
    with pytest.raises(ValueError, match="payout"):
        projetar_acionista(
            resultado.projecao, divida_inicial=0.0, custo_divida=0.1, payout=1.5
        )


def test_tabela_do_acionista(empresa_exemplo):
    resultado = avaliar(empresa_exemplo)
    tabela = projetar_acionista(
        resultado.projecao, divida_inicial=900.0, custo_divida=0.12
    ).tabela()
    assert "Lucro líquido" in tabela.index
    assert "Dividendos" in tabela.index
    assert "Dívida (fechamento)" in tabela.index


# ---------------------------------------------------------------------------
# Ponte de valor por EV/EBITDA
# ---------------------------------------------------------------------------


def test_ponte_ev_fecha_exatamente():
    ponte = decompor_ponte_ev(
        ebitda_entrada=100.0,
        ebitda_saida=150.0,
        multiplo_entrada=8.0,
        multiplo_saida=9.0,
        divida_entrada=400.0,
        divida_saida=250.0,
        dividendos_acumulados=60.0,
    )
    assert ponte.fecha()
    assert ponte.residuo == pytest.approx(0.0, abs=1e-6)


def test_ponte_ev_com_a_conta_na_mao():
    ponte = decompor_ponte_ev(
        ebitda_entrada=100.0,
        ebitda_saida=150.0,
        multiplo_entrada=8.0,
        multiplo_saida=9.0,
        divida_entrada=400.0,
        divida_saida=250.0,
    )
    assert ponte.equity_entrada == pytest.approx(100 * 8 - 400)     # 400
    assert ponte.equity_saida == pytest.approx(150 * 9 - 250)       # 1100
    assert ponte.contribuicao_ebitda == pytest.approx(50 * 8)       # 400
    assert ponte.contribuicao_multiplo == pytest.approx(1 * 100)    # 100
    assert ponte.contribuicao_cruzada == pytest.approx(50 * 1)      # 50
    assert ponte.contribuicao_desalavancagem == pytest.approx(150)  # 400 - 250


def test_desalavancagem_e_fonte_propria_de_retorno():
    """Divida encolhendo transfere valor do credor para o acionista."""
    sem = decompor_ponte_ev(100.0, 100.0, 8.0, 400.0, 400.0)
    com = decompor_ponte_ev(100.0, 100.0, 8.0, 400.0, 250.0)
    assert sem.contribuicao_desalavancagem == 0.0
    assert com.contribuicao_desalavancagem == pytest.approx(150.0)
    assert com.equity_saida > sem.equity_saida


def test_ponte_sem_re_rating_usa_o_multiplo_de_entrada():
    ponte = decompor_ponte_ev(100.0, 120.0, 8.0, 300.0, 300.0)
    assert ponte.multiplo_saida == pytest.approx(8.0)
    assert ponte.contribuicao_multiplo == pytest.approx(0.0)


def test_tabela_da_ponte():
    tabela = decompor_ponte_ev(100.0, 150.0, 8.0, 400.0, 250.0, 60.0, 9.0).tabela()
    assert "Desalavancagem (redução da dívida)" in tabela.index
    assert "Crescimento do EBITDA" in tabela.index


# ---------------------------------------------------------------------------
# Consistencia com o DCF
# ---------------------------------------------------------------------------


def test_multiplo_de_saida_implicito_no_dcf(empresa_exemplo):
    """O valor terminal do DCF e o EV do ano n; dele sai o P/L de saida."""
    resultado = avaliar(empresa_exemplo)
    lucro_saida = 80.0
    multiplo = multiplo_de_saida_do_dcf(resultado, lucro_saida, divida_saida=500.0)
    esperado = (resultado.dcf.valor_terminal - 500.0) / lucro_saida
    assert multiplo == pytest.approx(esperado)


def test_multiplo_implicito_exige_lucro_positivo(empresa_exemplo):
    resultado = avaliar(empresa_exemplo)
    with pytest.raises(CombinacaoInviavel, match="P/L de saida"):
        multiplo_de_saida_do_dcf(resultado, lucro_saida=-10.0)


def test_multiplo_implicito_com_divida_acima_do_valor_terminal(empresa_exemplo):
    resultado = avaliar(empresa_exemplo)
    with pytest.raises(CombinacaoInviavel, match="nao cobre a divida"):
        multiplo_de_saida_do_dcf(resultado, lucro_saida=50.0, divida_saida=1e9)


def test_fluxo_completo_do_tsr_a_partir_do_valuation(empresa_exemplo):
    """Caminho que o app percorre: valuation -> fluxos do acionista -> TSR."""
    resultado = avaliar(empresa_exemplo)
    acionista = projetar_acionista(
        resultado.projecao,
        divida_inicial=empresa_exemplo.ponte.divida_bruta,
        custo_divida=resultado.custo_capital.kd_bruto_brl,
        aliquota_ir=empresa_exemplo.macro.aliquota_ir,
        payout=0.4,
    )
    multiplo = multiplo_de_saida_do_dcf(
        resultado,
        lucro_saida=float(acionista.lucro_liquido[-1]),
        divida_saida=float(acionista.divida_fechamento[-1]),
    )
    decomposicao = decompor_tsr(
        preco_entrada=resultado.equity_value,
        lucro_entrada=float(acionista.lucro_liquido[0]),
        lucro_saida=float(acionista.lucro_liquido[-1]),
        dividendos=acionista.dividendos,
        multiplo_saida=multiplo,
    )
    assert decomposicao.fecha()
    assert np.isfinite(decomposicao.tsr)
    assert -0.5 < decomposicao.tsr < 1.0


# ---------------------------------------------------------------------------
# Preco-alvo para um TSR desejado
# ---------------------------------------------------------------------------


def test_preco_para_tsr_devolve_o_tsr_pedido():
    """Pagando o preco que o solver devolve, a TIR tem que sair no alvo."""
    from valuation.retorno import preco_para_tsr

    dividendos = [4.0, 4.5, 5.0, 5.5, 6.0]
    preco = preco_para_tsr(
        tsr_alvo=0.15,
        lucro_entrada_por_preco=10.0,
        lucro_saida=16.0,
        dividendos=dividendos,
        multiplo_saida=12.0,
    )
    conferencia = decompor_tsr(
        preco_entrada=preco,
        lucro_entrada=10.0,
        lucro_saida=16.0,
        dividendos=dividendos,
        multiplo_saida=12.0,
    )
    assert conferencia.tsr == pytest.approx(0.15, abs=1e-7)


def test_exigir_mais_retorno_exige_pagar_menos():
    from valuation.retorno import preco_para_tsr

    argumentos = dict(
        lucro_entrada_por_preco=10.0,
        lucro_saida=16.0,
        dividendos=[5.0] * 5,
        multiplo_saida=12.0,
    )
    assert preco_para_tsr(0.20, **argumentos) < preco_para_tsr(0.10, **argumentos)


def test_preco_alvo_valida_entradas():
    from valuation.retorno import preco_para_tsr

    with pytest.raises(ValueError, match="multiplo_saida"):
        preco_para_tsr(0.15, 10.0, 16.0, [5.0], multiplo_saida=0.0)
    with pytest.raises(ValueError, match="tsr_alvo"):
        preco_para_tsr(-1.5, 10.0, 16.0, [5.0], multiplo_saida=10.0)


# ---------------------------------------------------------------------------
# Consistencia com a convencao de desconto do DCF
# ---------------------------------------------------------------------------


def test_meio_de_ano_eleva_o_retorno():
    """Receber o dividendo no meio do ano vale mais do que no fim dele."""
    argumentos = dict(
        preco_entrada=100.0,
        lucro_entrada=10.0,
        lucro_saida=14.0,
        dividendos=[5.0] * 5,
        multiplo_saida=10.0,
    )
    fim = decompor_tsr(**argumentos, meio_de_ano=False)
    meio = decompor_tsr(**argumentos, meio_de_ano=True)
    assert meio.tsr > fim.tsr


def test_decomposicao_fecha_tambem_com_meio_de_ano():
    d = decompor_tsr(
        preco_entrada=120.0,
        lucro_entrada=10.0,
        lucro_saida=15.0,
        dividendos=[4.0, 4.5, 5.0, 5.5],
        multiplo_saida=11.0,
        meio_de_ano=True,
    )
    assert d.fecha()


def test_sem_dividendos_a_convencao_nao_muda_nada():
    """Sem fluxo intermediario nao ha o que reposicionar no tempo."""
    argumentos = dict(
        preco_entrada=100.0,
        lucro_entrada=10.0,
        lucro_saida=16.0,
        dividendos=[0.0] * 5,
        multiplo_saida=10.0,
    )
    fim = decompor_tsr(**argumentos, meio_de_ano=False)
    meio = decompor_tsr(**argumentos, meio_de_ano=True)
    assert meio.tsr == pytest.approx(fim.tsr, abs=1e-9)


def test_vpl_aceita_tempos_fracionarios():
    from valuation.retorno import valor_presente_liquido

    # 110 recebido em meio ano a 10% vale 110/1,1^0,5
    assert valor_presente_liquido(
        0.10, np.array([0.0, 110.0]), tempos=np.array([0.0, 0.5])
    ) == pytest.approx(110 / 1.10**0.5)


def test_vpl_rejeita_tempos_de_tamanho_errado():
    from valuation.retorno import valor_presente_liquido

    with pytest.raises(ValueError, match="mesmo tamanho"):
        valor_presente_liquido(0.1, np.array([-100.0, 110.0]), tempos=np.array([0.0]))


@pytest.mark.parametrize("meio_de_ano", [False, True])
def test_empresa_sem_divida_devolve_exatamente_o_ke(empresa_exemplo, meio_de_ano):
    """A prova da consistencia entre o DCF e o TSR.

    Sem divida, Ke e WACC coincidem e o fluxo do acionista e o proprio FCFF.
    Comprando pelo valor que o DCF calculou, a TIR **tem** que ser o Ke -- em
    qualquer das duas convencoes de desconto. Se este teste falhar, as duas
    telas do app estao contando historias diferentes sobre a mesma empresa.
    """
    from valuation import substituir_varios

    sem_divida = substituir_varios(
        empresa_exemplo,
        {
            "custo_capital.divida_pl_alvo": 0.0,
            "custo_capital.divida_pl_setor": 0.0,
            "ponte.divida_bruta": 0.0,
            "ponte.caixa": 0.0,
            "ponte.minoritarios": 0.0,
            "ponte.contingencias": 0.0,
        },
    )
    resultado = avaliar(sem_divida, meio_de_ano=meio_de_ano)
    acionista = projetar_acionista(
        resultado.projecao,
        divida_inicial=0.0,
        custo_divida=0.0,
        aliquota_ir=sem_divida.macro.aliquota_ir,
        politica="fcfe",
        amortizar_divida=False,
    )
    multiplo = multiplo_de_saida_do_dcf(resultado, float(acionista.lucro_liquido[-1]))
    decomposicao = decompor_tsr(
        preco_entrada=resultado.equity_value,
        lucro_entrada=float(acionista.lucro_liquido[0]),
        lucro_saida=float(acionista.lucro_liquido[-1]),
        dividendos=acionista.dividendos,
        multiplo_saida=multiplo,
        meio_de_ano=meio_de_ano,
    )
    assert decomposicao.tsr == pytest.approx(resultado.custo_capital.ke_brl, abs=1e-6)

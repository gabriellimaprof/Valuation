"""Testes do custo de capital."""

from __future__ import annotations

import pytest

from valuation import (
    PremissasCustoCapital,
    PremissasMacro,
    calcular_custo_capital,
    converter_taxa,
    desalavancar_beta,
    realavancar_beta,
)
from valuation.custo_capital import pesos_estrutura_capital


def test_hamada_ida_e_volta():
    """Desalavancar e realavancar na mesma estrutura devolve o beta original."""
    beta = 1.32
    desalavancado = desalavancar_beta(beta, divida_pl=0.6, aliquota_ir=0.34)
    assert realavancar_beta(desalavancado, 0.6, 0.34) == pytest.approx(beta)


def test_beta_desalavancado_e_menor_que_o_alavancado():
    assert desalavancar_beta(1.2, divida_pl=0.5, aliquota_ir=0.34) < 1.2


def test_beta_sem_divida_nao_muda():
    assert desalavancar_beta(0.9, divida_pl=0.0, aliquota_ir=0.34) == pytest.approx(0.9)


def test_conversao_de_moeda_por_diferencial_de_inflacao():
    # 10% em USD, com inflacao de 4% no BRL e 2% no USD.
    taxa_brl = converter_taxa(0.10, inflacao_destino=0.04, inflacao_origem=0.02)
    assert taxa_brl == pytest.approx(1.10 * 1.04 / 1.02 - 1)
    assert taxa_brl > 0.10  # inflacao local maior eleva a taxa nominal


def test_conversao_e_reversivel():
    ida = converter_taxa(0.12, 0.04, 0.023)
    assert converter_taxa(ida, 0.023, 0.04) == pytest.approx(0.12)


def test_pesos_da_estrutura_de_capital_somam_um():
    peso_divida, peso_equity = pesos_estrutura_capital(0.5)
    assert peso_divida == pytest.approx(1 / 3)
    assert peso_equity == pytest.approx(2 / 3)
    assert peso_divida + peso_equity == pytest.approx(1.0)


def test_capm_com_risco_pais(macro):
    """Confere o Ke contra a conta feita a mao, passo a passo."""
    premissas = PremissasCustoCapital(
        metodo="usd",
        rf_usd=0.045,
        erp_maduro=0.045,
        risco_pais=0.025,
        beta_alavancado_setor=1.05,
        divida_pl_setor=0.45,
        divida_pl_alvo=0.50,
        spread_credito=0.025,
    )
    resultado = calcular_custo_capital(premissas, macro)

    beta_u = 1.05 / (1 + 0.66 * 0.45)
    beta_l = beta_u * (1 + 0.66 * 0.50)
    ke_usd = 0.045 + beta_l * 0.045 + 0.025
    ke_brl = (1 + ke_usd) * 1.04 / 1.023 - 1

    assert resultado.beta_desalavancado == pytest.approx(beta_u)
    assert resultado.beta_realavancado == pytest.approx(beta_l)
    assert resultado.ke_usd == pytest.approx(ke_usd)
    assert resultado.ke_brl == pytest.approx(ke_brl)


def test_wacc_pondera_ke_e_kd_apos_impostos(macro):
    premissas = PremissasCustoCapital(
        beta_desalavancado=0.8, divida_pl_alvo=1.0, custo_divida_brl=0.14
    )
    resultado = calcular_custo_capital(premissas, macro)

    assert resultado.peso_divida == pytest.approx(0.5)
    assert resultado.kd_liquido_brl == pytest.approx(0.14 * 0.66)
    assert resultado.wacc_brl == pytest.approx(
        0.5 * resultado.ke_brl + 0.5 * 0.14 * 0.66
    )


def test_wacc_sem_divida_e_igual_ao_ke(macro):
    premissas = PremissasCustoCapital(beta_desalavancado=1.0, divida_pl_alvo=0.0)
    resultado = calcular_custo_capital(premissas, macro)
    assert resultado.wacc_brl == pytest.approx(resultado.ke_brl)


def test_mais_divida_reduz_o_wacc_ate_certo_ponto(macro):
    """O beneficio fiscal da divida derruba o WACC nos primeiros niveis de alavancagem."""
    sem_divida = calcular_custo_capital(
        PremissasCustoCapital(beta_desalavancado=0.8, divida_pl_alvo=0.0), macro
    )
    com_divida = calcular_custo_capital(
        PremissasCustoCapital(beta_desalavancado=0.8, divida_pl_alvo=0.4), macro
    )
    assert com_divida.wacc_brl < sem_divida.wacc_brl
    # ... mas o custo do equity sobe, porque o acionista assume mais risco.
    assert com_divida.ke_brl > sem_divida.ke_brl


def test_lambda_modula_a_exposicao_ao_risco_pais(macro):
    base = PremissasCustoCapital(
        metodo="usd", beta_desalavancado=1.0, risco_pais=0.03, lambda_pais=1.0
    )
    exportadora = PremissasCustoCapital(
        metodo="usd", beta_desalavancado=1.0, risco_pais=0.03, lambda_pais=0.4
    )
    ke_base = calcular_custo_capital(base, macro).ke_usd
    ke_exp = calcular_custo_capital(exportadora, macro).ke_usd
    assert ke_base - ke_exp == pytest.approx(0.6 * 0.03)


def test_kd_sintetico_soma_risco_pais_e_spread(macro):
    premissas = PremissasCustoCapital(
        metodo="usd",
        beta_desalavancado=1.0,
        rf_usd=0.045,
        risco_pais=0.025,
        spread_credito=0.03,
    )
    resultado = calcular_custo_capital(premissas, macro)
    kd_usd = 0.045 + 0.025 + 0.03
    assert resultado.kd_bruto_brl == pytest.approx(
        (1 + kd_usd) * 1.04 / 1.023 - 1
    )


def test_beta_obrigatorio():
    with pytest.raises(ValueError, match="beta"):
        PremissasCustoCapital(beta_alavancado_setor=None, beta_desalavancado=None)


def test_percentual_em_vez_de_decimal_e_rejeitado():
    """Digitar 34 no lugar de 0.34 e o erro de premissa mais comum e mais caro."""
    with pytest.raises(ValueError, match="decimais"):
        PremissasMacro(aliquota_ir=34)


# ---------------------------------------------------------------------------
# Banco: o beta nao se realavanca
# ---------------------------------------------------------------------------


def test_o_beta_de_banco_nao_e_realavancado():
    """Hamada supõe que a dívida é escolha de financiamento; num banco não é.

    O depósito e a captação são a **matéria-prima** do negócio, e o risco deles
    já está dentro do beta observado do equity. Medido nas 18 instituições com
    balanço legível em 2024: o passivo de terceiros é **11,2x o patrimônio na
    mediana**, e realavancar um beta de 0,95 por esse D/E daria beta 8,0 e Ke de
    **41% em dólar**. Banco nenhum tem isso.
    """
    from valuation.custo_capital import calcular_custo_capital
    from valuation.premissas import PremissasCustoCapital, PremissasMacro

    base = dict(metodo="usd", beta_desalavancado=0.95, divida_pl_alvo=11.2)
    industria = calcular_custo_capital(
        PremissasCustoCapital(**base), PremissasMacro()
    )
    banco = calcular_custo_capital(
        PremissasCustoCapital(**base, instituicao_financeira=True), PremissasMacro()
    )

    assert industria.beta_realavancado > 7.0, "o caso absurdo deixou de ser absurdo"
    assert industria.ke_usd > 0.40
    assert banco.beta_realavancado == pytest.approx(0.95)
    assert 0.08 < banco.ke_usd < 0.16


def test_a_marca_nao_muda_nada_para_quem_nao_e_banco():
    """A regra só pode valer onde foi justificada."""
    from valuation.custo_capital import calcular_custo_capital
    from valuation.premissas import PremissasCustoCapital, PremissasMacro

    sem_divida = dict(beta_desalavancado=0.9, divida_pl_alvo=0.0)
    a = calcular_custo_capital(PremissasCustoCapital(**sem_divida), PremissasMacro())
    b = calcular_custo_capital(
        PremissasCustoCapital(**sem_divida, instituicao_financeira=True),
        PremissasMacro(),
    )
    assert a.ke_brl == pytest.approx(b.ke_brl)


def test_o_setor_de_bancos_ja_vem_marcado():
    """Quem escolhe o setor na tela não precisa saber da regra para acertar."""
    from valuation.dados_setoriais import buscar_setor, premissas_do_setor

    assert buscar_setor("Bancos e servicos financeiros").financeiro
    assert premissas_do_setor(
        "Bancos e servicos financeiros", divida_pl_alvo=11.2
    ).instituicao_financeira

    assert not buscar_setor("Bens de capital").financeiro
    assert not premissas_do_setor("Bens de capital").instituicao_financeira


# ---------------------------------------------------------------------------
# CAPM local: NTN-B + premio local, sem risco-pais
# ---------------------------------------------------------------------------


def _premissas_locais(**extra):
    from valuation import PremissasCustoCapital
    from valuation.custo_capital import rf_local

    padrao = dict(
        rf_brl=rf_local(0.08, 0.04),
        erp_local=0.075,
        beta_alavancado_setor=1.05,
        divida_pl_setor=0.45,
        divida_pl_alvo=0.50,
        spread_credito=0.025,
    )
    padrao.update(extra)
    return PremissasCustoCapital(**padrao)


def test_a_ntnb_e_nominalizada_por_composicao():
    """`(1 + real) x (1 + inflacao) - 1`, e nao a soma dos dois.

    Somar subestima, e num rf que desconta todo ano projetado a diferenca nao
    fica pequena: a 8% real com 4% de IPCA, sao 12,32% contra 12,00%.
    """
    from valuation.custo_capital import rf_local

    assert rf_local(0.08, 0.04) == pytest.approx(1.08 * 1.04 - 1)
    assert rf_local(0.08, 0.04) > 0.08 + 0.04


def test_o_caminho_local_nao_soma_risco_pais():
    """Ele ja esta dentro da NTN-B; soma-lo de novo o contaria duas vezes.

    E a mesma dupla contagem que o caminho em dolar existe para evitar, pelo
    outro lado -- por isso o `risco_pais` das premissas nao pode mover o Ke aqui.
    """
    from valuation import PremissasMacro
    from valuation.custo_capital import calcular_custo_capital

    macro = PremissasMacro(inflacao_brl=0.04, inflacao_usd=0.023, aliquota_ir=0.34)
    sem = calcular_custo_capital(_premissas_locais(risco_pais=0.0), macro)
    com = calcular_custo_capital(_premissas_locais(risco_pais=0.10), macro)
    assert sem.ke_brl == pytest.approx(com.ke_brl)
    assert sem.wacc_brl == pytest.approx(com.wacc_brl)


def test_o_ke_local_e_o_rf_mais_beta_vezes_o_premio():
    """A conta inteira, refeita a mao."""
    from valuation import PremissasMacro
    from valuation.custo_capital import calcular_custo_capital

    macro = PremissasMacro(inflacao_brl=0.04, inflacao_usd=0.023, aliquota_ir=0.34)
    premissas = _premissas_locais()
    resultado = calcular_custo_capital(premissas, macro)

    esperado = premissas.rf_brl + resultado.beta_realavancado * premissas.erp_local
    assert resultado.ke_brl == pytest.approx(esperado)


def test_o_caminho_em_dolar_nao_mudou():
    """A construcao antiga continua identica: a nova e escolha, nao troca."""
    from valuation import PremissasCustoCapital, PremissasMacro
    from valuation.custo_capital import calcular_custo_capital, converter_taxa

    macro = PremissasMacro(inflacao_brl=0.04, inflacao_usd=0.023, aliquota_ir=0.34)
    p = PremissasCustoCapital(
        metodo="usd",
        beta_alavancado_setor=1.05,
        divida_pl_setor=0.45,
        divida_pl_alvo=0.50,
    )
    r = calcular_custo_capital(p, macro)
    esperado = (
        p.rf_usd + r.beta_realavancado * p.erp_maduro + p.lambda_pais * p.risco_pais
    )
    assert r.ke_usd == pytest.approx(esperado)
    assert r.ke_brl == pytest.approx(
        converter_taxa(esperado, macro.inflacao_brl, macro.inflacao_usd)
    )


def test_sem_rf_informado_ele_e_derivado_da_ntnb_de_referencia():
    """`rf_brl` vazio nao e erro: e derivado, e por isso o app abre funcionando.

    A taxa real de referencia e composta com a inflacao do bloco macro -- e a
    composicao acontece **ali**, e nao nas premissas, porque e ali que a inflacao
    existe. Quem informa um `rf_brl` fixa o numero e ignora a macro, que e o
    comportamento certo para quem quer um rf especifico.
    """
    from valuation import PremissasCustoCapital, PremissasMacro
    from valuation.custo_capital import (
        NTNB_REAL_REFERENCIA,
        calcular_custo_capital,
        rf_local,
    )

    macro = PremissasMacro(inflacao_brl=0.05)
    derivado = calcular_custo_capital(
        PremissasCustoCapital(beta_desalavancado=1.0), macro
    )
    assert derivado.rf_brl == pytest.approx(
        rf_local(NTNB_REAL_REFERENCIA, macro.inflacao_brl)
    )

    # E o informado manda, sem olhar a macro.
    fixo = calcular_custo_capital(
        PremissasCustoCapital(beta_desalavancado=1.0, rf_brl=0.11), macro
    )
    assert fixo.rf_brl == pytest.approx(0.11)


def test_o_caminho_local_e_o_padrao():
    """Pedido do dono do projeto: a NTN-B e o ponto de partida, o dolar e a
    alternativa."""
    from valuation import PremissasCustoCapital

    assert PremissasCustoCapital(beta_desalavancado=1.0).metodo == "local"
    assert PremissasCustoCapital(beta_desalavancado=1.0).erp_local == pytest.approx(0.03)


def test_metodo_desconhecido_e_rejeitado():
    from valuation import PremissasCustoCapital

    with pytest.raises(ValueError, match="metodo de custo de capital"):
        PremissasCustoCapital(metodo="chute", beta_alavancado_setor=1.0)


# ---------------------------------------------------------------------------
# A referencia embarcada envelhece, e diz isso
# ---------------------------------------------------------------------------


def test_a_taxa_de_referencia_carrega_a_data_em_que_foi_medida():
    """Ela decide o WACC de todo modelo que nao toca no campo.

    A curva se move todo dia; um numero embarcado com cara de numero buscado e o
    pior tipo de desatualizado, o que nao se anuncia -- a mesma licao da safra
    dos percentis e do universo de pares.
    """
    from datetime import date, timedelta

    from valuation.custo_capital import (
        DIAS_ATE_A_REFERENCIA_ENVELHECER,
        NTNB_MEDIDA_EM,
        idade_da_referencia_ntnb,
        referencia_ntnb_envelheceu,
    )

    assert isinstance(NTNB_MEDIDA_EM, date)
    assert idade_da_referencia_ntnb(NTNB_MEDIDA_EM) == 0
    assert not referencia_ntnb_envelheceu(NTNB_MEDIDA_EM)

    velha = NTNB_MEDIDA_EM + timedelta(days=DIAS_ATE_A_REFERENCIA_ENVELHECER + 1)
    assert referencia_ntnb_envelheceu(velha)
    assert idade_da_referencia_ntnb(velha) > DIAS_ATE_A_REFERENCIA_ENVELHECER

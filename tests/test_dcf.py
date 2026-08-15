"""Testes do fluxo de caixa descontado."""

from __future__ import annotations

import numpy as np
import pytest

from valuation import (
    PonteValor,
    PremissasPerpetuidade,
    avaliar,
    avaliar_dcf,
    fatores_desconto,
    ponte_ev_equity,
    projetar,
    substituir_varios,
)
from valuation.dcf import valor_terminal_gordon, valor_terminal_multiplo
from valuation.projecao import Projecao


def _projecao_plana(fluxo: float = 100.0, anos: int = 3) -> Projecao:
    """Projecao artificial com FCFF constante, para conferir contas fechadas."""
    vetor = np.full(anos, fluxo)
    return Projecao(
        anos=list(range(1, anos + 1)),
        receita=vetor * 10,
        ebitda=vetor * 2,
        depreciacao=np.zeros(anos),
        ebit=vetor,
        impostos=np.zeros(anos),
        nopat=vetor,
        capex=np.zeros(anos),
        capital_giro=np.zeros(anos),
        variacao_capital_giro=np.zeros(anos),
        fcff=vetor,
    )


def test_fatores_de_desconto_fim_de_ano():
    fatores = fatores_desconto(0.10, 3)
    assert fatores == pytest.approx([1 / 1.1, 1 / 1.1**2, 1 / 1.1**3])


def test_fatores_de_desconto_meio_de_ano():
    fatores = fatores_desconto(0.10, 2, meio_de_ano=True)
    assert fatores == pytest.approx([1 / 1.1**0.5, 1 / 1.1**1.5])


def test_meio_de_ano_aumenta_o_valor():
    """Receber antes vale mais: a convencao de meio de ano eleva o VP."""
    assert (fatores_desconto(0.10, 5, True) > fatores_desconto(0.10, 5, False)).all()


def test_perpetuidade_de_fluxo_constante_fecha_com_a_conta_direta():
    """FCFF de 100 perpetuo a 10% vale exatamente 1.000, venha por onde vier."""
    resultado = avaliar_dcf(
        _projecao_plana(100.0, anos=3),
        taxa_desconto=0.10,
        perpetuidade=PremissasPerpetuidade(metodo="gordon", crescimento_perpetuo=0.0),
    )
    assert resultado.enterprise_value == pytest.approx(1000.0)
    assert resultado.valor_presente_explicito == pytest.approx(248.6852, abs=1e-4)
    assert resultado.valor_presente_terminal == pytest.approx(751.3148, abs=1e-4)


def test_gordon_simples():
    # 100 * 1.03 / (0.10 - 0.03)
    assert valor_terminal_gordon(100, taxa=0.10, crescimento=0.03) == pytest.approx(
        103 / 0.07
    )


def test_gordon_normalizado_por_roic():
    """Crescer 4% com ROIC de 16% exige reinvestir 25% do NOPAT."""
    vt = valor_terminal_gordon(
        fluxo_final=999.0,  # ignorado quando ha ROIC
        taxa=0.10,
        crescimento=0.04,
        nopat_final=100.0,
        roic=0.16,
    )
    assert vt == pytest.approx(100 * 1.04 * 0.75 / 0.06)


def test_normalizacao_por_roic_reduz_o_valor_terminal_quando_o_capex_e_baixo():
    sem_roic = valor_terminal_gordon(100.0, taxa=0.10, crescimento=0.04)
    com_roic = valor_terminal_gordon(
        100.0, taxa=0.10, crescimento=0.04, nopat_final=100.0, roic=0.12
    )
    assert com_roic < sem_roic


def test_crescimento_acima_da_taxa_e_rejeitado():
    with pytest.raises(ValueError, match="maior que o crescimento"):
        valor_terminal_gordon(100, taxa=0.05, crescimento=0.06)


def test_crescimento_igual_a_taxa_e_rejeitado():
    with pytest.raises(ValueError):
        valor_terminal_gordon(100, taxa=0.05, crescimento=0.05)


def test_crescimento_acima_do_roic_e_rejeitado():
    with pytest.raises(ValueError, match="ROIC"):
        valor_terminal_gordon(
            100, taxa=0.20, crescimento=0.15, nopat_final=100, roic=0.10
        )


def test_valor_terminal_por_multiplo():
    assert valor_terminal_multiplo(200.0, 7.5) == pytest.approx(1500.0)


def test_multiplo_de_saida_usa_o_ebitda_do_ultimo_ano():
    projecao = _projecao_plana(100.0, anos=3)  # EBITDA = 200
    resultado = avaliar_dcf(
        projecao,
        taxa_desconto=0.10,
        perpetuidade=PremissasPerpetuidade(metodo="multiplo", multiplo_saida=6.0),
    )
    assert resultado.valor_terminal == pytest.approx(1200.0)
    assert resultado.valor_presente_terminal == pytest.approx(1200.0 / 1.1**3)


def test_ponte_ev_equity():
    equity, detalhe = ponte_ev_equity(
        1000.0,
        PonteValor(divida_bruta=300.0, caixa=50.0, minoritarios=20.0, contingencias=10.0),
    )
    assert equity == pytest.approx(1000 - 300 + 50 - 20 - 10)
    assert detalhe.loc["Equity Value", "Valor"] == pytest.approx(equity)


def test_ativos_nao_operacionais_somam_ao_equity():
    equity, _ = ponte_ev_equity(1000.0, PonteValor(ativos_nao_operacionais=120.0))
    assert equity == pytest.approx(1120.0)


def test_valor_por_acao(empresa_exemplo):
    resultado = avaliar(empresa_exemplo)
    assert resultado.valor_por_acao == pytest.approx(resultado.equity_value / 150.0)


def test_peso_da_perpetuidade_soma_um_com_o_periodo_explicito(empresa_exemplo):
    resultado = avaliar(empresa_exemplo)
    peso_explicito = (
        resultado.dcf.valor_presente_explicito / resultado.enterprise_value
    )
    assert peso_explicito + resultado.dcf.peso_perpetuidade == pytest.approx(1.0)


def test_wacc_maior_reduz_o_valor(empresa_exemplo):
    base = avaliar(empresa_exemplo)
    caro = avaliar(empresa_exemplo, taxa_desconto=base.dcf.taxa_desconto + 0.02)
    assert caro.equity_value < base.equity_value


def test_fcfe_descontado_ao_ke_chega_direto_ao_equity(empresa_exemplo):
    """O caminho do FCFE nao aplica a ponte: ele ja parte do fluxo do acionista."""
    resultado = avaliar(
        empresa_exemplo,
        tipo_fluxo="fcfe",
        divida_por_ano=[900.0, 900.0, 900.0],
    )
    esperado = (
        resultado.dcf.valor_presente_explicito + resultado.dcf.valor_presente_terminal
    )
    assert resultado.equity_value == pytest.approx(esperado)
    assert resultado.dcf.taxa_desconto == pytest.approx(
        resultado.custo_capital.ke_brl
    )


def test_fcfe_sem_projecao_de_divida_falha(empresa_exemplo):
    with pytest.raises(ValueError, match="FCFE"):
        avaliar(empresa_exemplo, tipo_fluxo="fcfe")


def test_empresa_sem_premissas_operacionais_falha(empresa_exemplo):
    from valuation import Empresa

    vazia = Empresa(nome="Sem projecao")
    with pytest.raises(ValueError, match="premissas operacionais"):
        avaliar(vazia)


def test_metodo_multiplo_exige_multiplo(empresa_exemplo):
    with pytest.raises(ValueError, match="multiplo_saida"):
        substituir_varios(empresa_exemplo, {"perpetuidade.metodo": "multiplo"})


def test_alterar_metodo_e_multiplo_juntos_funciona(empresa_exemplo):
    """Duas premissas do mesmo bloco precisam ser aplicadas na mesma operacao."""
    empresa = substituir_varios(
        empresa_exemplo,
        {"perpetuidade.metodo": "multiplo", "perpetuidade.multiplo_saida": 7.0},
    )
    resultado = avaliar(empresa)
    assert resultado.dcf.valor_terminal == pytest.approx(
        resultado.projecao.ebitda[-1] * 7.0
    )


def test_premissas_originais_nao_sao_alteradas(empresa_exemplo):
    g_original = empresa_exemplo.perpetuidade.crescimento_perpetuo
    substituir_varios(empresa_exemplo, {"perpetuidade.crescimento_perpetuo": 0.01})
    assert empresa_exemplo.perpetuidade.crescimento_perpetuo == g_original


def test_caminho_inexistente_e_rejeitado(empresa_exemplo):
    with pytest.raises(ValueError, match="nao tem o campo"):
        substituir_varios(empresa_exemplo, {"perpetuidade.crescimento_eterno": 0.03})


def test_escalar_aplicado_a_lista_vale_para_todos_os_anos(empresa_exemplo):
    empresa = substituir_varios(empresa_exemplo, {"operacionais.margem_ebitda": 0.25})
    assert empresa.operacionais.margem_ebitda == [0.25, 0.25, 0.25]

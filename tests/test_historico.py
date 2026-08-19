"""Testes da analise historica e da sugestao de premissas."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from valuation.historico import analisar, crescimento_composto, sugerir_premissas
from valuation.importacao import Demonstracoes


def _demonstracoes(dados: dict[str, list[float]], anos: list[int]) -> Demonstracoes:
    valores = pd.DataFrame(dados, index=anos).T
    return Demonstracoes(empresa="Teste S.A.", valores=valores, unidade="R$ milhoes")


ANOS = [2021, 2022, 2023, 2024]


@pytest.fixture
def dfs() -> Demonstracoes:
    """Empresa com numeros escolhidos para que as contas fechem na mao."""
    return _demonstracoes(
        {
            "receita_liquida": [1000.0, 1100.0, 1210.0, 1331.0],  # +10% a.a.
            "custo_produtos_vendidos": [600.0, 660.0, 726.0, 798.6],
            "depreciacao_amortizacao": [50.0, 55.0, 60.5, 66.55],
            "ebit": [200.0, 220.0, 242.0, 266.2],                  # margem 20%
            "lucro_antes_impostos": [150.0, 165.0, 181.5, 199.65],
            "impostos": [45.0, 49.5, 54.45, 59.895],               # 30% efetivo
            "lucro_liquido": [105.0, 115.5, 127.05, 139.755],
            "caixa_equivalentes": [100.0, 110.0, 120.0, 130.0],
            "contas_receber": [150.0, 165.0, 181.5, 199.65],
            "estoques": [100.0, 110.0, 121.0, 133.1],
            "fornecedores": [100.0, 110.0, 121.0, 133.1],
            "imobilizado": [600.0, 650.0, 700.0, 750.0],
            "ativo_total": [1200.0, 1300.0, 1400.0, 1500.0],
            "divida_curto_prazo": [100.0, 100.0, 100.0, 100.0],
            "divida_longo_prazo": [400.0, 420.0, 440.0, 460.0],
            "despesas_financeiras": [50.0, 55.0, 60.5, 66.55],
            "patrimonio_liquido": [500.0, 560.0, 620.0, 680.0],
            "capex": [100.0, 105.0, 110.0, 116.55],
        },
        ANOS,
    )


# ---------------------------------------------------------------------------
# Indicadores
# ---------------------------------------------------------------------------


def test_crescimento_e_margens(dfs):
    a = analisar(dfs)
    assert np.isnan(a.linha("Crescimento da receita").iloc[0])  # sem ano anterior
    assert a.linha("Crescimento da receita").iloc[1] == pytest.approx(0.10)
    assert a.linha("Margem EBIT").iloc[-1] == pytest.approx(0.20)
    assert a.linha("Margem bruta").iloc[-1] == pytest.approx(0.40)


def test_margem_ebitda_usa_ebit_mais_depreciacao(dfs):
    a = analisar(dfs)
    esperado = (266.2 + 66.55) / 1331.0
    assert a.linha("Margem EBITDA").iloc[-1] == pytest.approx(esperado)


def test_aliquota_efetiva_vem_do_historico(dfs):
    a = analisar(dfs)
    assert a.linha("Aliquota efetiva de IR").iloc[-1] == pytest.approx(0.30)


def test_retorno_usa_capital_medio(dfs):
    """ROE do primeiro ano e indefinido: nao ha saldo de abertura."""
    a = analisar(dfs)
    assert np.isnan(a.linha("ROE").iloc[0])
    patrimonio_medio = (560.0 + 500.0) / 2
    assert a.linha("ROE").iloc[1] == pytest.approx(115.5 / patrimonio_medio)


def test_roic_usa_capital_investido_medio(dfs):
    a = analisar(dfs)
    # Capital investido = divida liquida + patrimonio liquido
    ci_2021 = (500.0 - 100.0) + 500.0
    ci_2022 = (520.0 - 110.0) + 560.0
    nopat_2022 = 220.0 * (1 - 0.30)
    assert a.linha("ROIC").iloc[1] == pytest.approx(nopat_2022 / ((ci_2021 + ci_2022) / 2))


def test_dupont_multiplica_de_volta_ao_roe(dfs):
    """A decomposicao so vale se reconstituir o indicador decomposto."""
    a = analisar(dfs)
    d = a.decomposicao_dupont()
    produto = (
        d.loc["Margem liquida"] * d.loc["Giro do ativo"] * d.loc["Alavancagem financeira"]
    )
    pd.testing.assert_series_equal(
        produto.dropna(), d.loc["ROE"].dropna(), check_names=False
    )


def test_decomposicao_roic_multiplica_de_volta(dfs):
    a = analisar(dfs)
    d = a.decomposicao_roic()
    produto = d.loc["Margem NOPAT"] * d.loc["Giro do capital investido"]
    pd.testing.assert_series_equal(
        produto.dropna(), d.loc["ROIC"].dropna(), check_names=False
    )


def test_crescimento_fundamentado_e_reinvestimento_vezes_roic(dfs):
    a = analisar(dfs)
    esperado = a.linha("Taxa de reinvestimento") * a.linha("ROIC")
    pd.testing.assert_series_equal(
        a.linha("Crescimento fundamentado (reinvest. x ROIC)").dropna(),
        esperado.dropna(),
        check_names=False,
    )


def test_reinvestimento_e_capex_liquido_mais_variacao_de_giro(dfs):
    a = analisar(dfs)
    # 2022: capex 105 - depreciacao 55 + variacao do giro (165+110-110) - (150+100-100)
    esperado = 105.0 - 55.0 + (165.0 + 110.0 - 110.0) - (150.0 + 100.0 - 100.0)
    assert a.linha("Reinvestimento").iloc[1] == pytest.approx(esperado)


def test_ciclo_de_caixa(dfs):
    a = analisar(dfs)
    ciclo = a.ciclo_de_caixa()
    dso = 199.65 * 365 / 1331.0
    assert ciclo.loc["Prazo medio de recebimento (dias)"].iloc[-1] == pytest.approx(dso)
    soma = (
        ciclo.loc["Prazo medio de recebimento (dias)"].iloc[-1]
        + ciclo.loc["Prazo medio de estoque (dias)"].iloc[-1]
        - ciclo.loc["Prazo medio de pagamento (dias)"].iloc[-1]
    )
    assert ciclo.loc["Ciclo de conversao de caixa (dias)"].iloc[-1] == pytest.approx(soma)


def test_custo_da_divida_efetivo(dfs):
    a = analisar(dfs)
    divida_media = ((100.0 + 400.0) + (100.0 + 420.0)) / 2
    assert a.linha("Custo da divida efetivo").iloc[1] == pytest.approx(55.0 / divida_media)


def test_divida_liquida_sobre_ebitda(dfs):
    a = analisar(dfs)
    esperado = (560.0 - 130.0) / (266.2 + 66.55)
    assert a.linha("Divida liquida / EBITDA").iloc[-1] == pytest.approx(esperado)


def test_denominador_negativo_vira_nan():
    """Patrimonio liquido negativo nao pode produzir um ROE com sinal invertido."""
    dfs = _demonstracoes(
        {
            "receita_liquida": [1000.0, 1100.0],
            "ebit": [100.0, 110.0],
            "lucro_liquido": [-50.0, -60.0],
            "patrimonio_liquido": [-100.0, -160.0],
            "ativo_total": [500.0, 520.0],
        },
        [2023, 2024],
    )
    a = analisar(dfs)
    assert np.isnan(a.linha("ROE").iloc[-1])


def test_resumo_traz_ultimo_e_mediana(dfs):
    resumo = analisar(dfs).resumo()
    assert {"Ultimo ano", "Mediana", "Minimo", "Maximo"} == set(resumo.columns)
    assert resumo.loc["Margem EBIT", "Ultimo ano"] == pytest.approx(0.20)


def test_cagr(dfs):
    assert crescimento_composto(dfs.serie("receita_liquida")) == pytest.approx(0.10)


def test_cagr_com_um_ponto_e_indefinido():
    assert np.isnan(crescimento_composto(pd.Series([100.0])))


def test_analise_sem_anos_falha():
    vazio = Demonstracoes(empresa="X", valores=pd.DataFrame())
    with pytest.raises(ValueError, match="nenhum ano"):
        analisar(vazio)


# ---------------------------------------------------------------------------
# Premissas sugeridas
# ---------------------------------------------------------------------------


def test_premissas_sugeridas_partem_do_historico(dfs):
    sugestao = sugerir_premissas(analisar(dfs), horizonte=5)
    op = sugestao.operacionais

    assert op.receita_base == pytest.approx(1331.0)
    assert op.horizonte == 5
    assert op.ano_base == 2024
    # Margem sugerida = mediana historica da margem EBITDA
    assert op.margem_ebitda[0] == pytest.approx(analisar(dfs).mediana("Margem EBITDA"))


def test_crescimento_converge_para_o_longo_prazo(dfs):
    sugestao = sugerir_premissas(analisar(dfs), horizonte=5, crescimento_de_longo_prazo=0.04)
    crescimentos = sugestao.operacionais.crescimento_receita
    assert crescimentos[0] == pytest.approx(0.10)   # CAGR historico
    assert crescimentos[-1] == pytest.approx(0.04)  # longo prazo
    assert all(a >= b for a, b in zip(crescimentos, crescimentos[1:]))


def test_ponte_sugerida_vem_do_balanco(dfs):
    sugestao = sugerir_premissas(analisar(dfs))
    assert sugestao.ponte.divida_bruta == pytest.approx(560.0)
    assert sugestao.ponte.caixa == pytest.approx(130.0)
    assert sugestao.ponte.divida_liquida == pytest.approx(430.0)


def test_custo_de_capital_sugerido_usa_divida_e_juros_do_historico(dfs):
    sugestao = sugerir_premissas(analisar(dfs))
    assert sugestao.custo_capital.divida_pl_alvo == pytest.approx(560.0 / 680.0)
    assert sugestao.custo_capital.custo_divida_brl is not None


def test_toda_premissa_sugerida_tem_justificativa(dfs):
    """Uma premissa que o analista nao consegue explicar nao deveria ser sugerida."""
    sugestao = sugerir_premissas(analisar(dfs))
    for chave in (
        "crescimento_receita",
        "margem_ebitda",
        "capex_pct_receita",
        "capital_giro_pct_receita",
        "ponte",
        "custo_capital",
    ):
        assert chave in sugestao.justificativas
        assert len(sugestao.justificativas[chave]) > 20


def test_beta_generico_vira_alerta(dfs):
    sugestao = sugerir_premissas(analisar(dfs))
    assert any("beta" in alerta.lower() for alerta in sugestao.alertas)


def test_crescimento_explosivo_e_limitado():
    dfs = _demonstracoes(
        {
            "receita_liquida": [100.0, 300.0, 900.0],
            "ebit": [10.0, 30.0, 90.0],
            "lucro_liquido": [5.0, 15.0, 45.0],
            "ativo_total": [200.0, 400.0, 800.0],
            "patrimonio_liquido": [100.0, 200.0, 400.0],
            "caixa_equivalentes": [10.0, 20.0, 30.0],
        },
        [2022, 2023, 2024],
    )
    sugestao = sugerir_premissas(analisar(dfs), horizonte=5)
    assert sugestao.operacionais.crescimento_receita[0] == pytest.approx(0.30)
    assert any("30%" in alerta for alerta in sugestao.alertas)


def test_receita_em_queda_gera_alerta():
    dfs = _demonstracoes(
        {
            "receita_liquida": [1000.0, 900.0, 810.0],
            "ebit": [100.0, 80.0, 60.0],
            "lucro_liquido": [50.0, 40.0, 30.0],
            "ativo_total": [1000.0, 950.0, 900.0],
            "patrimonio_liquido": [500.0, 480.0, 460.0],
            "caixa_equivalentes": [50.0, 45.0, 40.0],
        },
        [2022, 2023, 2024],
    )
    sugestao = sugerir_premissas(analisar(dfs))
    assert sugestao.operacionais.crescimento_receita[0] < 0
    assert any("encolheu" in alerta for alerta in sugestao.alertas)


def test_sem_receita_nao_da_para_sugerir():
    dfs = _demonstracoes({"ebit": [100.0, 110.0]}, [2023, 2024])
    with pytest.raises(ValueError, match="receita liquida"):
        sugerir_premissas(analisar(dfs))


def test_premissas_sugeridas_rodam_no_motor(dfs):
    """A sugestao precisa ser diretamente avaliavel, sem ajuste manual."""
    from valuation import Empresa, PremissasPerpetuidade, avaliar

    sugestao = sugerir_premissas(analisar(dfs), horizonte=5)
    empresa = Empresa(
        nome="Teste S.A.",
        operacionais=sugestao.operacionais,
        ponte=sugestao.ponte,
        custo_capital=sugestao.custo_capital,
        perpetuidade=PremissasPerpetuidade(crescimento_perpetuo=0.04),
    )
    resultado = avaliar(empresa)
    assert np.isfinite(resultado.equity_value)
    assert resultado.projecao.receita[0] > dfs.valor("receita_liquida")


# ---------------------------------------------------------------------------
# A margem sugerida parte da recorrente
# ---------------------------------------------------------------------------


def _com_nao_recorrente(itens: list[float]) -> Demonstracoes:
    anos = [2022, 2023, 2024]
    base = {
        "receita_liquida": [1000.0] * 3,
        "custo_produtos_vendidos": [600.0] * 3,
        "lucro_bruto": [400.0] * 3,
        "ebit": [200.0 + i for i in itens],
        "depreciacao_amortizacao": [50.0] * 3,
        "outras_receitas_operacionais": itens,
        "lucro_liquido": [120.0] * 3,
        "ativo_total": [2000.0] * 3,
        "patrimonio_liquido": [900.0] * 3,
    }
    return Demonstracoes(
        empresa="Teste", valores=pd.DataFrame(base, index=anos).T
    )


def test_a_margem_sugerida_tira_o_que_nao_se_repete():
    """Ganho de R$ 100 num EBIT de R$ 300 e evento, nao regime.

    Sem o ajuste a sugestao projetaria 35% de margem EBITDA para sempre; com
    ele, os 25% que o negocio entrega.
    """
    analise = analisar(_com_nao_recorrente([100.0, 100.0, 100.0]))
    assert analise.mediana("Margem EBITDA") == pytest.approx(0.35)
    assert analise.mediana("Margem EBITDA recorrente") == pytest.approx(0.25)

    sugestao = sugerir_premissas(analise)
    assert sugestao.operacionais.margem_ebitda[0] == pytest.approx(0.25)
    assert "recorrente" in sugestao.justificativas["margem_ebitda"]


def test_o_ajuste_vai_nos_dois_sentidos():
    """Quando o item foi **perda**, a recorrente e maior que a reportada.

    E o caso da Vale, onde o item foi impairment: reportada de 38,7% contra
    51,9% recorrente na mediana de 2020-2024.
    """
    analise = analisar(_com_nao_recorrente([-80.0, -80.0, -80.0]))
    assert analise.mediana("Margem EBITDA") == pytest.approx(0.17)
    assert analise.mediana("Margem EBITDA recorrente") == pytest.approx(0.25)
    assert sugerir_premissas(analise).operacionais.margem_ebitda[0] == pytest.approx(0.25)


def test_a_diferenca_relevante_vira_alerta():
    """Trocar a base da projecao sem avisar e mudar o numero em silencio."""
    sugestao = sugerir_premissas(analisar(_com_nao_recorrente([100.0] * 3)))
    assert any("recorrente" in a and "reportada" in a for a in sugestao.alertas), (
        sugestao.alertas
    )


def test_sem_item_nao_recorrente_a_sugestao_nao_muda():
    """Quem nao publica os itens tem reportada e recorrente iguais."""
    analise = analisar(_com_nao_recorrente([0.0, 0.0, 0.0]))
    assert "Margem EBITDA recorrente" not in analise.indicadores.index
    sugestao = sugerir_premissas(analise)
    assert sugestao.operacionais.margem_ebitda[0] == pytest.approx(0.25)
    assert not any("recorrente" in a and "reportada" in a for a in sugestao.alertas)

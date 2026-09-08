"""Testes da analise historica e da sugestao de premissas."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from valuation.historico import analisar, crescimento_composto, sugerir_premissas
from valuation.importacao import Demonstracoes


def _demonstracoes(
    dados: dict[str, list[float]], anos: list[int], periodicidade: str = "anual"
) -> Demonstracoes:
    valores = pd.DataFrame(dados, index=anos).T
    return Demonstracoes(
        empresa="Teste S.A.",
        valores=valores,
        unidade="R$ milhoes",
        periodicidade=periodicidade,
    )


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


# ---------------------------------------------------------------------------
# O ciclo de conversao de caixa
# ---------------------------------------------------------------------------


def test_a_ponte_do_ciclo_e_uma_identidade(dfs):
    """As três pernas têm de somar exatamente a variação do ciclo.

    `CCC = PMR + PME − PMP` é definição, então `ΔCCC = ΔPMR + ΔPME − ΔPMP`
    também é — sem termo residual. Uma ponte que não fecha deixa de ser ponte e
    vira atribuição, que é o que este projeto recusa no TSR e na conversão de
    caixa pelos mesmos motivos.
    """
    from valuation.historico import NOME_DO_PMP, ponte_do_ciclo

    ponte = ponte_do_ciclo(analisar(dfs))
    assert ponte is not None

    soma = sum(p.contribuicao for p in ponte.pernas)
    assert soma == pytest.approx(ponte.variacao)
    assert ponte.fecha

    # O sinal do fornecedor é invertido, e essa é a informação: alongar o prazo
    # de pagamento **encurta** o ciclo. Sem inverter, a soma não fecharia.
    pagamento = next(p for p in ponte.pernas if p.nome == NOME_DO_PMP)
    assert pagamento.contribuicao == pytest.approx(-pagamento.variacao)


def test_o_prazo_medio_usa_a_duracao_do_periodo_e_nao_365_fixo():
    """Numa série trimestral o denominador é a receita de três meses.

    Com a constante de 365 aplicada a um trimestre, o prazo médio sai **4x**
    maior: medido na WEG antes da correção, o ciclo lia 689 dias contra os 166
    do exercício. É um número errado com cara de número plausível, porque dia é
    dia e nada na tela dizia que aquele denominador era de 90.
    """
    from valuation.historico import NOME_DO_CICLO, dias_do_periodo

    # A duracao vem **declarada**, e nao do rotulo: o ano movel tem rotulo de
    # trimestre e cobre doze meses, e inferir dali fazia o ciclo da WEG sair em
    # 43 dias onde ele e 166.
    assert list(dias_do_periodo([2023, 2024])) == [365.0, 365.0]
    assert list(dias_do_periodo(["1T25", "3T26"], "trimestral")) == [365 / 4, 365 / 4]
    assert list(dias_do_periodo(["1T25", "3T26"])) == [365.0, 365.0]

    anual = _demonstracoes(
        {
            "receita_liquida": [1000.0, 1000.0],
            "custo_produtos_vendidos": [600.0, 600.0],
            "contas_receber": [200.0, 200.0],
            "estoques": [150.0, 150.0],
            "fornecedores": [100.0, 100.0],
        },
        [2023, 2024],
    )
    # A mesma empresa medida por trimestre: receita e custo de tres meses, com
    # os mesmos saldos de balanco -- saldo e saldo, nao se divide por quatro.
    trimestral = _demonstracoes(
        {
            "receita_liquida": [250.0, 250.0],
            "custo_produtos_vendidos": [150.0, 150.0],
            "contas_receber": [200.0, 200.0],
            "estoques": [150.0, 150.0],
            "fornecedores": [100.0, 100.0],
        },
        ["1T24", "2T24"],
        periodicidade="trimestral",
    )

    ciclo_anual = analisar(anual).indicadores.loc[NOME_DO_CICLO].iloc[-1]
    ciclo_tri = analisar(trimestral).indicadores.loc[NOME_DO_CICLO].iloc[-1]

    # A mesma operacao lida nas duas frequencias tem de dar o mesmo prazo.
    assert ciclo_tri == pytest.approx(ciclo_anual, rel=0.001)


def test_o_caixa_preso_traduz_os_dias_em_dinheiro(dfs):
    """"O ciclo subiu 12 dias" não decide nada sem o tamanho em caixa."""
    from valuation.historico import NOME_DO_CICLO, caixa_preso_no_ciclo

    analise = analisar(dfs)
    caixa = caixa_preso_no_ciclo(analise)
    ciclo = analise.indicadores.loc[NOME_DO_CICLO]

    ultimo = caixa.index[-1]
    esperado = ciclo[ultimo] * dfs.serie("receita_liquida")[ultimo] / 365
    assert caixa[ultimo] == pytest.approx(esperado)


def test_o_cagr_conta_anos_e_nao_colunas():
    """O ano móvel rolante é onde contar colunas erra por quatro.

    Cada coluna dele cobre **doze meses** e a seguinte começa **três meses**
    depois: passo e duração são coisas diferentes, e quem calcula taxa ao ano
    precisa do passo. Medido na WEG, ano móvel de 2025: o CAGR saía em **1,67%**
    onde a anualização da mesma série dá **6,84%** — o mesmo erro do
    `DIAS_NO_ANO`, agora na premissa de crescimento.

    Ele estava justamente na leitura que o app **recomenda** quando recusa
    projetar sobre trimestres isolados.
    """
    from valuation.historico import anos_entre, crescimento_composto

    # Meio ano de distancia entre 1T25 e 3T25, e nao dois anos.
    assert anos_entre("1T25", "3T25") == pytest.approx(0.5)
    assert anos_entre("3T24", "3T25") == pytest.approx(1.0)
    assert anos_entre(2021, 2025) == pytest.approx(4.0)

    # +21% em meio ano sao 46,4% ao ano, e nao 10%.
    movel = pd.Series([100.0, 110.0, 121.0], index=["1T25", "2T25", "3T25"])
    assert crescimento_composto(movel) == pytest.approx(0.4641, abs=1e-4)

    # Serie anual nao se move: ali um passo **e** um ano.
    anual = pd.Series([100.0, 110.0, 121.0], index=[2023, 2024, 2025])
    assert crescimento_composto(anual) == pytest.approx(0.10)


def test_o_cagr_cai_no_passo_por_coluna_quando_o_rotulo_nao_e_periodo():
    """Planilha com cabeçalho livre continua funcionando como sempre funcionou."""
    from valuation.historico import crescimento_composto

    livre = pd.Series([100.0, 121.0], index=["antes", "depois"])
    assert crescimento_composto(livre) == pytest.approx(0.21)


def test_cagr_sobre_menos_de_um_ano_nao_vira_premissa_de_crescimento():
    """O ano móvel montado de um ITR nunca chega a um ano de intervalo.

    Medido em 25 companhias com o ITR de 2026: **as 25 têm span de 0,25 ano** —
    duas colunas, porque só dois trimestres foram publicados. Anualizar o
    movimento de um trimestre eleva o ruído à quarta potência, e o resultado
    virava a premissa de crescimento **perpétuo**: P10 de −13,9%, P90 de +24,2%,
    e |CAGR| acima de 30% em 3 das 25.

    Isto **não** é a guarda de frequência — o ano móvel é anual por conteúdo e a
    projeção o aceita. É outra pergunta: a série é longa o bastante para ter
    tendência? Ela vale igual para uma série anual de um ano só.
    """
    from valuation.historico import sugerir_premissas

    # Duas colunas de ano movel: conteudo de doze meses, tres meses de intervalo.
    curta = _demonstracoes(
        {
            "receita_liquida": [1000.0, 1030.0],
            "custo_produtos_vendidos": [600.0, 618.0],
            "ebit": [200.0, 206.0],
            "depreciacao_amortizacao": [50.0, 51.5],
            "ativo_total": [1500.0, 1545.0],
            "patrimonio_liquido": [700.0, 721.0],
        },
        ["1T26", "2T26"],
    )
    sugestao = sugerir_premissas(analisar(curta))

    # 3% num trimestre viraria 12,6% ao ano; a premissa nao parte dai.
    assert sugestao.operacionais.crescimento_receita[0] == pytest.approx(0.045)
    assert "meses" in " ".join(sugestao.alertas)
    # A justificativa nao pode dizer "CAGR historico" quando nao foi ele.
    assert "CAGR" not in sugestao.justificativas["crescimento_receita"]


def test_serie_anual_longa_continua_partindo_do_cagr():
    """O controle: a guarda do span não pode tocar no caminho normal."""
    from valuation.historico import sugerir_premissas

    longa = _demonstracoes(
        {
            "receita_liquida": [1000.0, 1100.0, 1210.0, 1331.0],
            "custo_produtos_vendidos": [600.0, 660.0, 726.0, 798.6],
            "ebit": [200.0, 220.0, 242.0, 266.2],
            "depreciacao_amortizacao": [50.0, 55.0, 60.5, 66.55],
            "ativo_total": [1500.0, 1650.0, 1815.0, 1996.5],
            "patrimonio_liquido": [700.0, 770.0, 847.0, 931.7],
        },
        [2022, 2023, 2024, 2025],
    )
    sugestao = sugerir_premissas(analisar(longa))
    assert sugestao.operacionais.crescimento_receita[0] == pytest.approx(0.10)
    assert "CAGR" in sugestao.justificativas["crescimento_receita"]


def test_a_guarda_de_span_protege_o_caminho_da_planilha():
    """Com três ITRs ela deixou de disparar na CVM, e continua necessária aqui.

    Medido com o padrão novo: **0 de 57 companhias** produzem span entre 0 e 1
    ano pelo caminho da CVM — 40 do universo (mínimo 1,50 ano) e 17 de fora dele
    (mínimo 2,00). As três sem série são holdings e seguradoras sem linha de
    receita, que falham antes, em `len(valores) < 2`.

    Mas o usuário também importa **planilha**, e ali é ele quem escreve o
    cabeçalho da coluna. Duas colunas `1T26` e `2T26` cobrem três meses, e sem a
    guarda o movimento de um trimestre viraria a premissa de crescimento
    perpétuo.

    **A periodicidade e o span respondem perguntas diferentes**, e este teste é
    onde isso fica visível: a planilha se declara `anual` (é o padrão, e o app
    não tem como saber), então as guardas de *frequência* não disparam — e a de
    *span* dispara, porque ela lê a distância entre os rótulos. Quanto cada
    coluna cobre e quanto as colunas distam são coisas distintas.
    """
    from valuation.historico import sugerir_premissas

    planilha = _demonstracoes(
        {
            "receita_liquida": [1000.0, 1030.0],
            "custo_produtos_vendidos": [600.0, 618.0],
            "ebit": [200.0, 206.0],
            "depreciacao_amortizacao": [50.0, 51.5],
            "ativo_total": [1500.0, 1545.0],
            "patrimonio_liquido": [700.0, 721.0],
        },
        ["1T26", "2T26"],
    )
    # O importador de planilha nao declara periodicidade: fica no padrao.
    assert planilha.periodicidade == "anual"

    sugestao = sugerir_premissas(analisar(planilha))
    assert sugestao.operacionais.crescimento_receita[0] == pytest.approx(0.045)
    assert "3 meses" in " ".join(sugestao.alertas)

"""Testes de sensibilidade, cenarios e Monte Carlo."""

from __future__ import annotations

import numpy as np
import pytest

from valuation import Distribuicao, avaliar, cenarios, monte_carlo, tabela_sensibilidade


def test_tabela_tem_o_formato_dos_eixos(empresa_exemplo):
    tabela = tabela_sensibilidade(
        empresa_exemplo,
        ("wacc", [0.10, 0.11, 0.12]),
        ("perpetuidade.crescimento_perpetuo", [0.03, 0.04]),
    )
    assert tabela.shape == (3, 2)
    assert tabela.index.name == "wacc"
    assert tabela.columns.name == "perpetuidade.crescimento_perpetuo"


def test_valor_cai_com_wacc_maior_e_sobe_com_crescimento_maior(empresa_exemplo):
    tabela = tabela_sensibilidade(
        empresa_exemplo,
        ("wacc", [0.10, 0.11, 0.12]),
        ("perpetuidade.crescimento_perpetuo", [0.03, 0.04, 0.05]),
    )
    valores = tabela.to_numpy()
    assert (np.diff(valores, axis=0) < 0).all()  # WACC maior -> valor menor
    assert (np.diff(valores, axis=1) > 0).all()  # g maior -> valor maior


def test_celula_central_reproduz_o_caso_base(empresa_exemplo):
    """A tabela e o caso base precisam ser o mesmo modelo, nao dois parecidos."""
    base = avaliar(empresa_exemplo)
    tabela = tabela_sensibilidade(
        empresa_exemplo,
        ("wacc", [base.dcf.taxa_desconto]),
        (
            "perpetuidade.crescimento_perpetuo",
            [empresa_exemplo.perpetuidade.crescimento_perpetuo],
        ),
    )
    assert tabela.iloc[0, 0] == pytest.approx(base.equity_value)


def test_combinacao_inviavel_vira_nan(empresa_exemplo):
    """g acima do WACC nao pode virar um numero: tem que aparecer como vazio."""
    tabela = tabela_sensibilidade(
        empresa_exemplo,
        ("wacc", [0.05]),
        ("perpetuidade.crescimento_perpetuo", [0.09]),
    )
    assert np.isnan(tabela.iloc[0, 0])


def test_sensibilidade_respeita_a_convencao_de_meio_de_ano(empresa_exemplo):
    base = avaliar(empresa_exemplo, meio_de_ano=True)
    tabela = tabela_sensibilidade(
        empresa_exemplo,
        ("wacc", [base.dcf.taxa_desconto]),
        (
            "perpetuidade.crescimento_perpetuo",
            [empresa_exemplo.perpetuidade.crescimento_perpetuo],
        ),
        meio_de_ano=True,
    )
    assert tabela.iloc[0, 0] == pytest.approx(base.equity_value)


def test_cenario_base_vazio_reproduz_o_caso_base(empresa_exemplo):
    base = avaliar(empresa_exemplo)
    tabela = cenarios(
        empresa_exemplo,
        {"Base": {}, "Pessimista": {"operacionais.margem_ebitda": 0.15}},
    )
    assert tabela.loc["equity_value", "Base"] == pytest.approx(base.equity_value)
    assert tabela.loc["equity_value", "Pessimista"] < base.equity_value


def test_cenario_inviavel_reporta_erro_em_vez_de_quebrar(empresa_exemplo):
    tabela = cenarios(
        empresa_exemplo, {"Absurdo": {"perpetuidade.crescimento_perpetuo": 0.50}}
    )
    assert np.isnan(tabela.loc["equity_value", "Absurdo"])
    assert "erro" in tabela.index


def _distribuicoes() -> list[Distribuicao]:
    return [
        Distribuicao(
            caminho="perpetuidade.crescimento_perpetuo",
            tipo="triangular",
            parametros={"minimo": 0.03, "moda": 0.045, "maximo": 0.055},
        ),
        Distribuicao(
            caminho="operacionais.margem_ebitda",
            tipo="normal",
            parametros={"media": 0.20, "desvio": 0.02},
            limite_inferior=0.10,
        ),
    ]


def test_monte_carlo_e_reproduzivel(empresa_exemplo):
    """Mesma semente, mesmo resultado: um valuation precisa ser reproduzivel."""
    a = monte_carlo(empresa_exemplo, _distribuicoes(), simulacoes=300, semente=7)
    b = monte_carlo(empresa_exemplo, _distribuicoes(), simulacoes=300, semente=7)
    assert a.valores == pytest.approx(b.valores)


def test_sementes_diferentes_dao_resultados_diferentes(empresa_exemplo):
    a = monte_carlo(empresa_exemplo, _distribuicoes(), simulacoes=300, semente=1)
    b = monte_carlo(empresa_exemplo, _distribuicoes(), simulacoes=300, semente=2)
    assert not np.allclose(a.valores, b.valores)


def test_percentis_sao_crescentes(empresa_exemplo):
    resultado = monte_carlo(empresa_exemplo, _distribuicoes(), simulacoes=500)
    percentis = resultado.percentis().to_numpy()
    assert (np.diff(percentis) >= 0).all()


def test_probabilidade_acima(empresa_exemplo):
    resultado = monte_carlo(empresa_exemplo, _distribuicoes(), simulacoes=500)
    mediana = float(np.median(resultado.valores))
    assert resultado.probabilidade_acima(mediana) == pytest.approx(0.5, abs=0.05)
    assert resultado.probabilidade_acima(float(resultado.valores.max()) + 1) == 0.0


def test_limites_truncam_as_amostras(empresa_exemplo):
    distribuicao = Distribuicao(
        caminho="operacionais.margem_ebitda",
        tipo="normal",
        parametros={"media": 0.20, "desvio": 0.10},
        limite_inferior=0.15,
        limite_superior=0.25,
    )
    resultado = monte_carlo(empresa_exemplo, [distribuicao], simulacoes=400)
    amostras = resultado.amostras["operacionais.margem_ebitda"]
    assert amostras.min() >= 0.15
    assert amostras.max() <= 0.25


def test_rodadas_inviaveis_sao_descartadas_e_contadas(empresa_exemplo):
    """Sorteios com g acima do WACC saem da distribuicao, mas ficam registrados."""
    distribuicao = Distribuicao(
        caminho="perpetuidade.crescimento_perpetuo",
        tipo="uniforme",
        parametros={"minimo": 0.02, "maximo": 0.30},
    )
    resultado = monte_carlo(empresa_exemplo, [distribuicao], simulacoes=400)
    assert resultado.descartadas > 0
    assert resultado.valores.size == 400 - resultado.descartadas
    assert np.isfinite(resultado.valores).all()


def test_todas_as_rodadas_inviaveis_e_um_erro(empresa_exemplo):
    distribuicao = Distribuicao(
        caminho="perpetuidade.crescimento_perpetuo",
        tipo="uniforme",
        parametros={"minimo": 0.50, "maximo": 0.60},
    )
    with pytest.raises(ValueError, match="Nenhuma simulacao viavel"):
        monte_carlo(empresa_exemplo, [distribuicao], simulacoes=50)


def test_lognormal_gera_apenas_valores_positivos():
    distribuicao = Distribuicao(
        caminho="qualquer", tipo="lognormal", parametros={"media": 0.2, "desvio": 0.05}
    )
    amostras = distribuicao.amostrar(np.random.default_rng(0), 1000)
    assert (amostras > 0).all()
    assert amostras.mean() == pytest.approx(0.2, abs=0.01)


def test_tipo_de_distribuicao_desconhecido(empresa_exemplo):
    distribuicao = Distribuicao(caminho="x", tipo="poisson", parametros={})
    with pytest.raises(ValueError, match="desconhecido"):
        distribuicao.amostrar(np.random.default_rng(0), 10)


def test_sem_distribuicoes_e_erro(empresa_exemplo):
    with pytest.raises(ValueError, match="ao menos uma distribuicao"):
        monte_carlo(empresa_exemplo, [], simulacoes=10)


def test_caminho_errado_nao_vira_tabela_de_nan(empresa_exemplo):
    """Typo em nome de premissa e erro de configuracao, nao celula vazia."""
    with pytest.raises(ValueError, match="nao tem o campo"):
        tabela_sensibilidade(
            empresa_exemplo,
            ("wacc", [0.11]),
            ("perpetuidade.cresimento_perpetuo", [0.04]),
        )


def test_caminho_errado_em_cenario_tambem_falha(empresa_exemplo):
    with pytest.raises(ValueError, match="nao tem o campo"):
        cenarios(empresa_exemplo, {"Erro": {"operacionais.margem_ebita": 0.2}})


def test_metrica_desconhecida(empresa_exemplo):
    with pytest.raises(ValueError, match="metrica"):
        tabela_sensibilidade(
            empresa_exemplo,
            ("wacc", [0.11]),
            ("perpetuidade.crescimento_perpetuo", [0.04]),
            metrica="lucro",
        )


# ---------------------------------------------------------------------------
# O pacote padrao: um calculo so, dois consumidores
# ---------------------------------------------------------------------------


def test_o_pacote_reproduz_o_caso_base_no_centro_da_grade(empresa_exemplo):
    """O centro da tabela **e** o numero principal.

    Se a celula do meio nao reproduz o valor da tela, a tabela inteira perde o
    sentido -- e a divergencia so apareceria na conferencia de quem recebe.
    """
    from valuation import avaliar, pacote_padrao

    resultado = avaliar(empresa_exemplo)
    pacote = pacote_padrao(empresa_exemplo, resultado)

    assert pacote.base == pytest.approx(resultado.equity_value)
    centro = pacote.wacc_x_g.iloc[len(pacote.wacc_x_g) // 2, len(pacote.wacc_x_g.columns) // 2]
    assert centro == pytest.approx(resultado.equity_value, rel=1e-9)
    base_cenario = pacote.cenarios.loc["equity_value", "Base"]
    assert base_cenario == pytest.approx(resultado.equity_value, rel=1e-9)


def test_o_pacote_carrega_as_convencoes_do_caso_base(empresa_exemplo):
    """Meio de ano muda o valor: sem a convencao, o "base" nao seria o base."""
    from valuation import avaliar, pacote_padrao

    resultado = avaliar(empresa_exemplo, meio_de_ano=True)
    pacote = pacote_padrao(empresa_exemplo, resultado, meio_de_ano=True)

    assert pacote.base == pytest.approx(resultado.equity_value)
    assert pacote.cenarios.loc["equity_value", "Base"] == pytest.approx(
        resultado.equity_value, rel=1e-9
    )


def test_wacc_maior_derruba_o_valor_na_grade(empresa_exemplo):
    from valuation import avaliar, pacote_padrao

    pacote = pacote_padrao(empresa_exemplo, avaliar(empresa_exemplo))
    coluna = pacote.wacc_x_g.iloc[:, 0]
    assert coluna.is_monotonic_decreasing, coluna.to_dict()


def test_o_tornado_ordena_pela_amplitude_e_diz_o_deslocamento(empresa_exemplo):
    """O tornado compara premissas entre si, e so vale com o mesmo deslocamento."""
    from valuation import avaliar, pacote_padrao

    pacote = pacote_padrao(empresa_exemplo, avaliar(empresa_exemplo))
    tornado = pacote.tornado

    assert list(tornado["Amplitude"]) == sorted(tornado["Amplitude"], reverse=True)
    assert "WACC" in tornado.index
    assert "-1 p.p." in tornado.columns and "+1 p.p." in tornado.columns
    # WACC acima derruba o valor; a coluna "+1 p.p." fica abaixo da "-1 p.p.".
    assert tornado.loc["WACC", "+1 p.p."] < tornado.loc["WACC", "-1 p.p."]


def test_perpetuidade_por_multiplo_nao_ganha_tabela_de_g(empresa_exemplo):
    """Com multiplo de saida o crescimento perpetuo nao entra na conta.

    Uma tabela com o eixo inerte mostraria a mesma coluna repetida com cara de
    analise -- pior que ausencia, porque parece medida.
    """
    from dataclasses import replace

    from valuation import avaliar, pacote_padrao

    empresa = replace(
        empresa_exemplo,
        perpetuidade=replace(
            empresa_exemplo.perpetuidade, metodo="multiplo", multiplo_saida=8.0
        ),
    )
    pacote = pacote_padrao(empresa, avaliar(empresa))

    assert pacote.wacc_x_g is None
    assert pacote.margem_x_crescimento is not None


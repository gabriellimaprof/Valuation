"""ITR trimestral e o ano movel que sai dele.

O fixture e um recorte em bytes do ``itr_cia_aberta_2025.zip`` publicado, com
tres companhias escolhidas por comportamento: WEG fecha o exercicio em dezembro,
Sao Martinho em marco, e Raia Drogasil e varejo com arrendamento pesado.

A armadilha propria do ITR, confirmada no arquivo antes de existir codigo: para
``DT_REFER`` de 30/09 a DRE traz **duas** linhas da mesma conta -- o acumulado do
exercicio e o trimestre isolado. Somar as duas infla em um terco; pegar a errada
muda o numero pela metade. E no primeiro trimestre ha uma linha so, entao "pegar
a ultima" acerta em marco e erra em setembro.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from valuation.importacao.cvm import (
    ErroCVM,
    _linhas_do_itr,
    importar_cvm,
    importar_ltm,
    periodo_acumulado,
    trimestres_disponiveis,
)

DADOS = Path(__file__).parent / "dados" / "cvm"
ITR = DADOS / "itr_cia_aberta_2025.zip"
WEG, SAO_MARTINHO, RAIA = 5410, 20516, 5258


# ---------------------------------------------------------------------------
# O contrato do arquivo
# ---------------------------------------------------------------------------


def test_o_itr_traz_um_registro_por_trimestre_entregue():
    assert trimestres_disponiveis(ITR, 2025, WEG) == [
        "2025-03-31",
        "2025-06-30",
        "2025-09-30",
    ]


def test_o_acumulado_e_a_linha_de_periodo_mais_longo():
    """A regra que funciona em qualquer trimestre, e nao so no primeiro."""
    linhas = _linhas_do_itr(ITR, 2025, "dre", WEG, [], "con", "2025-09-30", "ultimo")
    receita = [linha for linha in linhas if linha.codigo == "3.01"]

    assert len(receita) == 1, "sobrou o trimestre isolado junto do acumulado"
    # Acumulado de janeiro a setembro de 2025, direto do arquivo.
    assert receita[0].valor == pytest.approx(30_557_320_000.0)


def test_no_primeiro_trimestre_acumulado_e_trimestre_coincidem():
    linhas = _linhas_do_itr(ITR, 2025, "dre", WEG, [], "con", "2025-03-31", "ultimo")
    receita = [linha for linha in linhas if linha.codigo == "3.01"]
    assert len(receita) == 1
    assert receita[0].valor == pytest.approx(10_078_571_000.0)


def test_o_penultimo_do_itr_e_dado_util_e_nao_lixo():
    """No DFP o PENULTIMO duplica anos; aqui e a metade que falta do ano movel."""
    linhas = _linhas_do_itr(ITR, 2025, "dre", WEG, [], "con", "2025-09-30", "penultimo")
    receita = [linha for linha in linhas if linha.codigo == "3.01"]
    assert receita[0].valor == pytest.approx(27_164_665_000.0)


def test_o_periodo_acumulado_segue_o_exercicio_social():
    """Sao Martinho fecha em marco: o acumulado comeca em abril, nao em janeiro."""
    assert periodo_acumulado(ITR, 2025, WEG, "con", "2025-09-30") == (
        "2025-01-01",
        "2025-09-30",
    )
    assert periodo_acumulado(ITR, 2025, SAO_MARTINHO, "con", "2025-12-31") == (
        "2025-04-01",
        "2025-12-31",
    )


def test_o_balanco_do_itr_e_saldo_e_nao_periodo():
    linhas = _linhas_do_itr(ITR, 2025, "bp", WEG, [], "con", "2025-09-30", "ultimo")
    ativo = [linha for linha in linhas if linha.codigo == "1"]
    assert len(ativo) == 1
    assert ativo[0].valor == pytest.approx(41_494_475_000.0)


# ---------------------------------------------------------------------------
# O ano movel
# ---------------------------------------------------------------------------


def test_o_ano_movel_fecha_a_conta_de_ponta_a_ponta():
    """LTM = exercicio fechado + acumulado - mesmo periodo do ano anterior."""
    ltm = importar_ltm(WEG, cache=DADOS, ano=2025)
    anual = importar_cvm(WEG, [2024], cache=DADOS)

    esperado = (
        anual.valor("receita_liquida", 2024) + 30_557_320_000.0 - 27_164_665_000.0
    )
    assert ltm.valor("receita_liquida") == pytest.approx(esperado)
    assert ltm.fonte["ano_base"] == 2024
    assert ltm.fonte["ltm"] == "2025-09-30"


def test_o_balanco_do_ano_movel_e_o_saldo_do_trimestre():
    """Somar balanco pela formula do LTM daria um patrimonio que nao existe."""
    ltm = importar_ltm(WEG, cache=DADOS, ano=2025)
    assert ltm.valor("ativo_total") == pytest.approx(41_494_475_000.0)
    # E continua fechando a identidade contabil.
    assert ltm.valor("ativo_total") == pytest.approx(ltm.valor("passivo_total"))


def test_exercicio_social_quebrado_escolhe_a_base_certa():
    """Sao Martinho acumula de abril; a base e o exercicio encerrado em marco."""
    ltm = importar_ltm(SAO_MARTINHO, cache=DADOS, ano=2025)
    assert ltm.fonte["ano_base"] == 2025, "pegou o exercicio errado"

    anual = importar_cvm(SAO_MARTINHO, [2025], cache=DADOS)
    esperado = (
        anual.valor("receita_liquida", 2025) + 5_188_107_000.0 - 5_424_459_000.0
    )
    assert ltm.valor("receita_liquida") == pytest.approx(esperado)


def test_o_ano_movel_avisa_que_nao_e_exercicio_social():
    """Ler "2025" numa coluna de ano movel e entender ano cheio."""
    ltm = importar_ltm(WEG, cache=DADOS, ano=2025)
    aviso = " ".join(ltm.avisos)
    assert "não é um exercício social" in aviso
    assert "2025-09-30" in aviso


def test_a_origem_de_cada_conta_diz_como_ela_foi_montada():
    ltm = importar_ltm(WEG, cache=DADOS, ano=2025)
    assert "acumulado" in ltm.mapeamento["receita_liquida"]
    assert "saldo em 2025-09-30" == ltm.mapeamento["ativo_total"]


def test_companhia_sem_itr_no_ano_da_erro_claro():
    with pytest.raises(ErroCVM, match="ITR"):
        importar_ltm(999_999, cache=DADOS, ano=2025)


def test_o_ano_movel_alimenta_a_analise_historica():
    """O ponto do LTM e plugar no motor sem que nada mais mude."""
    from valuation.historico import analisar

    ltm = importar_ltm(RAIA, cache=DADOS, ano=2025).escalar(1e6, "R$ milhões")
    analise = analisar(ltm)

    assert "Margem EBITDA" in analise.indicadores.index
    margem = analise.mediana("Margem EBITDA")
    assert 0.05 < margem < 0.20, f"margem implausivel para varejo: {margem}"


def test_o_ano_movel_se_junta_a_serie_anual_sem_duplicar_coluna():
    """A tela emenda o LTM na serie; duas colunas do mesmo ano seriam um degrau falso."""
    from dataclasses import replace

    anual = importar_cvm(WEG, [2023, 2024], cache=DADOS)
    ltm = importar_ltm(WEG, cache=DADOS, ano=2025)
    rotulo = ltm.anos[-1]

    valores = anual.valores.drop(columns=[rotulo], errors="ignore").join(
        ltm.valores, how="outer"
    )
    juntas = replace(
        anual,
        valores=valores[sorted(valores.columns)],
        avisos=list(anual.avisos) + list(ltm.avisos),
    )

    assert juntas.anos == [2023, 2024, 2025]
    assert len(set(juntas.anos)) == len(juntas.anos), "coluna duplicada"
    assert juntas.valor("receita_liquida", 2025) > juntas.valor("receita_liquida", 2024)
    assert any("exercício social" in aviso for aviso in juntas.avisos)

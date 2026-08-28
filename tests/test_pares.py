"""Peer group por perfil economico.

O modulo existe porque o peer group anterior vinha do ``SETOR_ATIV`` da CVM,
que e classificacao de registro: emparelha a WEG com a Plascar. Os testes daqui
cuidam das tres coisas que fariam a substituicao ser pior que o problema.

**A escala.** Com media e desvio, uma companhia de margem de 300% define a
escala e todo o resto colapsa perto de zero -- o ranking vira ruido. Por isso
mediana e amplitude interquartil, e ha teste que quebra se alguem "simplificar".

**Os dados faltantes.** Companhia que so publica quatro dimensoes nao pode
parecer mais proxima de todo mundo do que uma que publica seis.

**A explicacao.** Um ranking sem o porque pede fe. A tabela dimensao a dimensao
e o que permite discordar com argumento.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from valuation.pares import (
    DIMENSOES,
    Universo,
    UniversoVazio,
    carregar_universo,
    construir_universo,
    distancia,
    explicar,
    fora_de_porte,
    pares_proximos,
    perfil_de,
    salvar_universo,
)

DADOS = Path(__file__).parent / "dados" / "cvm"


@pytest.fixture
def universo() -> Universo:
    """Seis companhias inventadas, com perfis deliberadamente distintos."""
    perfis = pd.DataFrame(
        {
            "Margem EBITDA": [0.20, 0.21, 0.45, 0.06, 0.19, 3.00],
            "ROIC": [0.15, 0.16, 0.09, 0.11, 0.14, 0.02],
            "Giro do capital investido": [1.2, 1.1, 0.4, 2.6, 1.3, 0.1],
            "Capex / Receita": [0.05, 0.06, 0.22, 0.02, 0.05, 0.30],
            "Crescimento da receita": [0.10, 0.09, 0.04, 0.12, 0.11, 0.01],
            "Divida liquida / EBITDA": [1.0, 1.2, 3.4, 0.5, 0.9, 12.0],
            "nome": ["Alfa", "Beta", "Pedágio", "Varejo", "Gama", "Estranha"],
            "receita": [1000.0, 1100.0, 800.0, 5000.0, 950.0, 30.0],
            "setor": ["Indústria"] * 6,
        },
        index=[1, 2, 3, 4, 5, 6],
    )
    perfis.index.name = "codigo"
    return Universo(perfis=perfis, anos=[2023, 2024])


# ---------------------------------------------------------------------------
# A distancia
# ---------------------------------------------------------------------------


def test_perfil_igual_da_distancia_zero(universo):
    perfil = universo.perfis.loc[1, universo.dimensoes].to_dict()
    d, quantas = distancia(perfil, perfil, universo.escalas())
    assert d == pytest.approx(0.0)
    assert quantas == len(universo.dimensoes)


def test_a_escala_e_robusta_a_extremos(universo):
    """A companhia de margem 300% nao pode achatar o resto do ranking.

    Com media e desvio, ela define a escala sozinha e Alfa, Beta e Gama --
    que sao de fato parecidas -- ficam todas a distancia quase zero de todo
    mundo, inclusive do pedágio.
    """
    escalas = universo.escalas()
    perfil = universo.perfis.loc[1, universo.dimensoes].to_dict()

    perto, _ = distancia(perfil, universo.perfis.loc[2, universo.dimensoes], escalas)
    longe, _ = distancia(perfil, universo.perfis.loc[3, universo.dimensoes], escalas)
    assert perto < longe / 3, "o ranking colapsou: a escala nao esta robusta"


def test_dimensao_faltante_nao_aproxima_artificialmente(universo):
    """Menos dados nao pode virar mais semelhanca."""
    escalas = universo.escalas()
    completo = universo.perfis.loc[3, universo.dimensoes].to_dict()

    alvo = universo.perfis.loc[1, universo.dimensoes].to_dict()
    parcial = {k: v for k, v in completo.items() if k in list(completo)[:3]}

    d_completo, n_completo = distancia(alvo, completo, escalas)
    d_parcial, n_parcial = distancia(alvo, parcial, escalas)
    assert n_completo == 6 and n_parcial == 3
    # Nao ha regra de sinal aqui, mas as duas tem que estar na mesma ordem de
    # grandeza: a normalizacao pelo numero de dimensoes e o que garante isso.
    assert 0.4 < d_parcial / d_completo < 2.5


def test_sem_dimensao_em_comum_a_distancia_e_ausente(universo):
    d, quantas = distancia({"Margem EBITDA": 0.2}, {"ROIC": 0.15}, universo.escalas())
    assert np.isnan(d)
    assert quantas == 0


def test_poucas_dimensoes_em_comum_saem_do_ranking(universo):
    """Companhia sem margem e sem alavancagem nao e comparavel, e o ranking sabia.

    Sem o minimo, ela aparecia no topo por falta de dado -- e quem le nao tinha
    como perceber, porque a tabela nao dizia quantas dimensoes sustentavam a
    distancia.
    """
    perfis = universo.perfis.copy()
    perfis.loc[3, ["Margem EBITDA", "Divida liquida / EBITDA", "Capex / Receita"]] = np.nan
    incompleto = Universo(perfis=perfis, anos=universo.anos)

    perfil = universo.perfis.loc[1, universo.dimensoes].to_dict()
    tabela = pares_proximos(perfil, incompleto, excluir=1, faixa_de_porte=None)

    assert "Pedágio" not in tabela.index
    assert (tabela["Dimensões"] >= 4).all()

    frouxo = pares_proximos(
        perfil, incompleto, excluir=1, faixa_de_porte=None, minimo_de_dimensoes=1
    )
    assert "Pedágio" in frouxo.index


# ---------------------------------------------------------------------------
# O ranking
# ---------------------------------------------------------------------------


def test_os_pares_saem_ordenados_e_o_mais_parecido_vem_primeiro(universo):
    perfil = universo.perfis.loc[1, universo.dimensoes].to_dict()
    tabela = pares_proximos(perfil, universo, excluir=1, faixa_de_porte=None)

    assert list(tabela.index)[:2] == ["Beta", "Gama"] or list(tabela.index)[:2] == [
        "Gama",
        "Beta",
    ]
    assert tabela["Distância"].is_monotonic_increasing
    assert "Alfa" not in tabela.index, "a propria companhia nao e par dela mesma"


def test_o_ranking_traz_as_dimensoes_para_conferencia(universo):
    """Sem elas, o usuario nao tem como discordar do ranking.

    So as que o universo tem: um universo construido antes de uma dimensao
    existir continua utilizavel, e a tabela mostra o que de fato foi comparado.
    """
    perfil = universo.perfis.loc[1, universo.dimensoes].to_dict()
    tabela = pares_proximos(perfil, universo, excluir=1, faixa_de_porte=None)
    for dimensao in universo.dimensoes:
        assert dimensao in tabela.columns
    assert set(universo.dimensoes) <= set(DIMENSOES)


def test_porte_muito_diferente_sai_do_ranking(universo):
    """Varejo fatura 5x e a Estranha 1/33: escala muda o negocio."""
    perfil = universo.perfis.loc[1, universo.dimensoes].to_dict()
    com_filtro = pares_proximos(perfil, universo, excluir=1, receita=1000.0, faixa_de_porte=3.0)
    assert "Varejo" not in com_filtro.index
    assert "Estranha" not in com_filtro.index

    sem_filtro = pares_proximos(perfil, universo, excluir=1, faixa_de_porte=None)
    assert "Varejo" in sem_filtro.index


@pytest.mark.parametrize(
    "alvo,par,esperado",
    [(1000.0, 1000.0, False), (1000.0, 5000.0, False), (1000.0, 20000.0, True),
     (1000.0, 50.0, True), (1000.0, float("nan"), False), (0.0, 100.0, False)],
)
def test_fora_de_porte(alvo, par, esperado):
    assert fora_de_porte(alvo, par) is esperado


def test_universo_pequeno_demais_e_erro_claro():
    perfis = pd.DataFrame({"Margem EBITDA": [0.2], "nome": ["Sozinha"]}, index=[1])
    with pytest.raises(UniversoVazio, match="menos de duas"):
        pares_proximos({"Margem EBITDA": 0.2}, Universo(perfis=perfis))


# ---------------------------------------------------------------------------
# A explicacao
# ---------------------------------------------------------------------------


def test_a_explicacao_mostra_onde_o_par_se_afasta(universo):
    perfil = universo.perfis.loc[1, universo.dimensoes].to_dict()
    tabela = explicar(perfil, universo.perfis.loc[3], universo)

    assert list(tabela.index) == list(universo.dimensoes)
    assert {"Alvo", "Par", "Afastamento (em amplitudes)"} <= set(tabela.columns)
    # O pedagio se afasta mais em giro do capital do que em crescimento.
    assert (
        tabela.loc["Giro do capital investido", "Afastamento (em amplitudes)"]
        > tabela.loc["Crescimento da receita", "Afastamento (em amplitudes)"]
    )


# ---------------------------------------------------------------------------
# Construir contra a base real
# ---------------------------------------------------------------------------


def test_construir_universo_a_partir_dos_arquivos_da_cvm():
    """Quatro companhias no fixture; o Banco do Brasil tem que ficar de fora."""
    universo = construir_universo([2023, 2024], cache=DADOS)

    assert len(universo) >= 2
    nomes = " ".join(str(n) for n in universo.perfis["nome"])
    assert "WEG" in nomes
    assert "BANCO DO BRASIL" not in nomes.upper(), (
        "banco no universo: margem EBITDA e capex/receita nao querem dizer nada nele"
    )
    for dimensao in ("Margem EBITDA", "ROIC"):
        assert dimensao in universo.perfis.columns


def test_o_universo_sobrevive_ao_disco(tmp_path):
    universo = construir_universo([2023, 2024], cache=DADOS)
    destino = salvar_universo(universo, tmp_path / "perfis.csv")
    voltou = carregar_universo([2023, 2024], caminho=destino)

    assert len(voltou) == len(universo)
    assert voltou.dimensoes == universo.dimensoes
    pd.testing.assert_series_equal(
        voltou.perfis["Margem EBITDA"].astype(float),
        universo.perfis["Margem EBITDA"].astype(float),
        check_names=False,
    )


def test_indicadores_extra_viajam_sem_entrar_na_distancia():
    universo = construir_universo(
        [2023, 2024], cache=DADOS, indicadores_extra=("Margem liquida",)
    )
    assert "Margem liquida" in universo.perfis.columns
    assert "Margem liquida" not in universo.dimensoes


def test_perfil_de_usa_mediana_e_nao_ultimo_ano():
    """Comparavel escolhido pelo ano de uma greve e comparavel escolhido a esmo."""
    from valuation.historico import analisar
    from valuation.importacao import Demonstracoes

    valores = pd.DataFrame(
        {
            2022: {"receita_liquida": 1000.0, "ebit": 200.0, "depreciacao_amortizacao": 50.0},
            2023: {"receita_liquida": 1000.0, "ebit": 200.0, "depreciacao_amortizacao": 50.0},
            2024: {"receita_liquida": 1000.0, "ebit": 10.0, "depreciacao_amortizacao": 50.0},
        }
    )
    perfil = perfil_de(analisar(Demonstracoes(empresa="X", valores=valores)))
    assert perfil["Margem EBITDA"] == pytest.approx(0.25)


# ---------------------------------------------------------------------------
# A safra do universo de comparaveis
# ---------------------------------------------------------------------------


def test_o_universo_avisa_quando_fica_para_tras():
    """Ele é construído uma vez e lido muitas, e não se atualiza sozinho.

    Quando sai DFP nova o app passa a comparar a companhia contra uma base de
    dois anos atrás **com a mesma aparência de atual** — e as referências saem
    dele, então a safra velha contamina os percentis que a tela cita.
    """
    from pathlib import Path

    from valuation.pares import SafraDoUniverso

    atrasado = SafraDoUniverso(
        anos=[2020, 2021, 2022, 2023, 2024],
        construido_em="2026-08-19",
        ano_mais_novo_disponivel=2025,
        caminho=Path("perfis.csv"),
    )
    assert atrasado.desatualizado
    assert atrasado.exercicios_atras == 1
    assert "1 exercício atrás" in atrasado.resumo()
    assert "python -m valuation.pares" in atrasado.resumo()


def test_universo_na_safra_mais_nova_nao_alarma():
    from pathlib import Path

    from valuation.pares import SafraDoUniverso

    em_dia = SafraDoUniverso(
        anos=[2021, 2022, 2023, 2024, 2025],
        construido_em="2026-08-22",
        ano_mais_novo_disponivel=2025,
        caminho=Path("perfis.csv"),
    )
    assert not em_dia.desatualizado
    assert "safra mais nova" in em_dia.resumo()


def test_sem_dfp_no_cache_o_universo_nao_e_julgado():
    """Sem base local não há como afirmar que ele envelheceu."""
    from pathlib import Path

    from valuation.pares import SafraDoUniverso

    sem_referencia = SafraDoUniverso(
        anos=[2020, 2024],
        construido_em="2026-08-19",
        ano_mais_novo_disponivel=None,
        caminho=Path("perfis.csv"),
    )
    assert not sem_referencia.desatualizado


def test_a_base_de_referencia_nao_pede_indicador_que_o_universo_nao_mede():
    """Regerar as referências não pode encolher `BASE` calado.

    `gerar_referencias` só emite o indicador que existe no universo. Se `BASE`
    publica um que `INDICADORES_EXTRA` não coleta, refazer a medição o **apaga**
    sem avisar — foi o que quase aconteceu com `Arrendamento / Divida bruta`,
    que estava publicado e não era coletado.

    O invariante: tudo que `BASE` publica sai do universo, ou é dimensão de
    comparação (que o perfil já traz).
    """
    from valuation.pares import DIMENSOES, INDICADORES_EXTRA
    from valuation.referencias import BASE

    medidos = set(DIMENSOES) | set(INDICADORES_EXTRA)
    faltando = sorted(nome for nome in BASE if nome not in medidos)
    assert not faltando, (
        "estes indicadores são publicados em referencias.BASE e o universo não "
        f"os coleta, então refazer a medição os perderia: {faltando}"
    )

"""Testes das partes puras do app.

As telas do Streamlit sao verificadas rodando o app de verdade no navegador; o
que da para testar aqui e o que nao depende do runtime: formatacao brasileira,
construcao dos graficos e a paleta -- que precisa continuar passando nas
verificacoes de acessibilidade mesmo depois de alguem "so ajustar uma cor".
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.componentes import _markdown_para_html, formatar, tabela_formatada
from app.graficos import (
    barras_ciclo,
    barras_de_faixa,
    barras_temporais,
    cascata_ponte,
    composicao_do_valor,
    distribuicao_simulada,
    fluxos_projetados,
    linhas_percentuais,
    mapa_de_calor,
    pequenos_multiplos,
    roic_versus_wacc,
)
from app.tema import CLARO, ESCURO
from app.textos import CONCEITOS, PASSOS

# ---------------------------------------------------------------------------
# Formatacao
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "valor,formato,esperado",
    [
        (1234.5, "moeda", "1.234,5"),
        (1_234_567.8, "moeda", "1.234.567,8"),
        (0.1234, "pct", "12,3%"),
        (0.1234, "pct2", "12,34%"),
        (8.5, "multiplo", "8,50x"),
        (1234.5, "numero", "1.234,50"),
        (45.2, "dias", "45 dias"),
        (None, "moeda", "—"),
        (float("nan"), "pct", "—"),
        (float("inf"), "moeda", "—"),
    ],
)
def test_formatacao_brasileira(valor, formato, esperado):
    assert formatar(valor, formato) == esperado


def test_formatacao_com_unidade():
    assert formatar(1500.0, "moeda", "R$ milhões") == "1.500,0 R$ milhões"


def test_tabela_formatada_preserva_estrutura():
    dados = pd.DataFrame({2023: [1000.0, 2000.0], 2024: [1100.0, 2200.0]})
    formatada = tabela_formatada(dados, "moeda")
    assert formatada.shape == dados.shape
    assert formatada.iloc[0, 0] == "1.000,0"


# ---------------------------------------------------------------------------
# Conversao de markdown nos blocos explicativos
# ---------------------------------------------------------------------------


def test_markdown_vira_html():
    assert _markdown_para_html("**WACC**") == "<strong>WACC</strong>"
    assert _markdown_para_html("*ênfase*") == "<em>ênfase</em>"
    assert _markdown_para_html("`codigo`") == "<code>codigo</code>"


def test_negrito_nao_e_confundido_com_italico():
    """O asterisco duplo precisa ser consumido antes do simples."""
    assert "<em>" not in _markdown_para_html("**negrito**")


def test_nenhum_conceito_deixa_asterisco_solto():
    """Se sobrar asterisco, ele aparece literal na tela do usuario."""
    for chave, texto in CONCEITOS.items():
        convertido = _markdown_para_html(texto)
        assert "**" not in convertido, chave


def test_conceitos_explicam_e_nao_so_definem():
    """Todo conceito deve dizer por que importa, e não apenas o que é."""
    for chave, texto in CONCEITOS.items():
        assert len(texto) > 150, chave


def test_passos_cobrem_o_fluxo():
    """O roteiro da tela inicial precisa acompanhar as telas que existem."""
    from app.main import main  # noqa: F401 - garante que o modulo importa

    nomes = [nome for nome, _, _ in PASSOS]
    assert "Retorno esperado" in nomes
    assert len(PASSOS) == 10
    for nome, resumo, detalhe in PASSOS:
        assert nome and resumo and detalhe


# ---------------------------------------------------------------------------
# Paleta
# ---------------------------------------------------------------------------


def test_paleta_tem_oito_tons_categoricos():
    assert len(CLARO.series) == 8
    assert len(ESCURO.series) == 8


def test_indice_de_serie_satura_em_vez_de_reciclar():
    """Reciclar cores faria duas series distintas dividirem o mesmo tom."""
    assert CLARO.serie(0) == CLARO.series[0]
    assert CLARO.serie(7) == CLARO.series[7]
    assert CLARO.serie(99) == CLARO.series[-1]


def test_modos_claro_e_escuro_tem_superficies_distintas():
    assert CLARO.superficie != ESCURO.superficie
    assert CLARO.texto_primario != ESCURO.texto_primario


def test_cores_sao_hex_validos():
    for paleta in (CLARO, ESCURO):
        for cor in paleta.series + paleta.sequencial:
            assert cor.startswith("#") and len(cor) == 7


def test_rampa_sequencial_e_de_um_tom_so():
    """Arco-iris em escala sequencial engana sobre a ordem dos valores."""
    for paleta in (CLARO, ESCURO):
        assert len(paleta.sequencial) >= 6
        # Um unico tom significa componente azul dominante em toda a rampa.
        for cor in paleta.sequencial:
            vermelho = int(cor[1:3], 16)
            azul = int(cor[5:7], 16)
            assert azul > vermelho


# ---------------------------------------------------------------------------
# Graficos
# ---------------------------------------------------------------------------


@pytest.fixture
def serie_anual() -> pd.DataFrame:
    return pd.DataFrame(
        {2022: [0.20, 0.15], 2023: [0.22, 0.16], 2024: [0.24, 0.17]},
        index=["Margem EBITDA", "Margem EBIT"],
    )


def test_linhas_percentuais(serie_anual):
    figura = linhas_percentuais(serie_anual, "Margens")
    assert len(figura.data) == 2
    assert figura.layout.yaxis.tickformat == ".0%"
    assert figura.layout.showlegend is True


def test_serie_unica_dispensa_legenda(serie_anual):
    """Com uma serie so, o titulo ja identifica; a caixa de legenda vira ruido."""
    figura = linhas_percentuais(serie_anual.iloc[[0]], "Margem")
    assert figura.layout.showlegend is False


def test_barras_temporais(serie_anual):
    figura = barras_temporais(serie_anual, "Valores", "R$ mi")
    assert len(figura.data) == 2
    assert figura.layout.barmode == "group"


def test_cores_seguem_a_ordem_fixa(serie_anual):
    """A mesma serie precisa ter a mesma cor em todos os graficos."""
    linhas = linhas_percentuais(serie_anual)
    barras = barras_temporais(serie_anual)
    assert linhas.data[0].line.color == barras.data[0].marker.color
    assert linhas.data[1].line.color == barras.data[1].marker.color


def test_roic_versus_wacc_tem_as_duas_series():
    roic = pd.Series([0.14, 0.16, 0.15], index=[2022, 2023, 2024])
    figura = roic_versus_wacc(roic, 0.12)
    assert len(figura.data) == 2
    assert figura.layout.yaxis.tickformat == ".0%"


def test_cascata_marca_totais_nas_pontas():
    itens = [("Enterprise Value", 1000.0), ("(−) Dívida", -300.0), ("Equity Value", 700.0)]
    figura = cascata_ponte(itens, "R$ mi")
    assert list(figura.data[0].measure) == ["absolute", "relative", "total"]


def test_composicao_do_valor_soma_as_duas_partes():
    figura = composicao_do_valor(400.0, 600.0, "R$ mi")
    assert figura.layout.barmode == "stack"
    assert sum(float(t.x[0]) for t in figura.data) == pytest.approx(1000.0)


def test_fluxos_projetados_tem_nominal_e_descontado():
    figura = fluxos_projetados(
        [1, 2, 3], np.array([100.0, 110.0, 120.0]), np.array([90.0, 89.0, 88.0]), "R$ mi"
    )
    assert len(figura.data) == 2


def test_mapa_de_calor_usa_eixo_categorico():
    """Sem eixo categorico o Plotly reinterpreta "11,50%" como numero."""
    tabela = pd.DataFrame(
        [[100.0, 110.0], [120.0, 130.0]],
        index=pd.Index(["10,00%", "11,00%"], name="wacc"),
        columns=pd.Index(["3,00%", "4,00%"], name="g"),
    )
    figura = mapa_de_calor(tabela, "Sensibilidade", "R$ mi")
    assert figura.layout.xaxis.type == "category"
    assert figura.layout.yaxis.type == "category"


def test_mapa_de_calor_escreve_o_numero_em_cada_celula():
    """Cor sozinha nao se le com a precisao que um valuation exige."""
    tabela = pd.DataFrame([[100.0, 110.0]], index=["a"], columns=["x", "y"])
    figura = mapa_de_calor(tabela)
    assert figura.data[0].text is not None


def test_distribuicao_simulada_marca_percentis():
    valores = np.random.default_rng(1).normal(1000, 100, 500)
    figura = distribuicao_simulada(
        valores, {"P5": 850.0, "P50": 1000.0, "P95": 1150.0}, 990.0, "R$ mi"
    )
    assert len(figura.layout.shapes) == 4  # P5, mediana, P95 e caso base


def test_anotacoes_do_monte_carlo_sao_escalonadas():
    """Mediana e caso base costumam coincidir; os rotulos nao podem se sobrepor."""
    valores = np.random.default_rng(1).normal(1000, 100, 200)
    figura = distribuicao_simulada(valores, {"P50": 1000.0}, 1000.5, "R$ mi")
    alturas = {a.yshift for a in figura.layout.annotations}
    assert len(alturas) > 1


def test_barras_de_faixa_ignora_valores_invalidos():
    figura = barras_de_faixa(
        ["EV/EBITDA", "P/L"], [1000.0, float("nan")], referencia=900.0
    )
    assert len(figura.data[0].y) == 1


def test_barras_de_faixa_sem_valores_validos_nao_quebra():
    figura = barras_de_faixa(["P/L"], [float("nan")])
    assert len(figura.data) == 0


def test_pequenos_multiplos_um_grafico_por_indicador():
    """Grandezas incompativeis pedem escalas proprias, nao um eixo secundario."""
    dados = pd.DataFrame(
        {2023: [0.10, 1.5, 2.0], 2024: [0.11, 1.6, 2.1]},
        index=["Margem liquida", "Giro do ativo", "Alavancagem financeira"],
    )
    figuras = pequenos_multiplos(
        dados, {"Margem liquida": ".1%", "Giro do ativo": ",.2f"}
    )
    assert len(figuras) == 3
    assert [nome for nome, _ in figuras] == list(dados.index)
    for _, figura in figuras:
        assert figura.layout.showlegend is not True


def test_barras_ciclo():
    dados = pd.Series([45.0, 60.0, 30.0], index=["Recebimento", "Estoque", "Pagamento"])
    figura = barras_ciclo(dados, "Ciclo")
    assert len(figura.data[0].y) == 3


def test_nenhum_grafico_usa_eixo_secundario(serie_anual):
    """Eixo duplo e o erro numero um em grafico financeiro."""
    figuras = [
        linhas_percentuais(serie_anual),
        barras_temporais(serie_anual),
        roic_versus_wacc(pd.Series([0.15], index=[2024]), 0.12),
        composicao_do_valor(400.0, 600.0),
    ]
    for figura in figuras:
        assert not hasattr(figura.layout, "yaxis2") or figura.layout.yaxis2.title.text is None

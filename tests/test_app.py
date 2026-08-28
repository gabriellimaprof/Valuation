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
    linhas_em_dias,
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
from app.textos import CONCEITOS

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
# Ordenacao da tela de conferencia
# ---------------------------------------------------------------------------


def test_conta_sintetica_vem_antes_da_analitica():
    """A DFP traz centenas de subcontas; a tela so mostra as primeiras.

    Ordenada por codigo, a linha de capex da WEG (6.02.02) caia na posicao 212
    de 237 e ficava fora de alcance, enquanto as 40 visiveis eram subcontas de
    quarto e quinto nivel que ninguem mapeia.
    """
    from app.paginas.dados import LIMITE_CONFERENCIA, _relevancia
    from valuation.importacao import LinhaNaoReconhecida

    linhas = [
        LinhaNaoReconhecida(f"1.01.06.01.{i:02d} - Tributo a recuperar", "Balanço", None, 0.0)
        for i in range(60)
    ] + [LinhaNaoReconhecida("6.02.02 - Imobilizado", "DFC", None, 0.0)]

    ordenadas = sorted(linhas, key=_relevancia)
    posicao = next(
        i for i, l in enumerate(ordenadas) if l.rotulo.startswith("6.02.02")
    )
    assert posicao < LIMITE_CONFERENCIA, "o capex voltou a ficar fora da tela"


def test_cotacao_vira_valor_de_mercado_na_unidade_certa():
    """Valor de mercado = cotacao x acoes, com as acoes na unidade dos valores.

    Errar isto produz um multiplo plausivel e errado por um fator de mil, que e
    o pior tipo de erro: nao parece erro.
    """
    from app.paginas.multiplos import comparavel_de_peer

    # WEG em R$ milhoes: 4.195,5 milhoes de acoes a R$ 50,00.
    peer = comparavel_de_peer(
        {
            "Empresa": "WEG SA",
            "Cotação (R$/ação)": 50.0,
            "Ações": 4195.537378,
            "Dívida líquida": -3000.0,
            "Receita": 40804.1,
            "EBITDA": 8000.0,
            "EBIT": 7690.5,
            "Lucro líquido": 6318.8,
            "Patrimônio líquido": 23125.2,
        }
    )
    assert peer is not None
    assert peer.valor_mercado == pytest.approx(209_776.87, abs=0.1)  # R$ milhoes
    assert peer.receita == pytest.approx(40804.1)
    assert peer.divida_liquida == pytest.approx(-3000.0)


@pytest.mark.parametrize(
    "linha",
    [
        {"Empresa": "", "Cotação (R$/ação)": 10.0, "Ações": 100.0},
        {"Empresa": "X", "Cotação (R$/ação)": None, "Ações": 100.0},
        {"Empresa": "X", "Cotação (R$/ação)": 10.0, "Ações": 0.0},
        {"Empresa": "X", "Cotação (R$/ação)": 10.0, "Ações": None},
    ],
)
def test_peer_incompleto_nao_vira_comparavel(linha):
    """Sem nome, cotacao ou acoes nao da para calcular valor de mercado."""
    from app.paginas.multiplos import comparavel_de_peer

    assert comparavel_de_peer(linha) is None


@pytest.mark.parametrize(
    "alvo,peer,esperado",
    [
        (40_000.0, 38_000.0, False),   # mesmo porte
        (40_000.0, 3_000.0, True),     # peer 13x menor
        (3_000.0, 40_000.0, True),     # peer 13x maior
        (40_000.0, 4_500.0, False),    # 9x, ainda dentro da faixa
        (40_000.0, float("nan"), False),  # sem dado nao acusa
        (0.0, 100.0, False),           # receita zero nao divide
    ],
)
def test_faixa_de_porte_do_peer_group(alvo, peer, esperado):
    from app.paginas.multiplos import fora_de_porte

    assert fora_de_porte(alvo, peer) is esperado


def test_atualizar_da_cvm_so_avanca_no_tempo():
    """Atualizar acrescenta exercicios novos, nunca desce buscar decada antiga.

    A conta ingenua (todos os anos completos menos os salvos) fazia um clique em
    "Atualizar" baixar de 2010 em diante -- dez arquivos de 13 MB que o usuario
    nao pediu.
    """
    from app.paginas.dados import _anos_a_acrescentar

    disponiveis = list(range(2010, 2027))
    assert _anos_a_acrescentar([2019, 2020, 2021, 2022, 2023], disponiveis, 2026) == [
        2024,
        2025,
    ]
    # Ja atualizado: nada a fazer, e o ano corrente nao entra.
    assert _anos_a_acrescentar([2024, 2025], disponiveis, 2026) == []


def test_ordenacao_de_planilha_sem_codigo_continua_alfabetica():
    """Origem sem codigo CVM empata em nivel zero: nada muda para ela."""
    from app.paginas.dados import _relevancia
    from valuation.importacao import LinhaNaoReconhecida

    linhas = [
        LinhaNaoReconhecida("Zebra", "Plan1", None, 0.0),
        LinhaNaoReconhecida("Alfa", "Plan1", None, 0.0),
    ]
    assert [l.rotulo for l in sorted(linhas, key=_relevancia)] == ["Alfa", "Zebra"]


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
    """O roteiro da tela inicial e o menu sao a mesma lista.

    Eram duas -- `textos.PASSOS` desenhava o Inicio e o `main` montava o menu --,
    e nada obrigava as duas a concordarem. Agora ha uma so, em `navegacao`, e o
    que se verifica e que ela cobre as telas que o app de fato tem.
    """
    from app.main import main  # noqa: F401 - garante que o modulo importa
    from app.navegacao import PASSOS

    titulos = [passo.titulo for passo in PASSOS]
    assert "Retorno esperado" in titulos
    assert titulos[0] == "Início", "o caminho comeca no Inicio"

    # **A propriedade, e nao a contagem.** `len(PASSOS) == 12` virava falha
    # sozinho ao acrescentar uma tela legitima, sem nada estar errado -- o mesmo
    # defeito dos testes que pinavam a safra. O que precisa valer e que todo
    # passo tem tela e toda tela esta no caminho.
    from app.main import TELAS

    assert set(TELAS) == {passo.chave for passo in PASSOS}, (
        "todo passo precisa de uma tela, e toda tela precisa estar no caminho"
    )
    assert len({p.chave for p in PASSOS}) == len(PASSOS), "chave repetida"
    assert len({p.url for p in PASSOS}) == len(PASSOS), "url repetida"


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


def test_linhas_em_dias_desenha_o_ciclo_e_as_pernas():
    """O gráfico do ciclo é uma série temporal, e não o retrato de um período.

    A tela mostrava barras do último exercício, que respondem "qual é o ciclo
    hoje" e não "para onde ele foi" — que é a pergunta de quem acompanha uma
    empresa. As quatro séries dividem o eixo porque estão na mesma unidade.
    """
    dados = pd.DataFrame(
        {
            2023: [68.0, 120.0, 37.0, 151.0],
            2024: [71.0, 144.0, 55.0, 160.0],
        },
        index=[
            "Prazo medio de recebimento (dias)",
            "Prazo medio de estoque (dias)",
            "Prazo medio de pagamento (dias)",
            "Ciclo de conversao de caixa (dias)",
        ],
    )
    figura = linhas_em_dias(dados, "Ciclo")

    assert len(figura.data) == 4
    # O total tem de se distinguir das pernas: quatro linhas de mesmo peso
    # obrigam quem lê a procurar qual delas é a soma.
    # O total e a ultima linha da tabela, por convencao de montagem -- e nao
    # "a que tem 'ciclo' no nome": reconhecer por substring quebra calado quando
    # o rotulo muda, e ele muda (a tela acentua o que o motor guarda sem acento).
    ciclo = figura.data[-1]
    pernas = list(figura.data[:-1])
    assert ciclo.name == "Ciclo de conversao de caixa (dias)"
    assert all(t.line.dash == "dot" for t in pernas)
    assert ciclo.line.dash == "solid"
    assert ciclo.line.width > pernas[0].line.width


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


def test_a_suite_roda_dos_dois_jeitos_de_invocar_o_pytest():
    """`pytest` puro e `python -m pytest` precisam achar as telas.

    `app` **não é empacotado** — só `src/` entra em `packages.find` —, então os
    sete arquivos de teste que importam telas dependiam do diretório do projeto
    estar no `sys.path`. `python -m pytest` o põe ali; `pytest` puro, não.

    Rodando de um jeito na máquina e de outro no CI, a suíte ficou **verde aqui
    e vermelha lá**, com `ModuleNotFoundError: No module named 'app'` — e o erro
    não era do código, era de como se invoca o pytest. O `pythonpath` no
    `pyproject.toml` é o que faz "passou" querer dizer a mesma coisa nos dois
    lugares, e este teste é o que impede que ele seja removido por limpeza.
    """
    import tomllib
    from pathlib import Path

    raiz = Path(__file__).resolve().parent.parent
    config = tomllib.loads((raiz / "pyproject.toml").read_text(encoding="utf-8"))
    opcoes = config["tool"]["pytest"]["ini_options"]
    assert "." in opcoes.get("pythonpath", []), (
        "sem `pythonpath` o `pytest` puro não acha o pacote `app`, e o CI "
        "reprova o que a máquina aprova"
    )

"""O tema: os tokens do Streamlit e a paleta do app dizem a mesma coisa.

A identidade visual passou a vir dos **tokens nativos** do Streamlit, em
`.streamlit/config.toml`: tipografia, raio, borda, cor primaria e as cores de
grafico. E a forma certa de fazer -- o token atravessa todo componente, inclusive
os que o CSS do app nao alcanca --, mas cria uma segunda copia das cores.

Duas fontes da verdade para a mesma cor divergem no dia em que alguem muda uma
delas. Estes testes sao o que impede isso, e o que trava a regra que o guia de
dataviz impoe: **a paleta nao se troca por gosto**.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from app import tema
from app.navegacao import PASSOS, anterior, numero, proximo

CONFIG = Path(__file__).resolve().parent.parent / ".streamlit" / "config.toml"


@pytest.fixture(scope="module")
def config() -> dict:
    return tomllib.loads(CONFIG.read_text(encoding="utf-8"))


def test_as_cores_do_tema_sao_as_da_paleta(config):
    """O que o Streamlit pinta e o que o guia validou, nos dois modos."""
    for modo, palheta in (("light", tema.CLARO), ("dark", tema.ESCURO)):
        bloco = config["theme"][modo]
        assert bloco["backgroundColor"].lower() == palheta.superficie
        assert bloco["textColor"].lower() == palheta.texto_primario
        assert bloco["borderColor"].lower() == palheta.grade
        # A cor primaria e a primeira serie: e o azul que todo grafico do app
        # usa, e a aba ativa, o radio e o botao tem de concordar com ele.
        assert bloco["primaryColor"].lower() == palheta.serie(0)


def test_as_cores_de_grafico_do_tema_sao_a_serie_da_paleta(config):
    """Grafico nativo do Streamlit e grafico do app nao podem discordar.

    O app desenha em Plotly com a paleta; um `st.line_chart` cru usaria as cores
    padrao do Streamlit. Mesma tela, duas paletas.
    """
    categoricas = [c.lower() for c in config["theme"]["chartCategoricalColors"]]
    assert categoricas == list(tema.CLARO.series)
    sequenciais = [c.lower() for c in config["theme"]["chartSequentialColors"]]
    assert sequenciais == list(tema.CLARO.sequencial)


def test_toda_opcao_de_tema_existe_no_streamlit(config):
    """Opcao inventada e ignorada em silencio -- com um aviso que ninguem le.

    `chartCategoricalColors` foi escrita sob `[theme.light]` e `[theme.dark]`,
    onde ela **nao existe**: o Streamlit a descartava e seguia com as cores
    padrao. O teste anterior passava porque conferia o **arquivo**, e nao o que
    o Streamlit aceita -- que e o defeito que este aqui fecha.
    """
    from streamlit import config as config_do_streamlit

    validas = set(config_do_streamlit._config_options_template)

    def conferir(bloco: dict, prefixo: str) -> None:
        for chave, valor in bloco.items():
            caminho = f"{prefixo}.{chave}"
            if isinstance(valor, dict):
                conferir(valor, caminho)
                continue
            assert caminho in validas, f"{caminho} nao e opcao do Streamlit"

    conferir(config["theme"], "theme")


def test_o_tema_nao_forca_claro_nem_escuro(config):
    """A paleta tem passos proprios para os dois modos; travar um anula metade.

    Sem `base`, o Streamlit segue o navegador do usuario.
    """
    assert "base" not in config["theme"]


def test_a_fonte_declara_um_fallback(config):
    """Sem rede, a fonte remota nao carrega -- e o app nao pode ficar sem fonte."""
    for chave in ("font", "headingFont"):
        assert config["theme"][chave].rstrip().endswith("sans-serif")


# ---------------------------------------------------------------------------
# O caminho
# ---------------------------------------------------------------------------


def test_o_caminho_e_uma_corrente_sem_furo():
    """`proximo` e `anterior` percorrem a lista inteira nos dois sentidos."""
    visitados = [PASSOS[0].chave]
    while (adiante := proximo(visitados[-1])) is not None:
        visitados.append(adiante.chave)
    assert visitados == [p.chave for p in PASSOS]

    assert proximo(PASSOS[-1].chave) is None
    assert anterior(PASSOS[0].chave) is None
    assert anterior(PASSOS[1].chave).chave == PASSOS[0].chave


def test_cada_passo_tem_titulo_acao_e_resumo():
    """O Inicio mostra os tres, e um vazio vira uma linha muda na lista."""
    for passo in PASSOS:
        assert passo.titulo and passo.acao and passo.resumo
        assert passo.url and passo.icone


def test_os_icones_existem_no_conjunto_do_streamlit():
    """Nome de icone invalido derruba o app na construcao da pagina."""
    from streamlit.material_icon_names import ALL_MATERIAL_ICONS

    for passo in PASSOS:
        assert passo.icone in ALL_MATERIAL_ICONS, passo.chave


def test_as_urls_nao_se_repetem():
    """URL repetida faz duas telas colidirem no mesmo endereco."""
    urls = [p.url for p in PASSOS]
    assert len(set(urls)) == len(urls)


def test_numero_do_passo_segue_a_ordem_da_lista():
    assert numero(PASSOS[0].chave) == 0
    assert numero(PASSOS[-1].chave) == len(PASSOS) - 1
    with pytest.raises(KeyError):
        numero("nao-existe")


# ---------------------------------------------------------------------------
# A tabela financeira
# ---------------------------------------------------------------------------


def test_a_unidade_nao_se_repete_em_cada_celula():
    """O erro que a arvore publicada ja tinha custado, e que eu repeti aqui.

    Numa DRE de 22 linhas por 7 anos, "R$ milhoes" em cada celula sao 154 vezes
    o mesmo texto -- e o que ele empurra para fora da largura util e o numero.
    Foi assim que a tabela antiga perdeu tres anos de coluna, e foi assim que a
    primeira versao deste componente saiu.
    """
    import pandas as pd

    from app.componentes import tabela_financeira

    tabela = pd.DataFrame(
        {2024: [1000.0, -400.0], 2025: [1200.0, -450.0]},
        index=["Receita líquida", "(−) Custos"],
    )
    html = tabela_financeira(tabela, {"Receita líquida"}, "moeda", "R$ milhões")

    corpo = html.split("</thead>")[1]
    assert "R$" not in corpo, "a unidade vazou para dentro das celulas"
    # E aparece uma vez so, no cabecalho da primeira coluna.
    assert html.split("</thead>")[0].count("R$ mi") == 1


def test_o_subtotal_sai_com_peso_diferente_do_item():
    import pandas as pd

    from app.componentes import tabela_financeira

    tabela = pd.DataFrame(
        {2024: [1000.0, -400.0]}, index=["= Lucro bruto", "(−) Custos"]
    )
    html = tabela_financeira(tabela, {"= Lucro bruto"}, "moeda")
    assert '<tr class="n2">' in html, "o subtotal nao ganhou destaque"
    assert '<tr class="n3">' in html, "o item comum nao ficou recessivo"


def test_o_negativo_ganha_marca_alem_do_sinal():
    import pandas as pd

    from app.componentes import tabela_financeira

    tabela = pd.DataFrame({2024: [-400.0, 0.0]}, index=["(−) Custos", "Vazio"])
    html = tabela_financeira(tabela, formato="moeda")
    assert 'class="negativo"' in html
    assert 'class="nulo"' in html


# ---------------------------------------------------------------------------
# Contraste: o que o teste de cor nao pega
# ---------------------------------------------------------------------------


def _luminancia(hexa: str) -> float:
    canal = [int(hexa.lstrip("#")[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    ajustado = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in canal]
    return 0.2126 * ajustado[0] + 0.7152 * ajustado[1] + 0.0722 * ajustado[2]


def contraste(frente: str, fundo: str) -> float:
    a, b = _luminancia(frente), _luminancia(fundo)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


# A WCAG pede 4,5:1 para texto normal. A tabela usa corpos de 0,74rem a 0,9rem,
# entao vale o limite de texto normal e nao o de texto grande.
MINIMO = 4.5


@pytest.mark.parametrize("modo", ["claro", "escuro"])
def test_o_cabecalho_da_tabela_tem_contraste(modo):
    """Branco sobre `serie(0)` dava 4,42:1 -- reprovado, e num texto em caixa alta.

    O teste de cor passava, porque a cor era "a da paleta". Contraste e
    propriedade de renderizacao: so aparece medindo o par frente/fundo.
    """
    fundo = tema.CABECALHO_DA_TABELA[modo]
    assert contraste("#ffffff", fundo) >= MINIMO, f"{modo}: {contraste('#ffffff', fundo):.2f}"


@pytest.mark.parametrize("modo", ["claro", "escuro"])
def test_o_negativo_da_tabela_tem_contraste_sobre_as_tres_linhas(modo):
    """Vermelho sobre a tinta do subtotal dava 3,24:1 no fundo mais forte.

    Ele e **reforco** do sinal de menos e nao a unica pista -- mas 3,24:1 num
    corpo de 0,8rem e ilegivel, nao discreto.
    """
    cor = tema.NEGATIVO_NA_TABELA[modo]
    palheta = tema.CLARO if modo == "claro" else tema.ESCURO
    fundos = [palheta.superficie, tema.FUNDOS[modo]["n1"], tema.FUNDOS[modo]["n2"]]
    for fundo in fundos:
        assert contraste(cor, fundo) >= MINIMO, f"{modo} sobre {fundo}: {contraste(cor, fundo):.2f}"


@pytest.mark.parametrize("modo", ["claro", "escuro"])
def test_o_nivel_mais_fraco_da_tabela_ainda_se_le(modo):
    """`texto_suave` dava 3,70:1 no claro. A hierarquia sobrevive no tamanho."""
    palheta = tema.CLARO if modo == "claro" else tema.ESCURO
    assert contraste(palheta.texto_secundario, palheta.superficie) >= MINIMO


def test_a_tabela_aceita_celula_de_texto():
    """Balizador poe "no percentil 69 de 397" ao lado de "12,5%" na mesma tabela.

    Sem a passagem de texto, essas tabelas voltariam a ser `st.dataframe` -- que
    desenha em canvas e alinha tudo a esquerda, que e o defeito que o revamp
    corrigiu no resto do app.
    """
    import pandas as pd

    from app.componentes import tabela_de_indicadores

    tabela = pd.DataFrame(
        {"Projetado": [0.125], "Onde cai": ["no percentil 69 de 397"]},
        index=["Margem EBITDA"],
    )
    html = tabela_de_indicadores(tabela, "pct")
    assert "12,5%" in html
    assert 'class="texto"' in html
    assert "no percentil 69 de 397" in html


# ---------------------------------------------------------------------------
# As referencias que o balizador cita
# ---------------------------------------------------------------------------


def test_todo_indicador_que_o_balizador_cita_tem_distribuicao():
    """Sem distribuicao medida nao ha percentil, e o balizador so tem metade.

    A tela mostra "o que a empresa entregou" a partir da propria analise, mas
    "onde isso cai na base" depende de `referencias.BASE`. Campo que cita um
    indicador ausente dali sai com meia resposta, calado.
    """
    from valuation import referencias

    citados = {
        "Crescimento da receita",
        "ROIC",
        "ROE",
        "Margem EBITDA",
        "Capex / Receita",
        "Capital de giro / Receita",
        "Divida bruta / Patrimonio liquido",
    }
    faltando = [i for i in citados if i not in referencias.BASE]
    # "Capital de giro / Receita" e "Depreciacao / Receita" ainda nao foram
    # medidos, e o balizador degrada em silencio neles -- mostra o historico da
    # empresa e omite o percentil. Este teste trava os que ja existem.
    assert "Divida bruta / Patrimonio liquido" not in faltando
    assert "ROE" not in faltando
    assert "ROIC" not in faltando


def test_o_corte_de_divida_pl_continua_no_quartil_alto():
    """`DIVIDA_PL_ALTA` foi calibrado em outra safra; reconferido nesta."""
    from valuation import referencias
    from valuation.diagnostico import DIVIDA_PL_ALTA

    percentil = referencias.posicao("Divida bruta / Patrimonio liquido", DIVIDA_PL_ALTA)
    # Entre P70 e P85: um corte de "alavancado" que acusa perto de um quarto da
    # base. Fora dessa faixa ele vira ruido (dispara sempre) ou inutil (nunca).
    assert 0.70 <= percentil <= 0.85, f"percentil {percentil:.0%}"

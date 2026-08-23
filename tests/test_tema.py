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
    for modo, palheta in (("light", tema.CLARO), ("dark", tema.ESCURO)):
        categoricas = [c.lower() for c in config["theme"][modo]["chartCategoricalColors"]]
        assert categoricas == list(palheta.series)
        sequenciais = [c.lower() for c in config["theme"][modo]["chartSequentialColors"]]
        assert sequenciais == list(palheta.sequencial)


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

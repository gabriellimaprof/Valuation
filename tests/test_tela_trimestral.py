"""As telas com uma **serie de trimestres isolados** dentro, sem navegador.

Esta combinacao -- serie trimestral **mais** tela -- nao era alcancada por teste
nenhum. Ela so era percorrida pela varredura do navegador, que roda por
agendamento, e foi assim que tres defeitos chegaram a producao e ficaram la:

* as duas guardas de frequencia estavam **inertes**, porque `escalar`
  reconstruia `Demonstracoes` campo a campo e perdia `periodicidade` -- e a tela
  de Dados converte para R$ milhoes logo depois de importar;
* a tabela dos direcionadores em Premissas nunca teve guarda, e acusava a
  projecao de ser doze vezes menor do que a empresa entrega;
* os cartoes do Historico diziam "Receita do 2T26" tanto para R$ 40,1 bi (ano
  movel) quanto para R$ 10,1 bi (trimestre).

O fixture passa por `escalar` de proposito: era ali que o campo se perdia, e um
fixture que nao escala nao teria pego nada disso.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from valuation.importacao.cvm import importar_ltm_rolante, importar_trimestral

pytest.importorskip("streamlit.testing.v1")
from streamlit.testing.v1 import AppTest  # noqa: E402

DADOS = Path(__file__).parent / "dados" / "cvm"
RAIZ = Path(__file__).resolve().parent.parent
WEG = 5410

# Quantos ITRs o **recorte** tem: 2024 e 2025. O padrao de producao e tres, e
# pedi-lo aqui faria o leitor **baixar** o ITR de 2023 da CVM -- 32 MB dentro do
# diretorio de fixtures, num projeto cuja regra e que nenhum teste alcanca a
# rede. Foi o que aconteceu quando o padrao mudou de dois para tres, e o guarda
# `test_os_fixtures_continuam_sendo_recortes_e_nao_downloads` acusou.
#
# Fixar aqui tambem devolve o tempo: os testes do ano movel custavam ~30s cada
# lendo tres exercicios, e a suite inteira subiu de 250s para 477s.
ITRS_NO_RECORTE = 2



def _script(modulo: str) -> str:
    return f"""
import sys
for caminho in ({str(RAIZ)!r}, {str(RAIZ / "src")!r}):
    if caminho not in sys.path:
        sys.path.insert(0, caminho)
import streamlit as st
from app import estado
from app.paginas import {modulo}

estado.iniciar()
if st.session_state.get("dfs") is not None:
    estado.definir_demonstracoes(st.session_state["dfs"])
{modulo}.render()
"""


@pytest.fixture(scope="module")
def trimestral():
    """Trimestres isolados, **passando pela troca de unidade**.

    `escalar` e o caminho real do app e era onde `periodicidade` se perdia.
    """
    return importar_trimestral(WEG, cache=DADOS, ano=2025).escalar(1e6, "R$ milhões")


@pytest.fixture(scope="module")
def ano_movel():
    """O controle: rotulo de trimestre, conteudo de doze meses.

    Toda guarda aqui tem de deixar esta serie passar -- ela e justamente a saida
    que o app oferece quando recusa a de cima. Uma decisao tomada pelo **rotulo**
    da coluna recusaria as duas, e o teste nao veria diferenca.
    """
    return importar_ltm_rolante(
        WEG, cache=DADOS, ano=2025, anos_de_itr=ITRS_NO_RECORTE
    ).escalar(1e6, "R$ milhões")


def _rodar(modulo: str, dfs) -> AppTest:
    teste = AppTest.from_string(_script(modulo), default_timeout=180)
    teste.session_state["dfs"] = dfs
    teste.run()
    assert not teste.exception, [str(e.value) for e in teste.exception]
    return teste


def _texto(teste: AppTest) -> str:
    partes = []
    for colecao in (teste.markdown, teste.info, teste.warning, teste.success, teste.caption):
        partes += [str(i.value) for i in colecao]
    for erro in teste.error:
        partes.append(str(erro.value))
    return " ".join(partes)


# ---------------------------------------------------------------------------
# A periodicidade sobrevive ao caminho real
# ---------------------------------------------------------------------------


def test_a_periodicidade_chega_a_tela(trimestral, ano_movel):
    """A raiz de tudo: `escalar` descartava o campo.

    Sem isto as duas guardas ficam inertes e **todos** os testes abaixo passam
    por engano, porque a serie chega se declarando anual.
    """
    assert trimestral.periodicidade == "trimestral"
    # Rotulo de trimestre, conteudo de doze meses.
    assert ano_movel.periodicidade == "anual"
    assert str(ano_movel.valores.columns[-1]).endswith("25")


# ---------------------------------------------------------------------------
# Historico
# ---------------------------------------------------------------------------


def test_o_historico_marca_o_periodo_nos_cartoes(trimestral, ano_movel):
    """"ROIC (mediana) 8,2%" se le como retorno anual, e nao e."""
    tri = _rodar("historico", trimestral)
    rotulos_tri = [m.label for m in tri.metric]
    assert any("por trimestre" in r for r in rotulos_tri), rotulos_tri

    movel = _rodar("historico", ano_movel)
    assert not any("por trimestre" in m.label for m in movel.metric)


def test_o_veredito_de_qualidade_recusa_a_serie_trimestral(trimestral, ano_movel):
    """Medido em 30 companhias, ele muda em 37% delas entre as duas leituras.

    Os seis insumos do veredito nao atravessam a frequencia -- os seis --, entao
    nao ha subconjunto que se salve.
    """
    from valuation.historico import analisar
    from valuation.qualidade import SEM_DADOS, avaliar_qualidade

    assert avaliar_qualidade(analisar(trimestral)).veredito == SEM_DADOS
    assert avaliar_qualidade(analisar(ano_movel)).veredito != SEM_DADOS


# ---------------------------------------------------------------------------
# Premissas
# ---------------------------------------------------------------------------


def test_premissas_avisa_antes_do_clique_e_oferece_a_saida(trimestral):
    """A recusa nomeava o ano movel sem oferece-lo.

    E o aviso vem **antes** do botao de sugerir: quem ve a serie trimestral
    descobre que a projecao nao sai sem precisar clicar, levar a recusa e so
    entao achar o caminho.
    """
    teste = _rodar("premissas", trimestral)
    texto = _texto(teste)
    assert "trimestres isolados" in texto
    rotulos = [b.label for b in teste.button]
    assert any("Ano móvel" in r for r in rotulos), rotulos


def test_o_apptest_nao_enxerga_o_conteudo_de_st_html():
    """**O ponto cego que deixou o defeito da tabela passar**, travado por teste.

    A tabela dos direcionadores vai por `st.html`, e nao por `st.dataframe`, por
    decisao documentada: o Styler do pandas so atravessa **cor** para o canvas
    do Streamlit, e nao peso nem tamanho de fonte -- que sao o que separa um
    total de um item folha.

    O custo dessa decisao e este: `AppTest` **nao expoe colecao nenhuma** para
    `st.html`. Um teste de tela que procurasse o conteudo da tabela ali passaria
    por vazio -- procurando numa coleção que nao existe, e concluindo que o
    texto errado nao esta la porque texto nenhum esta.

    Por isso o conteudo da tabela e verificado **chamando a funcao**, em
    `test_app.py::test_a_tabela_dos_direcionadores_respeita_a_frequencia`, que
    captura o quadro antes de ele virar HTML. Este teste existe para que a
    proxima pessoa nao escreva o teste vazio.
    """
    teste = AppTest.from_string(
        "import streamlit as st\nst.html('<p>marcador</p>')\nst.markdown('visivel')",
        default_timeout=30,
    )
    teste.run()

    assert not hasattr(teste, "html")
    assert "visivel" in " ".join(m.value for m in teste.markdown)
    assert not any("marcador" in m.value for m in teste.markdown)


def test_o_ano_movel_passa_pelas_guardas(ano_movel):
    """O controle que impede a guarda de ser tomada pelo rotulo da coluna.

    O ano movel tem colunas `1T25`, `2T25`, `3T25` e conteudo de doze meses. Se
    alguem trocar `periodicidade` por uma leitura do rotulo, este teste quebra --
    e os outros continuariam passando.
    """
    teste = _rodar("premissas", ano_movel)
    texto = _texto(teste)
    assert "trimestres isolados" not in texto
    assert not any("Ano móvel" in b.label for b in teste.button)


# ---------------------------------------------------------------------------
# Diagnostico
# ---------------------------------------------------------------------------


def test_o_diagnostico_declara_o_que_nao_verificou(trimestral, ano_movel):
    """Lista de achados menor nao e modelo mais limpo.

    Sete verificacoes confrontam a premissa -- que e de um exercicio -- com o
    historico. Numa serie trimestral o ROIC da companhia sai a um quarto e o
    achado **inverte de sinal**: na WEG, 36,6% anual contra 8,2% trimestral.
    """
    tri = _rodar("diagnostico", trimestral)
    texto = _texto(tri)
    assert "não rodaram" in texto
    # E ela diz **quais**, porque "algumas não rodaram" nao dirige atencao.
    assert "ROIC" in texto

    movel = _rodar("diagnostico", ano_movel)
    assert "não rodaram" not in _texto(movel)


def test_o_diagnostico_nao_aprova_o_que_nao_testou(trimestral):
    """"Passou nas verificacoes" nao pode vir logo abaixo de "7 nao rodaram".

    Visto no navegador, e nenhum teste pegaria: as duas pecas estao certas em
    separado, e so a contradicao entre elas e o defeito.
    """
    teste = _rodar("diagnostico", trimestral)
    aprovacoes = [str(i.value) for i in teste.success]
    assert not any("passou nas verificações" in a.lower() for a in aprovacoes), aprovacoes


# ---------------------------------------------------------------------------
# Custo de capital
# ---------------------------------------------------------------------------


def test_o_kd_da_empresa_some_e_diz_por_que(trimestral, ano_movel):
    """A frase fica ao lado do campo que pede uma **taxa ao ano**.

    Medido em 60 companhias, o custo da divida pela competencia sai a **0,26x**
    numa serie de trimestres isolados: juro de tres meses sobre saldo de divida.
    """
    tri = _rodar("custo_capital", trimestral)
    texto = _texto(tri)
    assert "Sem o Kd da empresa" in texto
    # A ausencia diz por que, e nao so desaparece.
    assert "trimestres isolados" in texto
    assert "Na empresa:" not in texto

    movel = _rodar("custo_capital", ano_movel)
    assert "Sem o Kd da empresa" not in _texto(movel)

"""A tela de Dados renderizada de verdade, sem navegador.

O app era verificado so no navegador, o que e lento, manual e some quando o
script sai do scratchpad. O ``AppTest`` do Streamlit executa a tela inteira em
processo: se um widget quebrar, uma tabela nao montar ou o Arrow recusar um
tipo, aparece aqui -- com a excecao, e nao com um timeout.

Nao substitui o navegador, que continua sendo onde se ve colisao de layout e
markdown cru. Cobre o que da para afirmar sem olhar: que a tela roda, e com
quais dados.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from valuation.importacao.cvm import importar_cvm

pytest.importorskip("streamlit.testing.v1")
from streamlit.testing.v1 import AppTest  # noqa: E402

DADOS = Path(__file__).parent / "dados" / "cvm"

RAIZ = Path(__file__).resolve().parent.parent

# A tela roda em processo separado, entao o script precisa achar o pacote.
SCRIPT = f"""
import sys
for caminho in ({str(RAIZ)!r}, {str(RAIZ / "src")!r}):
    if caminho not in sys.path:
        sys.path.insert(0, caminho)
import streamlit as st
from app import estado
from app.paginas import dados

estado.iniciar()
if "dfs" in st.session_state and st.session_state["dfs"] is not None:
    estado.definir_demonstracoes(st.session_state["dfs"])
dados.render()
"""


@pytest.fixture(scope="module")
def weg():
    return importar_cvm(5410, [2023, 2024], cache=DADOS).escalar(1e6, "R$ milhões")


def _rodar(dfs=None) -> AppTest:
    teste = AppTest.from_string(SCRIPT, default_timeout=120)
    teste.session_state["dfs"] = dfs
    teste.run()
    assert not teste.exception, [str(e.value) for e in teste.exception]
    return teste


def test_tela_abre_sem_dados():
    """Sem nada importado a tela nao pode quebrar -- e a primeira que se ve."""
    teste = _rodar()
    assert teste.tabs, "as abas de origem sumiram"


def _tabelas_publicadas(teste) -> list[str]:
    """O HTML de cada demonstracao publicada desenhada na tela.

    A arvore deixou de ser ``st.dataframe`` e passou a ser HTML: o Styler do
    pandas so leva cor para o canvas do Streamlit, e nao peso nem tamanho de
    fonte -- que sao justamente o que separa um total de um item folha. Efeito
    colateral bem-vindo: o numero passa a existir no DOM, entao da para conferi-lo
    aqui e no navegador, o que o canvas nunca permitiu.
    """
    return [e.body for e in teste.get("html") if "df-publicada" in (e.body or "")]


def test_tela_desenha_as_tres_demonstracoes(weg):
    teste = _rodar(weg)

    tabelas = _tabelas_publicadas(teste)
    assert len(tabelas) >= 3

    # DRE, balanco e DFC, cada uma com a arvore publicada.
    linhas = sorted(t.count("<tr class=") for t in tabelas[:3])
    assert linhas[0] >= 20, "a DRE publicada tem mais que umas poucas linhas"
    assert linhas[-1] >= 90, "o balanco publicado tem dezenas de linhas"

    # Duas colunas de ano em todas.
    for tabela in tabelas[:3]:
        assert tabela.count("<th>") == 2, "sobrou ou faltou coluna de ano"


def test_o_botao_de_abrir_a_arvore_existe_em_cada_demonstracao(weg):
    """Uma alavanca por demonstracao com arvore -- hoje as seis da CVM."""
    from app.paginas.dados import DEMONSTRACOES, _tem

    teste = _rodar(weg)
    rotulos = [t.label for t in teste.toggle]
    esperadas = sum(1 for chave, _ in DEMONSTRACOES if _tem(weg, chave))
    assert rotulos.count("Demonstração publicada, com a abertura") == esperadas
    assert esperadas == 6, "a WEG publica as seis demonstracoes"


def test_desligar_a_arvore_mostra_so_as_contas_do_modelo(weg):
    """O recorte canonico e menor que a demonstracao publicada."""
    teste = _rodar(weg)
    publicadas = _tabelas_publicadas(teste)[0].count("<tr class=")

    alavanca = next(
        t for t in teste.toggle if t.label == "Demonstração publicada, com a abertura"
    )
    alavanca.set_value(False).run()
    assert not teste.exception, [str(e.value) for e in teste.exception]
    canonicas = teste.dataframe[0].value.shape[0]

    assert 0 < canonicas < publicadas


def test_a_arvore_desenhada_tem_a_hierarquia(weg):
    """O nivel do plano de contas chega a tela em peso e em recuo.

    Sao duas leituras da mesma informacao e nenhuma substitui a outra: o peso
    diz "isto e um total", o recuo diz "dentro de quem". Num quarto nivel com
    rotulo longo, so o peso perderia o caminho de volta ao pai.
    """
    tabelas = _tabelas_publicadas(_rodar(weg))
    junto = "".join(tabelas[:3])

    for nivel in (1, 2, 3):
        assert f'<tr class="n{nivel}">' in junto, f"nenhuma linha de nivel {nivel}"
    assert "0 * 0.85rem" in junto, "o primeiro nivel nao ficou rente a margem"
    assert "2 * 0.85rem" in junto, "faltou o recuo do terceiro nivel"


def test_a_escala_escolhida_chega_na_arvore(weg):
    """Em R$ milhoes o ativo total da WEG fica na casa das dezenas de milhar."""
    balanco = max(_tabelas_publicadas(_rodar(weg)), key=lambda t: t.count("<tr class="))
    primeira = balanco.split("<tr class=")[1]
    assert "Ativo Total" in primeira, "a primeira linha do balanco nao e o ativo"
    ativo = primeira.split("<td>")[-1].split("</td>")[0]
    assert 30_000 < float(ativo.replace(".", "").replace(",", ".")) < 60_000


# ---------------------------------------------------------------------------
# As seis demonstracoes, e nao tres
# ---------------------------------------------------------------------------


def test_as_seis_demonstracoes_ganham_aba(weg):
    """Medido na WEG de 2024: o zip traz 574 linhas consolidadas.

    DRE, balanco e DFC somam 276; as outras 298 estao em DMPL, DVA e DRA. Mais
    da metade do que a companhia publica ficava fora da tela mesmo ja sendo
    lida pelo importador.
    """
    teste = _rodar(weg)
    rotulos = [aba.label for aba in teste.tabs if aba.label]
    for esperado in (
        "Resultado",
        "Balanço",
        "Fluxo de caixa",
        "Valor adicionado",
        "Resultado abrangente",
        "Mutações do PL",
        "O que o app entendeu",
    ):
        assert esperado in rotulos, f"faltou a aba {esperado}: {rotulos}"


def test_demonstracao_ausente_nao_ganha_aba_vazia(weg):
    """Aba vazia promete conteudo e nao entrega.

    Planilha importada nao tem DMPL nem DRA, e o usuario nao teria como saber se
    o app deixou de ler ou se a companhia nao publicou.
    """
    sem_arvore = type(weg)(**{**weg.__dict__, "detalhe": None})
    teste = _rodar(sem_arvore)
    rotulos = [aba.label for aba in teste.tabs if aba.label]
    assert "Mutações do PL" not in rotulos
    assert "Resultado abrangente" not in rotulos
    # As que tem conta canonica continuam.
    assert "Resultado" in rotulos and "O que o app entendeu" in rotulos


def test_a_dva_traz_o_que_a_dre_nao_abre(weg):
    """Receita bruta, folha e o total pago ao governo so existem na DVA.

    Sao 450 das 467 companhias. Contra a receita liquida do 3.01, a diferenca
    para a bruta do 7.01.01 sao impostos sobre vendas e devolucoes -- 9,0% na
    WEG.
    """
    arvore = weg.arvore("dva")
    assert not arvore.empty
    assert weg.valor("receita_bruta", 2024) > weg.valor("receita_liquida", 2024)


# ---------------------------------------------------------------------------
# Contas remontadas por soma
# ---------------------------------------------------------------------------


def test_a_conferencia_diz_o_que_a_regra_achou(weg):
    """Capex, juro pago e dividendo pago não existem como linha única na CVM.

    Chegam partidos em várias rubricas e são somados por regra, então a tela de
    conferência precisa dizer o que a regra montou nesta companhia.
    """
    teste = _rodar(weg)
    texto = " ".join(m.value for m in teste.markdown)
    assert "Contas remontadas por soma" in texto

    tabelas = [d.value for d in teste.dataframe]
    quadro = [t for t in tabelas if "Situação" in list(t.columns)]
    assert quadro, "o quadro das contas remontadas nao chegou a tela"
    assert len(quadro[0]) == 3


def test_ausente_e_escapou_nao_sao_a_mesma_coisa(weg):
    """Os dois motivos pedem coisas diferentes, e confundi-los custa tempo.

    Companhia que não pagou dividendo não tem o que mapear; mandar o analista
    procurar o que não existe gasta o tempo dele. Medido na base de 2024: em
    dividendos pagos, **172 das 467 simplesmente não pagaram**, e a cobertura vai
    de 61% aparente para 96% real.
    """
    from valuation.auditoria import ContaSomadaNaCompanhia

    achou = ContaSomadaNaCompanhia("capex", 100.0, "6.02.01", [])
    nao_tem = ContaSomadaNaCompanhia("dividendos_pagos", float("nan"), "", [])
    escapou = ContaSomadaNaCompanhia(
        "juros_pagos", float("nan"), "", ["Juros sobre empréstimos"]
    )
    assert achou.situacao == "encontrada"
    assert nao_tem.situacao == "ausente"
    assert escapou.situacao == "escapou"


def test_valor_zero_nao_conta_como_encontrada():
    """Conta somada que deu zero é conta que a regra não montou.

    É a mesma armadilha da medição de cobertura: linha publicada zerada não é
    dado, e tratá-la como achado esconderia que não há nada ali.
    """
    from valuation.auditoria import ContaSomadaNaCompanhia

    assert ContaSomadaNaCompanhia("capex", 0.0, "", []).situacao == "ausente"


# ---------------------------------------------------------------------------
# As tres leituras do tempo, na tela
# ---------------------------------------------------------------------------


def test_a_tela_oferece_as_tres_leituras_do_tempo():
    """Anual, trimestral e ano móvel respondem perguntas diferentes.

    O exercício é o único que fecha com o resultado que a companhia divulga como
    do ano; o trimestre isolado mostra inflexão mas carrega sazonalidade; o ano
    móvel tira a sazonalidade sem esperar o exercício fechar.
    """
    from app.paginas.dados import VISOES

    assert list(VISOES) == [
        "Anual",
        "Anual + ano móvel",
        "Trimestral (isolado)",
        "Ano móvel rolante",
    ]
    # Cada uma diz o que responde e o que custa.
    assert "sazonalidade" in VISOES["Trimestral (isolado)"]
    assert "tendência" in VISOES["Ano móvel rolante"]
    assert "não é um exercício social" in VISOES["Anual + ano móvel"]


def test_o_catalogo_e_chamado_pelo_nome_certo():
    """``_catalogo()`` não existe, e o erro só aparecia ao clicar em importar.

    O caminho do ano móvel carregava a chamada errada desde que foi escrito: o
    ``NameError`` não é ``ErroCVM``, então o ``try`` em volta não o pegava e a
    tela quebrava inteira. Nenhum teste alcançava a linha porque ela só roda com
    rede.
    """
    import inspect

    from app.paginas import dados

    fonte = inspect.getsource(dados)
    assert "_catalogo()" not in fonte, "sobrou chamada ao helper inexistente"
    assert "_catalogo_cvm()" in fonte


# ---------------------------------------------------------------------------
# A linha que a companhia publica zerada
# ---------------------------------------------------------------------------


def test_linhas_zeradas_em_todo_ano_ficam_fora_por_padrao(weg):
    """A companhia entrega o plano de contas inteiro e marca com zero o que nao tem.

    Medido em 40 companhias de 2019 a 2025: **37,1% das linhas publicadas sao
    zero em todos os anos** -- 51,6% no balanco. Sao linhas que nao dizem nada e
    empurram para fora da tela as que dizem.
    """
    todas = weg.linhas_publicadas("bp")
    vivas = weg.linhas_publicadas("bp", ocultar_vazias=True)

    assert 0 < len(vivas) < len(todas)
    anos = [c for c in vivas.columns if isinstance(c, int)]
    sobreviventes = vivas[anos].to_numpy(dtype=float)
    assert (sobreviventes != 0).any(axis=1).all(), "sobrou linha zerada"


def test_a_linha_zerada_com_filha_com_valor_nao_some(weg):
    """O bloco do lucro por acao e um pai sem valor proprio, e nao pode sumir.

    Medido: das linhas zeradas com filha viva, **todas** sao ``3.99`` -- o
    numero mora em ``3.99.01.01`` e o pai e so titulo. Esconder pela leitura da
    propria linha apagaria o lucro por acao junto com o caminho ate ele.
    """
    vivas = weg.linhas_publicadas("dre", ocultar_vazias=True)
    codigos = set(vivas["codigo"].astype(str))
    anos = [c for c in vivas.columns if isinstance(c, int)]

    pai = vivas[vivas["codigo"] == "3.99"]
    assert not pai.empty, "o titulo do lucro por acao sumiu"
    assert (pai[anos].to_numpy(dtype=float) == 0).all(), "o pai devia ser zerado"
    assert "3.99.01.01" in codigos, "a filha com valor sumiu junto"


def test_o_numero_do_que_foi_escondido_aparece_na_tela(weg):
    """Linha escondida sem aviso e o app decidindo pelo analista o que ele ve."""
    teste = _rodar(weg)
    alavancas = [t.label for t in teste.toggle]
    assert any(
        "zeradas em todos os anos" in rotulo for rotulo in alavancas
    ), "nao ha como pedir de volta as linhas escondidas"


def test_ligar_a_alavanca_traz_as_zeradas_de_volta(weg):
    teste = _rodar(weg)
    antes = _tabelas_publicadas(teste)[0].count("<tr class=")

    alavanca = next(t for t in teste.toggle if "zeradas em todos os anos" in t.label)
    alavanca.set_value(True).run()
    assert not teste.exception, [str(e.value) for e in teste.exception]

    depois = _tabelas_publicadas(teste)[0].count("<tr class=")
    assert depois > antes


# ---------------------------------------------------------------------------
# O lucro por acao nao esta na moeda escalada do arquivo
# ---------------------------------------------------------------------------


def test_o_lucro_por_acao_nao_leva_a_escala_do_arquivo():
    """``ESCALA_MOEDA`` vale para a demonstracao, e o bloco 3.99 nao e moeda.

    A CVM declara ``MIL`` para o arquivo inteiro e escreve o lucro por acao em
    reais na mesma linha -- o rotulo diz, "Lucro por Acao - (Reais / Acao)".
    Multiplicar por mil transformava o R$ 1,44 da WEG em R$ 1.440,26, e a
    conversao para R$ milhoes depois o achatava em 0,0 na tela.

    Medido no DRE consolidado de 2024: 889 linhas de **384 companhias**, com
    mediana de |valor| bruto em 1,31 e 99% abaixo de 1.000.
    """
    bruto = importar_cvm(5410, [2023, 2024], cache=DADOS)
    linhas = bruto.linhas_publicadas("dre")
    eps = linhas[linhas["codigo"] == "3.99.01.01"]
    assert not eps.empty, "a WEG publica lucro por acao"
    assert eps[2024].iloc[0] == pytest.approx(1.44026, rel=1e-6)

    # E a troca de unidade da demonstracao tambem nao o toca: reais por acao
    # continuam reais por acao quando o balanco vira R$ milhoes.
    em_milhoes = bruto.escalar(1e6, "R$ milhões")
    depois = em_milhoes.linhas_publicadas("dre")
    valor = depois[depois["codigo"] == "3.99.01.01"][2024].iloc[0]
    assert valor == pytest.approx(1.44026, rel=1e-6)

    # Enquanto uma conta de moeda de verdade acompanha a escala.
    receita = depois[depois["codigo"] == "3.01"][2024].iloc[0]
    assert 30_000 < float(receita) < 45_000


def test_a_tabela_marca_a_linha_que_esta_em_reais_por_acao(weg):
    """Um "1,4" sem marca, na coluna de um balanco em R$ milhoes, se le errado."""
    from app.componentes import tabela_de_demonstracao

    html = tabela_de_demonstracao(weg.linhas_publicadas("dre", ocultar_vazias=True))
    linha_do_eps = next(
        pedaco for pedaco in html.split("<tr class=") if 'title="3.99.01.01"' in pedaco
    )
    assert "R$/ação" in linha_do_eps
    assert "1,44" in linha_do_eps

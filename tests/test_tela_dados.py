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


def test_tela_desenha_as_tres_demonstracoes(weg):
    teste = _rodar(weg)

    tabelas = [t.value for t in teste.dataframe]
    assert len(tabelas) >= 3

    # DRE, balanco e DFC, cada uma com a arvore publicada inteira.
    linhas = sorted(t.shape[0] for t in tabelas[:3])
    assert linhas[0] >= 20, "a DRE publicada tem mais que umas poucas linhas"
    assert linhas[-1] >= 150, "o balanco publicado tem mais de 150 linhas"

    # Duas colunas de ano em todas.
    assert all(t.shape[1] == 2 for t in tabelas[:3])


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
    publicadas = teste.dataframe[0].value.shape[0]

    teste.toggle[0].set_value(False).run()
    assert not teste.exception, [str(e.value) for e in teste.exception]
    canonicas = teste.dataframe[0].value.shape[0]

    assert 0 < canonicas < publicadas


def test_a_arvore_desenhada_tem_a_hierarquia(weg):
    """O recuo chega ate a tela: e ele que mostra o que compoe o que."""
    from valuation.importacao.importador import RECUO

    teste = _rodar(weg)
    indices = [str(i) for t in teste.dataframe[:3] for i in t.value.index]
    assert any(i.startswith(RECUO) for i in indices), "nenhuma linha saiu recuada"
    assert any(i.startswith(RECUO * 2) for i in indices), "faltou o terceiro nivel"


def test_a_escala_escolhida_chega_na_arvore(weg):
    """Em R$ milhoes o ativo total da WEG fica na casa das dezenas de milhar."""
    teste = _rodar(weg)
    balanco = next(
        t.value for t in teste.dataframe if t.value.shape[0] > 150
    )
    ativo = balanco.iloc[0, -1]
    assert 30_000 < float(str(ativo).replace(".", "").replace(",", ".")) < 60_000


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

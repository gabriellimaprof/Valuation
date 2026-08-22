"""A tela de Historico com a aba de liquidez e composicao, sem navegador."""

from __future__ import annotations

from pathlib import Path

import pytest

from valuation.historico import sugerir_premissas, analisar
from valuation.importacao.cvm import importar_cvm

pytest.importorskip("streamlit.testing.v1")
from streamlit.testing.v1 import AppTest  # noqa: E402

DADOS = Path(__file__).parent / "dados" / "cvm"
RAIZ = Path(__file__).resolve().parent.parent

SCRIPT = f"""
import sys
for caminho in ({str(RAIZ)!r}, {str(RAIZ / "src")!r}):
    if caminho not in sys.path:
        sys.path.insert(0, caminho)
import streamlit as st
from app import estado
from app.paginas import historico

estado.iniciar()
if st.session_state.get("dfs") is not None:
    estado.definir_demonstracoes(st.session_state["dfs"])
historico.render()
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


def test_tela_abre_sem_historico():
    """Sem demonstracoes a tela precisa orientar, nao quebrar."""
    _rodar()


def test_aba_de_liquidez_aparece_quando_ha_arvore(weg):
    teste = _rodar(weg)
    rotulos = [aba.label for aba in teste.tabs if aba.label]
    assert "Liquidez e composição" in rotulos


def test_a_aba_traz_os_indicadores_e_a_composicao(weg):
    teste = _rodar(weg)
    texto = " ".join(m.value for m in teste.markdown)
    assert "Liquidez" in texto
    assert "De que cada conta é feita" in texto

    # Uma tabela de liquidez e uma composicao por conta aberta.
    assert len(teste.dataframe) >= 1
    rotulos_expander = [e.label for e in teste.expander]
    assert any("Ativo circulante" in r for r in rotulos_expander)
    assert any("Dívida de curto prazo" in r for r in rotulos_expander)


def test_sem_arvore_a_aba_nao_existe(weg):
    """Planilha importada sem hierarquia nao ganha uma aba vazia."""
    sem_arvore = type(weg)(**{**weg.__dict__, "detalhe": None})
    teste = _rodar(sem_arvore)
    rotulos = [aba.label for aba in teste.tabs if aba.label]
    assert "Liquidez e composição" not in rotulos
    # E as demais abas continuam la.
    assert "Resultado" in rotulos and "Tudo" in rotulos


# ---------------------------------------------------------------------------
# Qualidade dos lucros
# ---------------------------------------------------------------------------


def test_a_aba_de_qualidade_aparece_e_da_um_veredito(weg):
    teste = _rodar(weg)
    rotulos = [aba.label for aba in teste.tabs if aba.label]
    assert "Qualidade dos lucros" in rotulos

    qualidade = teste.session_state["qualidade"]
    assert qualidade.sinais, "o motor rodou mas nao produziu sinal nenhum"
    assert qualidade.veredito in ("bom", "atencao", "ruim", "sem dados")


def test_o_veredito_e_o_pior_sinal_e_a_tela_diz_isso(weg):
    """Media de sinais e como um alerta some; a tela precisa explicar a regra."""
    teste = _rodar(weg)
    texto = " ".join(m.value for m in teste.markdown)
    assert "Lucro é opinião, caixa é fato" in texto

    from valuation.qualidade import ATENCAO, BOM, RUIM, SEM_DADOS

    qualidade = teste.session_state["qualidade"]
    vereditos = [s.veredito for s in qualidade.sinais if s.veredito != SEM_DADOS]
    if vereditos:
        pior = min(vereditos, key=lambda v: {RUIM: 0, ATENCAO: 1, BOM: 2}[v])
        assert qualidade.veredito == pior


def test_os_cortes_sao_apresentados_como_convencao(weg):
    """Nao calibrados contra a base da CVM -- e a tela nao pode esconder isso."""
    teste = _rodar(weg)
    assert any("convenções de leitura" in c.value for c in teste.caption)


# ---------------------------------------------------------------------------
# A DRE gerencial
# ---------------------------------------------------------------------------


def test_a_aba_de_dre_e_a_primeira(weg):
    """E a primeira porque e de onde tudo o mais sai."""
    teste = _rodar(weg)
    rotulos = [aba.label for aba in teste.tabs if aba.label]
    assert rotulos[0] == "DRE"


def test_a_tela_mostra_a_ponte_na_ordem_da_especificacao(weg):
    teste = _rodar(weg)
    dre = weg.dre_gerencial()
    assert list(dre.index)[:3] == ["Receita líquida", "(−) Custos", "= Lucro bruto"]

    # A tabela exibida e a mesma que o motor monta, so formatada.
    exibidas = [
        quadro for quadro in teste.dataframe if "= EBITDA ajustado" in list(quadro.value.index)
    ]
    assert exibidas, "a DRE gerencial nao chegou a tela"
    assert list(exibidas[0].value.index) == list(dre.index)


def test_a_conferencia_aparece_junto_e_nao_escondida(weg):
    """Ponte montada por subtracao precisa ser vista fechando, nao presumida."""
    teste = _rodar(weg)
    textos = [s.value for s in teste.success]
    assert any("subtotais fecham" in t for t in textos), textos


def test_a_tela_avisa_quando_um_subtotal_nao_fecha(weg):
    """Companhia que publica DRE inconsistente tem que aparecer como tal."""
    import pandas as pd

    quebrada = type(weg)(**{**weg.__dict__, "valores": weg.valores.copy()})
    quebrada.valores.loc["lucro_liquido"] = (
        pd.to_numeric(quebrada.valores.loc["lucro_liquido"]) * 2
    )
    teste = _rodar(quebrada)
    textos = [a.value for a in teste.warning]
    assert any("não fecha" in t for t in textos), textos


def test_a_dre_em_percentual_da_receita(weg):
    """Estrutura de custo e o que se projeta; a tela oferece as duas leituras."""
    teste = _rodar(weg)
    radios = [r for r in teste.radio if r.label == "Como exibir"]
    assert radios, "faltou a escolha entre valores e percentual"
    radios[0].set_value("% da receita líquida").run()
    assert not teste.exception, [str(e.value) for e in teste.exception]

    exibidas = [
        quadro for quadro in teste.dataframe if "= EBITDA ajustado" in list(quadro.value.index)
    ]
    assert exibidas
    assert exibidas[0].value.loc["Receita líquida"].iloc[0].startswith("100,0%")


def test_a_tela_diz_que_o_ebitda_ajustado_nao_e_o_do_release(weg):
    """A confusão mais provável de quem lê a aba, dita antes de acontecer.

    O ajuste daqui sai dos códigos que a CVM padroniza; o do release da
    companhia tira o que ela decidiu chamar de não recorrente, que mora dentro
    do SG&A e não existe separado no DFP. Medido na Viveo de 2024: R$ 652 mi no
    release contra R$ 131,8 mi nesta ponte. Os dois estão certos sobre coisas
    diferentes, e quem não souber disso vai achar que um deles está errado.
    """
    teste = _rodar(weg)
    textos = " ".join(i.value for i in teste.info)
    assert "não é o do release" in textos, textos
    assert "3.04.03" in textos

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

"""As telas que ganharam a macro de longo prazo, sem navegador.

Duas coisas so podem ser verificadas com a tela rodando: que a ancora escolhida
em Premissas chega ao modelo, e que o estresse macro em Sensibilidade nao
quebra nem sai mudo. O resto -- a aritmetica da ancora -- esta em test_macro.py.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("streamlit.testing.v1")
from streamlit.testing.v1 import AppTest  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent

CABECALHO = f"""
import sys
for caminho in ({str(RAIZ)!r}, {str(RAIZ / "src")!r}):
    if caminho not in sys.path:
        sys.path.insert(0, caminho)
import streamlit as st
from app import estado
from valuation import substituir_varios

estado.iniciar()
if st.session_state.get("alteracoes"):
    estado.definir_empresa(
        substituir_varios(estado.empresa(), st.session_state["alteracoes"])
    )
"""

TELA_PREMISSAS = CABECALHO + """
from app.paginas import premissas
premissas.render()
"""

TELA_SENSIBILIDADE = CABECALHO + """
from app.paginas import sensibilidade
sensibilidade.render()
"""


def _rodar(script: str, alteracoes: dict | None = None) -> AppTest:
    teste = AppTest.from_string(script, default_timeout=120)
    if alteracoes:
        teste.session_state["alteracoes"] = alteracoes
    teste.run()
    assert not teste.exception, teste.exception
    return teste


# ---------------------------------------------------------------------------
# Premissas
# ---------------------------------------------------------------------------


def test_a_tela_de_premissas_abre_com_a_ancora_livre():
    teste = _rodar(TELA_PREMISSAS)
    ancora = next(s for s in teste.selectbox if s.label == "De onde vem o g")
    assert ancora.value.startswith("Livre"), "ninguem pode ganhar uma ancora sem pedir"
    assert teste.session_state["empresa"].perpetuidade.ancora == "livre"


def test_escolher_a_ancora_grava_no_modelo():
    teste = _rodar(TELA_PREMISSAS)
    ancora = next(s for s in teste.selectbox if s.label == "De onde vem o g")
    ancora.select("PIB nominal").run()

    botao = next(b for b in teste.button if b.label == "Aplicar perpetuidade")
    botao.click().run()
    assert not teste.exception, teste.exception

    empresa = teste.session_state["empresa"]
    assert empresa.perpetuidade.ancora == "pib_nominal"
    assert empresa.perpetuidade.crescimento_perpetuo == pytest.approx(
        empresa.macro.pib_nominal
    )


def test_o_campo_do_g_fica_travado_quando_ancorado():
    """Ancorado, o g e derivado: deixar o campo editavel seria mentir na tela."""
    teste = _rodar(TELA_PREMISSAS, {"perpetuidade.ancora": "ipca"})
    campo = next(
        n for n in teste.number_input if n.label == "Crescimento perpétuo (%)"
    )
    assert campo.disabled
    assert campo.value == pytest.approx(teste.session_state["empresa"].macro.inflacao_brl * 100)


def test_o_pib_real_e_editavel_na_tela_de_premissas():
    teste = _rodar(TELA_PREMISSAS)
    campo = next(
        n for n in teste.number_input if n.label == "PIB real de longo prazo (%)"
    )
    campo.set_value(0.5).run()
    next(b for b in teste.button if b.label == "Aplicar perpetuidade").click().run()

    assert teste.session_state["empresa"].macro.pib_real == pytest.approx(0.005)


# ---------------------------------------------------------------------------
# Sensibilidade
# ---------------------------------------------------------------------------


def test_o_estresse_macro_roda_e_diz_alguma_coisa():
    teste = _rodar(TELA_SENSIBILIDADE)
    assert any("Estresse macro" in m.value for m in teste.markdown)
    assert any("risco-país move" in c.value for c in teste.caption), (
        "a leitura do estresse sumiu"
    )

    tabela = teste.session_state["tabela_cenarios_macro"]
    assert "Base" in tabela.columns
    assert tabela.shape[1] == 4


def test_o_estresse_macro_mede_cada_choque_separado():
    """Os tres cenarios tem que dar tres numeros distintos do base."""
    teste = _rodar(TELA_SENSIBILIDADE, {"perpetuidade.ancora": "pib_nominal"})
    tabela = teste.session_state["tabela_cenarios_macro"]

    por_nome = {c: float(tabela.loc["equity_value", c]) for c in tabela.columns}
    base = por_nome["Base"]
    ipca = next(v for c, v in por_nome.items() if c.startswith("IPCA"))
    risco = next(v for c, v in por_nome.items() if c.startswith("Risco"))
    pib = next(v for c, v in por_nome.items() if c.startswith("PIB"))

    assert ipca < base and risco < base
    assert pib < base, "ancorado em PIB nominal, o PIB fraco tem que doer"
    assert ipca != risco


def test_os_eixos_macro_existem_e_avisam_quando_nao_movem_nada():
    teste = _rodar(TELA_SENSIBILIDADE)
    eixos = [s for s in teste.selectbox if s.label in ("Nas linhas", "Nas colunas")]
    assert "PIB real de longo prazo" in eixos[0].options

    eixos[0].select("PIB real de longo prazo").run()
    assert not teste.exception, teste.exception
    avisos = [i.value for i in teste.info]
    assert any("não altera o valuation" in a for a in avisos), (
        "sem âncora em PIB nominal, o eixo sai achatado e a tela precisa dizer"
    )

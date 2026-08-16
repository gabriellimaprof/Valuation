"""Margem de seguranca na tela, e o relatorio que sai da exportacao.

O que so da para verificar com a tela rodando: que o preco informado numa tela
chega na outra (senao as duas discordam sem que nada acuse), e que o relatorio
sai completo quando as pecas existem e confessa a ausencia quando nao existem.
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
if st.session_state.get("preco"):
    estado.definir_preco(*st.session_state["preco"])
if st.session_state.get("dfs") is not None:
    estado.definir_demonstracoes(st.session_state["dfs"])
"""

TELA_MARGEM = CABECALHO + """
from app.paginas import margem
margem.render()
"""

TELA_EXPORTAR = CABECALHO + """
from app.paginas import exportar
exportar.render()
"""


def _rodar(script: str, **estado_inicial) -> AppTest:
    teste = AppTest.from_string(script, default_timeout=240)
    for chave, valor in estado_inicial.items():
        teste.session_state[chave] = valor
    teste.run()
    assert not teste.exception, [str(e.value) for e in teste.exception]
    return teste


# ---------------------------------------------------------------------------
# A tela
# ---------------------------------------------------------------------------


def test_a_tela_abre_com_o_preco_igual_ao_valor(_=None):
    teste = _rodar(TELA_MARGEM)
    rotulos = {m.label: m.value for m in teste.metric}
    assert rotulos["Margem sobre o valor"] == "0,0%"
    assert rotulos["Valor calculado"] == rotulos["Preço pedido"]


def test_preco_abaixo_do_valor_da_margem_positiva():
    empresa_valor = 930.0  # equity value da empresa inicial do app
    teste = _rodar(TELA_MARGEM, preco=(empresa_valor * 0.6, False))
    rotulos = {m.label: m.value for m in teste.metric}
    assert rotulos["Margem sobre o valor"] == "40,0%"
    # 40% de margem sobre o valor sao 66,7% de potencial sobre o preco.
    assert rotulos["Potencial sobre o preço"] == "66,7%"


def test_a_tela_separa_margem_de_potencial():
    """Os dois numeros medem a mesma distancia e sao confundidos o tempo todo."""
    teste = _rodar(TELA_MARGEM, preco=(500.0, False))
    texto = " ".join(c.value for c in teste.caption)
    assert "30% de margem" in texto and "42,9% de potencial" in texto


def test_preco_acima_do_valor_e_apontado_como_caro():
    teste = _rodar(TELA_MARGEM, preco=(2000.0, False))
    assert any("acima do valor" in e.value for e in teste.error)


def test_as_expectativas_implicitas_saem_na_tela():
    teste = _rodar(TELA_MARGEM, preco=(700.0, False))
    tabela = teste.session_state["expectativas_implicitas"]
    assert "Margem EBITDA" in tabela.index
    assert not tabela["Implícita no preço"].isna().all()

    texto = " ".join(m.value for m in teste.markdown)
    assert "premissa com menos folga" in texto


def test_o_preco_fica_guardado_para_as_outras_telas():
    teste = _rodar(TELA_MARGEM, preco=(600.0, False))
    guardado = teste.session_state["preco_pedido"]
    assert guardado["valor"] == pytest.approx(600.0)
    assert guardado["por_acao"] is False


# ---------------------------------------------------------------------------
# O relatorio
# ---------------------------------------------------------------------------


def test_o_relatorio_sai_da_tela_de_exportar():
    teste = _rodar(TELA_EXPORTAR)
    rotulos = [b.label for b in teste.get("download_button")]
    assert "Baixar o relatório (.md)" in rotulos

    texto = teste.session_state["relatorio"]
    assert texto.startswith("# ")
    assert "## O que este relatório não faz" in texto


def test_sem_preco_o_relatorio_avisa_o_que_falta():
    teste = _rodar(TELA_EXPORTAR)
    avisos = " ".join(i.value for i in teste.info)
    assert "preço de mercado" in avisos
    assert "histórico" in avisos


def test_com_preco_o_relatorio_traz_a_margem():
    teste = _rodar(TELA_EXPORTAR, preco=(700.0, False))
    texto = teste.session_state["relatorio"]
    assert "O que o preço embute" in texto
    assert "Implícita no preço" in texto
    assert "**Não avaliado** — nenhum preço" not in texto


# ---------------------------------------------------------------------------
# Pares por perfil economico
# ---------------------------------------------------------------------------

TELA_MULTIPLOS = CABECALHO + """
from app.paginas import multiplos
if st.session_state.get("dfs") is not None:
    estado.definir_demonstracoes(st.session_state["dfs"])
multiplos.render()
"""


def test_sem_universo_construido_a_tela_ensina_o_comando(monkeypatch, tmp_path):
    """Construir custa minutos: nao pode acontecer por abrir uma aba."""
    from valuation.importacao.cvm import importar_cvm
    from valuation import pares

    monkeypatch.setattr(pares, "diretorio_cache", lambda: tmp_path / "vazio")
    dfs = importar_cvm(5410, [2023, 2024], cache=Path(__file__).parent / "dados" / "cvm")

    teste = _rodar(TELA_MULTIPLOS, dfs=dfs)
    avisos = " ".join(i.value for i in teste.info)
    assert "universo de perfis ainda não foi construído" in avisos
    assert any("python -m valuation.pares" in c.value for c in teste.code)


def test_a_tela_avisa_que_perfil_parecido_nao_e_negocio_parecido(monkeypatch, tmp_path):
    """Uma concessionária de rodovia e um gasoduto sao gemeos no perfil."""
    import pandas as pd

    from valuation.importacao.cvm import importar_cvm
    from valuation import pares

    pasta = tmp_path / "universo"
    pasta.mkdir()
    perfis = pd.DataFrame(
        {
            "Margem EBITDA": [0.20, 0.19, 0.45],
            "ROIC": [0.30, 0.28, 0.09],
            "Giro do capital investido": [1.2, 1.3, 0.4],
            "Capex / Receita": [0.05, 0.06, 0.22],
            "Crescimento da receita": [0.15, 0.14, 0.04],
            "Divida liquida / EBITDA": [-0.5, -0.4, 3.4],
            "nome": ["Par A", "Par B", "Par C"],
            "receita": [3.5e10, 3.0e10, 2.8e10],
            "setor": ["Indústria"] * 3,
        },
        index=[101, 102, 103],
    )
    perfis.index.name = "codigo"
    perfis.to_csv(pasta / "perfis_2023_2024.csv", encoding="utf-8")
    monkeypatch.setattr(pares, "diretorio_cache", lambda: pasta)

    dfs = importar_cvm(5410, [2023, 2024], cache=Path(__file__).parent / "dados" / "cvm")
    teste = _rodar(TELA_MULTIPLOS, dfs=dfs)

    avisos = " ".join(w.value for w in teste.warning)
    assert "Perfil parecido não é negócio parecido" in avisos
    assert any("Dimensões" in list(d.value.columns) for d in teste.dataframe)

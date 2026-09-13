"""O WACC sugerido: beta do setor realavancado, teto de D/E e piso de Kd.

A sugestao gravava beta 1,0 com a D/E do setor igual a da companhia, e o beta
nunca era realavancado: a CSN, com 77% do capital em divida, saia com WACC de
6,4%. Medido nas 415 companhias de 2021-2025, 31 saiam fora de 7%-30%; com o beta
do setor do cadastro da CVM, teto de D/E 3 e piso de Kd 3%, sai uma.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from valuation.dados_setoriais import BETA_DESALAVANCADO_SEM_SETOR
from valuation.historico import (
    DIVIDA_PL_ALVO_MAXIMA,
    KD_MINIMO_PLAUSIVEL,
    analisar,
    sugerir_premissas,
)

DADOS = Path(__file__).parent / "dados" / "cvm"


@pytest.fixture(scope="module")
def weg():
    from valuation.importacao.cvm import carregar_cadastro, importar_cvm

    # **Com o catalogo, como o app faz.** Sem ele a importacao nao acha o
    # registro da companhia e o setor nao viaja na `fonte` -- e o teste mediria
    # a sugestao sem setor achando que media a com.
    catalogo = carregar_cadastro(DADOS / "cad_cia_aberta.csv")
    return importar_cvm(5410, [2024, 2025], cache=DADOS, catalogo=catalogo).escalar(
        1e6, "R$ milhões"
    )


def test_o_beta_vem_do_setor_do_cadastro(weg):
    assert weg.fonte.get("setor"), weg.fonte
    sugestao = sugerir_premissas(analisar(weg))
    cc = sugestao.custo_capital
    assert sugestao.setor == "Bens de capital"
    from valuation.dados_setoriais import POR_NOME

    assert cc.beta_desalavancado == pytest.approx(
        POR_NOME["Bens de capital"].beta_desalavancado
    )
    assert "Bens de capital" in sugestao.justificativas["custo_capital"]
    assert not any("marcador" in a for a in sugestao.alertas)


def test_sem_setor_traduzido_o_beta_e_a_mediana(weg):
    sem_setor = replace(weg, fonte={**weg.fonte, "setor": "Hospedagem e Turismo"})
    sugestao = sugerir_premissas(analisar(sem_setor))
    assert sugestao.setor is None
    assert sugestao.custo_capital.beta_desalavancado == pytest.approx(
        BETA_DESALAVANCADO_SEM_SETOR
    )
    assert any("Escolha o setor" in a for a in sugestao.alertas)


def test_divida_de_balanco_alta_tem_teto_e_kd_irrisorio_tem_piso(weg):
    """Dívida trinta vezes maior: D/E acima de 3 e o juro pago vira 0,1%.

    É o retrato da Simpar e da Marfrig na medição -- o juro existe, só não está
    na linha que o app divide pela dívida.
    """
    valores = weg.valores.copy()
    for conta in ("divida_curto_prazo", "divida_longo_prazo"):
        if conta in valores.index:
            valores.loc[conta] = valores.loc[conta] * 30
    alavancada = replace(weg, valores=valores)
    analise = analisar(alavancada)
    assert analise.ultimo("Divida bruta / Patrimonio liquido") > DIVIDA_PL_ALVO_MAXIMA

    sugestao = sugerir_premissas(analise)
    cc = sugestao.custo_capital
    assert cc.divida_pl_alvo == pytest.approx(DIVIDA_PL_ALVO_MAXIMA)
    assert any("estrutura-alvo" in a for a in sugestao.alertas)

    kd = analise.mediana("Custo da divida pelo caixa")
    assert kd < KD_MINIMO_PLAUSIVEL
    assert cc.custo_divida_brl is None
    assert any("abaixo de 3%" in a for a in sugestao.alertas)


def test_derivar_grava_o_setor_para_a_tela_de_custo_de_capital(weg):
    """Sem isto a caixa abriria em "(informar beta manualmente)" e o próximo
    "Aplicar" trocaria o beta do setor por 1,0."""
    pytest.importorskip("streamlit.testing.v1")
    from streamlit.testing.v1 import AppTest

    raiz = Path(__file__).resolve().parent.parent
    script = f"""
import sys
for caminho in ({str(raiz)!r}, {str(raiz / "src")!r}):
    if caminho not in sys.path:
        sys.path.insert(0, caminho)
import streamlit as st
from app import estado

estado.iniciar()
if st.session_state.get("dfs") is not None:
    estado.definir_demonstracoes(st.session_state.pop("dfs"))
    estado.derivar_premissas_do_historico()
st.session_state["setor_na_config"] = estado.config().get("setor")
"""
    teste = AppTest.from_string(script, default_timeout=120)
    teste.session_state["dfs"] = weg
    teste.run()
    assert not teste.exception, [str(e.value) for e in teste.exception]
    assert teste.session_state["setor_na_config"] == "Bens de capital"

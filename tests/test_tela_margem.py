"""Margem de seguranca na tela, e o relatorio que sai da exportacao.

O que so da para verificar com a tela rodando: que o preco informado numa tela
chega na outra (senao as duas discordam sem que nada acuse), e que o relatorio
sai completo quando as pecas existem e confessa a ausencia quando nao existem.
"""

from __future__ import annotations

import re
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



# A unidade passou a viajar no **rotulo** da metrica, e nao dentro do numero:
# "930,0 R$ milhoes" nao cabe na largura de um cartao e o Streamlit o corta em
# "930,0 R$ mil…". Os testes travam **que a metrica existe**, e nao como a
# unidade e escrita -- pinar a string inteira faz uma decisao de apresentacao
# virar regressao, que e o defeito que os literais de calibracao ja custaram.
_UNIDADE_NO_ROTULO = re.compile(r"\s*\((?:R\$|US\$)[^)]*\)$")


def _sem_unidade(rotulo: str) -> str:
    return _UNIDADE_NO_ROTULO.sub("", rotulo)

# ---------------------------------------------------------------------------
# A tela
# ---------------------------------------------------------------------------


def test_a_tela_abre_sem_preco_e_sem_placar():
    """O campo nasce **vazio**, e nao igual ao valor calculado.

    Preenchido com o numero do proprio DCF ele produzia margem de 0,0% e um
    "Preco pedido" no placar que se le como dado de mercado -- um usuario leu ali
    o valor de mercado da WEG e viu R$ 59,8 bi, que e o DCF do app e nao a bolsa.
    O app nao busca cotacao em lugar nenhum, e enquanto o numero nao vier de fora
    a tela nao deve mostrar comparacao nenhuma.
    """
    teste = _rodar(TELA_MARGEM)
    rotulos = {_sem_unidade(m.label) for m in teste.metric}
    assert "Margem sobre o valor" not in rotulos, "o placar apareceu sem preco"

    campos = [n.label for n in teste.number_input]
    assert any("Cotação" in r or "Valor de mercado" in r for r in campos), campos


def test_a_tela_diz_que_nao_busca_cotacao():
    """Numero que o app nao tem nao pode parecer numero que o app tem."""
    teste = _rodar(TELA_MARGEM)
    campo = next(
        n for n in teste.number_input
        if "Cotação" in n.label or "Valor de mercado" in n.label
    )
    assert "não busca cotação" in (campo.help or "")


def test_preco_abaixo_do_valor_da_margem_positiva():
    empresa_valor = 930.0  # equity value da empresa inicial do app
    teste = _rodar(TELA_MARGEM, preco=(empresa_valor * 0.6, False))
    rotulos = {_sem_unidade(m.label): m.value for m in teste.metric}
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


# ---------------------------------------------------------------------------
# O relatorio de instituicao financeira
# ---------------------------------------------------------------------------


def _banco_para_relatorio():
    import pandas as pd

    from valuation.importacao import Demonstracoes

    anos = [2021, 2022, 2023, 2024]
    return Demonstracoes(
        empresa="Banco Teste",
        unidade="R$ milhões",
        valores=pd.DataFrame(
            {
                "patrimonio_liquido": [1000.0, 1100.0, 1210.0, 1331.0],
                "lucro_liquido": [180.0, 198.0, 217.8, 239.6],
                "dividendos_pagos": [-80.0, -88.0, -96.8, -106.5],
                "receita_liquida": [900.0, 990.0, 1089.0, 1197.9],
                "ebit": [250.0, 275.0, 302.5, 332.8],
                "ativo_total": [9000.0, 9900.0, 10890.0, 11979.0],
            },
            index=anos,
        ).T,
        avisos=[
            "Esta companhia publica no plano de contas de instituicao financeira "
            "ou seguradora."
        ],
    )


def test_o_relatorio_do_banco_nao_descreve_um_dcf():
    """O relatório é o que sobra depois que a tela fecha.

    A tela de Valor recusou o DCF para esta companhia; descrever aqui um
    Enterprise Value, um WACC e uma ponte que ninguém calculou contradiria o
    número que o usuário viu.
    """
    teste = _rodar(TELA_EXPORTAR, dfs=_banco_para_relatorio())
    texto = teste.session_state["relatorio"]

    assert "## Valor, pelo lucro residual" in texto
    assert "Enterprise Value" not in texto
    assert "Do Enterprise Value ao Equity Value" not in texto
    assert "Peso da perpetuidade no valor" not in texto


def test_o_relatorio_do_banco_usa_os_indicadores_que_valem_nele():
    """Margem EBITDA e capex sobre receita não dizem nada num banco.

    A seção industrial mostrava margem EBITDA de −8,3% para o Bradesco, número
    que não descreve coisa alguma.
    """
    teste = _rodar(TELA_EXPORTAR, dfs=_banco_para_relatorio())
    texto = teste.session_state["relatorio"]

    assert "## O que a instituição entregou" in texto
    assert "ROE" in texto and "Payout" in texto
    # A margem EBITDA nao pode aparecer em lugar nenhum: nem na tabela do
    # historico, nem como percentil contra uma base que exclui bancos.
    assert "Margem EBITDA" not in texto


def test_o_relatorio_do_banco_declara_o_que_o_modelo_nao_faz():
    """Capital regulatório não é modelado, e o entregável precisa dizer."""
    teste = _rodar(TELA_EXPORTAR, dfs=_banco_para_relatorio())
    texto = teste.session_state["relatorio"]
    assert "capital regulatório" in texto
    assert "P/VP implícito" in texto


def test_o_relatorio_nao_diz_mais_que_os_cortes_sao_convencao():
    """Texto velho no entregável vira afirmação falsa sobre o próprio trabalho.

    Conversão de caixa, alavancagem, arrendamento e peso do não recorrente foram
    calibrados contra as 467 companhias com DFP consolidada.
    """
    teste = _rodar(TELA_EXPORTAR)
    texto = teste.session_state["relatorio"]
    assert "ainda não calibradas contra a base da CVM" not in texto
    assert "quartis medidos" in texto


def test_o_relatorio_do_banco_declara_o_que_deixou_de_fora():
    """Omitir em silêncio é pior que omitir dizendo.

    Duas seções descreviam outra companhia: o percentil contra pares — universo
    que **exclui bancos de propósito** — e o diagnóstico automático, que verifica
    a coerência de um DCF que não foi usado. Ele chegava a reclamar de "margem
    EBITDA projetada abaixo do pior ano histórico" num modelo que não projeta
    margem nenhuma.
    """
    teste = _rodar(TELA_EXPORTAR, dfs=_banco_para_relatorio())
    texto = teste.session_state["relatorio"]

    assert "## O que não foi avaliado aqui" in texto
    assert "exclui bancos" in texto
    assert "o DCF não foi usado" in texto
    # E as seções que descreviam outra companhia saíram de fato. A busca é pelo
    # percentil **com número** — a explicação acima usa a palavra de propósito.
    import re

    assert not re.search(r"no percentil \d", texto), texto
    assert "companhias brasileiras" not in texto
    # O cabeçalho da seção de riscos, e não a menção a ela no texto acima.
    assert "## O que pode dar errado" not in texto


def test_a_industria_continua_com_as_duas_secoes():
    """O corte só pode valer onde foi justificado."""
    teste = _rodar(TELA_EXPORTAR)
    texto = teste.session_state["relatorio"]
    assert "## O que não foi avaliado aqui" not in texto
    assert "## As perguntas que os números não respondem" in texto


def test_cotacao_informada_mostra_o_valor_de_mercado_implicito():
    """As acoes ja estao aqui, lidas da composicao de capital que a CVM publica.

    Quem digita a cotacao quer conferir o valor de mercado que ela implica --
    sem isto o usuario sai da tela para multiplicar, e foi assim que o numero de
    acoes nunca chegou a ser conferido contra o mercado. Na WEG: 4,196 bilhoes
    de acoes a R$ 49,29 dao os R$ 206,8 bi que a bolsa marca.
    """
    teste = _rodar(TELA_MARGEM, preco=(12.0, True))
    legendas = " ".join(c.value for c in teste.caption)
    assert "Valor de mercado implícito" in legendas
    assert "ações em circulação" in legendas

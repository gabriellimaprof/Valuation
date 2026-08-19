"""O cronograma de divida na tela de Valor.

O motor sempre soube calcular FCFE -- ``projetar(divida_por_ano=...)`` existe e
e testado. A tela oferecia a opcao "FCFE (para o acionista)" sem ter onde
informar o cronograma, entao escolher FCFE dava erro ou caia num FCFF disfarcado.
O que se verifica aqui e a ligacao: que o que o usuario digita na tela chega ao
motor e muda o numero.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("streamlit.testing.v1")
from streamlit.testing.v1 import AppTest  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent

SCRIPT = f"""
import sys
for caminho in ({str(RAIZ)!r}, {str(RAIZ / "src")!r}):
    if caminho not in sys.path:
        sys.path.insert(0, caminho)
import streamlit as st
from app import estado

estado.iniciar()
for chave, valor in (st.session_state.get("ajustes") or {{}}).items():
    estado.config()[chave] = valor

from app.paginas import valor
valor.render()
# As convencoes reais, para o teste conferir o que chega ao motor sem
# reimplementar a regra -- teste que copia a logica passa junto com o bug.
st.session_state["convencoes_vistas"] = estado.convencoes()
"""


def _rodar(**config) -> AppTest:
    teste = AppTest.from_string(SCRIPT, default_timeout=240)
    if config:
        teste.session_state["ajustes"] = config
    teste.run()
    assert not teste.exception, [str(e.value) for e in teste.exception]
    return teste


def test_a_tela_abre_no_fcff_sem_pedir_cronograma():
    """No FCFF a divida entra so na ponte; pedir cronograma ali seria ruido."""
    teste = _rodar()
    rotulos = [e.label for e in teste.expander]
    assert not any("Cronograma" in r for r in rotulos), rotulos


def test_escolher_fcfe_abre_o_cronograma():
    teste = _rodar(tipo_fluxo="fcfe")
    rotulos = [e.label for e in teste.expander]
    assert any("Cronograma da dívida" in r for r in rotulos), rotulos


def test_o_cronograma_nasce_com_divida_constante():
    """A hipotese que a maioria dos modelos assume sem dizer, dita.

    Com divida constante a variacao e zero e o FCFE fica abaixo do FCFF pelo
    juro depois de imposto -- que e o resultado certo, e nao um FCFF disfarcado.
    """
    teste = _rodar(tipo_fluxo="fcfe")
    empresa = teste.session_state["empresa"]
    anos = len(empresa.operacionais.crescimento_receita)
    inicial = float(empresa.ponte.divida_bruta)

    # A tela abriu sem erro, o que so acontece se o modelo fechou -- e no FCFE
    # ele so fecha com cronograma. Antes disto, escolher FCFE dava
    # "o modelo nao fecha" sem dizer o que faltava.
    assert not teste.error, [e.value for e in teste.error]

    # O ``data_editor`` nao e exposto pelo AppTest, entao a verificacao e sobre
    # o numero: o que a tela mostrou tem que ser o do cronograma constante.
    from valuation import avaliar

    constante = avaliar(empresa, tipo_fluxo="fcfe", divida_por_ano=[inicial] * anos)
    na_tela = next(m for m in teste.metric if m.label == "Equity Value")
    assert _numero(na_tela.value) == pytest.approx(constante.equity_value, rel=0.02)


def _numero(texto: str) -> float:
    """Desfaz a formatacao brasileira do cartao para poder comparar."""
    limpo = "".join(c for c in texto if c.isdigit() or c in ",-.")
    return float(limpo.replace(".", "").replace(",", "."))


def test_o_cronograma_chega_as_convencoes():
    """Premissa que a tela guarda e o motor ignora e premissa que nao existe."""
    from app import estado

    teste = _rodar(tipo_fluxo="fcfe", divida_por_ano=[10.0, 20.0, 30.0, 40.0, 50.0])
    convencoes = teste.session_state["config"]
    assert convencoes["divida_por_ano"] == [10.0, 20.0, 30.0, 40.0, 50.0]


def test_no_fcff_o_cronograma_nao_viaja():
    """Premissa invisivel e a que ninguem confere.

    O cronograma nao muda o FCFF, mas mandado junto faria a sensibilidade e os
    cenarios carregarem uma premissa que a tela nao mostra naquele modo.
    """
    teste = _rodar(tipo_fluxo="fcff", divida_por_ano=[10.0] * 5)
    assert "divida_por_ano" not in teste.session_state["convencoes_vistas"]


def test_no_fcfe_o_cronograma_viaja_com_as_demais_convencoes():
    """Sensibilidade e cenarios tem que rodar sob o mesmo cronograma do caso base.

    Se o cenario "base" nao reproduz o numero principal, o modelo perde
    credibilidade na primeira conferencia.
    """
    teste = _rodar(tipo_fluxo="fcfe", divida_por_ano=[50.0, 40.0, 30.0, 20.0, 10.0])
    convencoes = teste.session_state["convencoes_vistas"]
    assert convencoes["divida_por_ano"] == [50.0, 40.0, 30.0, 20.0, 10.0]
    assert convencoes["tipo_fluxo"] == "fcfe"


def test_sem_cronograma_o_fcfe_ganha_divida_constante():
    """Sem isto, escolher FCFE respondia "o modelo nao fecha" e nada mais."""
    teste = _rodar(tipo_fluxo="fcfe")
    empresa = teste.session_state["empresa"]
    esperado = [float(empresa.ponte.divida_bruta)] * len(
        empresa.operacionais.crescimento_receita
    )
    assert teste.session_state["convencoes_vistas"]["divida_por_ano"] == esperado


def test_o_fcfe_sai_diferente_do_fcff():
    """Se os dois derem o mesmo numero, o cronograma nao chegou ao motor."""
    from valuation import avaliar
    from valuation.premissas import Empresa

    fcff = _rodar()
    empresa: Empresa = fcff.session_state["empresa"]
    divida = float(empresa.ponte.divida_bruta)
    anos = len(empresa.operacionais.crescimento_receita)

    sem = avaliar(empresa, tipo_fluxo="fcff")
    com = avaliar(
        empresa, tipo_fluxo="fcfe", divida_por_ano=[divida] * anos
    )
    assert com.equity_value != pytest.approx(sem.equity_value)


def test_amortizar_muda_o_valor_do_acionista():
    """Amortizar consome caixa do acionista nos anos de pagamento."""
    from valuation import avaliar

    empresa = _rodar().session_state["empresa"]
    divida = float(empresa.ponte.divida_bruta)
    anos = len(empresa.operacionais.crescimento_receita)

    constante = avaliar(
        empresa, tipo_fluxo="fcfe", divida_por_ano=[divida] * anos
    )
    passo = divida / anos
    amortizando = avaliar(
        empresa,
        tipo_fluxo="fcfe",
        divida_por_ano=[max(divida - passo * (i + 1), 0.0) for i in range(anos)],
    )
    assert amortizando.equity_value != pytest.approx(constante.equity_value)

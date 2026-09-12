"""Um passo atras nas premissas, porque perde-las era irreversivel.

Um usuario relatou ter clicado num botao em Premissas e visto o que tinha
montado voltar ao sugerido. **Seis mecanismos foram medidos atras disso e
nenhum reproduziu** -- "Aplicar perpetuidade" nao move um unico dos 50 campos da
`Empresa`, nem em modelo derivado nem em customizado; navegar para outra tela e
voltar preserva; o slider de horizonte estica a lista sem reescrever o que ja
havia; premissas operacionais postas a mao sobrevivem.

O caminho, portanto, continua aberto. Enquanto ele nao aparece, o que da para
garantir e que a perda seja **desfazivel** -- um passo atras vale mais que um
diagnostico que ainda nao existe. E remontar a mao um horizonte inteiro de
direcionadores e o tipo de trabalho que faz o analista desistir da ferramenta.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

pytest.importorskip("streamlit.testing.v1")
from streamlit.testing.v1 import AppTest  # noqa: E402


SCRIPT = """
import streamlit as st
from app import estado

estado.iniciar()
pedido = st.session_state.get("pedido")
if pedido == "mudar":
    estado.atualizar({"perpetuidade.crescimento_perpetuo": 0.031})
elif pedido == "mudar_de_novo":
    estado.atualizar({"perpetuidade.crescimento_perpetuo": 0.022})
elif pedido == "desfazer":
    st.session_state["houve"] = estado.desfazer()
elif pedido == "mesmo_valor":
    estado.definir_empresa(estado.empresa())
st.session_state["pedido"] = None
st.session_state["g"] = estado.empresa().perpetuidade.crescimento_perpetuo
st.session_state["pode"] = estado.pode_desfazer()
"""


def _app() -> AppTest:
    teste = AppTest.from_string(SCRIPT, default_timeout=60)
    teste.run()
    assert not teste.exception, [str(e.value) for e in teste.exception]
    return teste


def _pedir(teste: AppTest, pedido: str) -> AppTest:
    teste.session_state["pedido"] = pedido
    teste.run()
    assert not teste.exception, [str(e.value) for e in teste.exception]
    return teste


def test_sem_mudanca_nao_ha_o_que_desfazer():
    """Botão de desfazer numa sessão recém-aberta prometeria o que não tem."""
    teste = _app()
    assert not teste.session_state["pode"]


def test_um_passo_atras_devolve_a_premissa_anterior():
    teste = _app()
    original = teste.session_state["g"]

    _pedir(teste, "mudar")
    assert teste.session_state["g"] == pytest.approx(0.031)
    assert teste.session_state["pode"]

    _pedir(teste, "desfazer")
    assert teste.session_state["houve"]
    assert teste.session_state["g"] == pytest.approx(original)


def test_desfazer_anda_um_passo_por_vez():
    """Dois cliques desfazem duas mudanças, e não voltam tudo de uma vez."""
    teste = _app()
    original = teste.session_state["g"]

    _pedir(teste, "mudar")
    _pedir(teste, "mudar_de_novo")
    assert teste.session_state["g"] == pytest.approx(0.022)

    _pedir(teste, "desfazer")
    assert teste.session_state["g"] == pytest.approx(0.031)

    _pedir(teste, "desfazer")
    assert teste.session_state["g"] == pytest.approx(original)

    # E acabou: nao ha o que desfazer alem do estado inicial.
    assert not teste.session_state["pode"]


def test_gravar_o_mesmo_valor_nao_enche_o_historico():
    """**Rerun reescreve o mesmo objeto**, e sem guarda o desfazer não anda.

    O Streamlit reexecuta o script inteiro a cada interação, e várias telas
    regravam a empresa sem mudá-la. Contando esses passos, o histórico encheria
    de estados idênticos e "desfazer" viraria um botão que não faz nada visível.
    """
    teste = _app()
    for _ in range(5):
        _pedir(teste, "mesmo_valor")
    assert not teste.session_state["pode"]


def test_o_historico_tem_teto():
    """Cada passo é uma `Empresa` inteira, e a sessão vive na memória do servidor.

    Sem teto, um analista que passa a tarde ajustando premissas acumula centenas
    de cópias — vazamento lento num servidor compartilhado.
    """
    from app.estado import CHAVE_HISTORICO, PASSOS_GUARDADOS

    teste = _app()
    for i in range(PASSOS_GUARDADOS + 8):
        teste.session_state["pedido"] = "mudar"
        # Um valor diferente a cada volta, senao a guarda de igualdade barra.
        teste.run()
        teste.session_state["pedido"] = "mudar_de_novo"
        teste.run()

    assert len(teste.session_state[CHAVE_HISTORICO]) <= PASSOS_GUARDADOS


TELA = """
import sys
for caminho in (RAIZ, SRC):
    if caminho not in sys.path:
        sys.path.insert(0, caminho)
import streamlit as st
from app import estado
from app.paginas import premissas

estado.iniciar()
if st.session_state.get("mudar"):
    estado.atualizar({"perpetuidade.crescimento_perpetuo": 0.031})
    st.session_state["mudar"] = False
premissas.render()
"""


def _tela(mudar: bool) -> AppTest:
    from pathlib import Path

    raiz = Path(__file__).resolve().parent.parent
    script = (
        TELA.replace("RAIZ", repr(str(raiz))).replace("SRC", repr(str(raiz / "src")))
    )
    teste = AppTest.from_string(script, default_timeout=90)
    teste.session_state["mudar"] = mudar
    teste.run()
    assert not teste.exception, [str(e.value) for e in teste.exception]
    return teste


def test_a_tela_de_premissas_oferece_o_desfazer():
    """O botão aparece **só quando há o que desfazer**.

    Um desfazer sempre visível numa sessão recém-aberta promete o que não tem —
    e o custo de descobrir isso é justamente no momento em que se precisa dele.
    """
    sem_mudanca = [b.label for b in _tela(mudar=False).button]
    assert not any("Desfazer" in r for r in sem_mudanca), sem_mudanca

    com_mudanca = [b.label for b in _tela(mudar=True).button]
    assert any("Desfazer" in r for r in com_mudanca), com_mudanca


def test_o_botao_desfazer_devolve_a_premissa():
    """O laço inteiro pela tela, e não só pelo estado."""
    teste = _tela(mudar=True)
    alvo = [b for b in teste.button if "Desfazer" in b.label]
    assert alvo

    from app.estado import CHAVE_EMPRESA

    antes = teste.session_state[CHAVE_EMPRESA].perpetuidade.crescimento_perpetuo
    assert antes == pytest.approx(0.031)

    alvo[0].click().run()
    assert not teste.exception, [str(e.value) for e in teste.exception]
    depois = teste.session_state[CHAVE_EMPRESA].perpetuidade.crescimento_perpetuo
    assert depois != pytest.approx(0.031)

"""Tela de diagnostico: o app criticando o modelo antes de voce defender o numero."""

from __future__ import annotations

import streamlit as st

from valuation.diagnostico import ALERTA, ERRO, INFORMACAO

from .. import estado
from ..componentes import aviso_sem_modelo, barra_de_severidade, etapa

CORES = {ERRO: "🔴", ALERTA: "🟡", INFORMACAO: "🔵"}
TITULOS = {
    ERRO: "Erros — o modelo não deveria ser usado assim",
    ALERTA: "Alertas — premissas que precisam de justificativa",
    INFORMACAO: "Observações — vale conferir",
}


def render() -> None:
    etapa(
        "Passo 9",
        "Diagnóstico",
        "Verificações de consistência que um revisor experiente faria",
    )

    diagnostico = estado.diagnostico()
    if diagnostico is None:
        aviso_sem_modelo(estado.erro_do_modelo())
        return

    st.markdown(
        "Um DCF sempre devolve um número. O número ser **defensável** depende de "
        "coisas que a aritmética não verifica. Cada achado abaixo diz o que foi "
        "encontrado, por que aquilo importa para o valor e o que fazer a respeito."
    )

    barra_de_severidade(
        len(diagnostico.por_severidade(ERRO)),
        len(diagnostico.por_severidade(ALERTA)),
        len(diagnostico.por_severidade(INFORMACAO)),
    )

    if not estado.tem_historico():
        st.info(
            "Sem demonstrações importadas, as comparações contra o histórico da própria "
            "empresa ficam desligadas — e elas são as mais úteis. Importe as DFs em "
            "**Dados** para habilitá-las."
        )

    if len(diagnostico) == 0:
        st.success(
            "Nenhum achado. O modelo passou nas verificações de consistência — o que "
            "não substitui julgamento sobre as premissas em si."
        )
        return

    st.divider()

    for severidade in (ERRO, ALERTA, INFORMACAO):
        achados = diagnostico.por_severidade(severidade)
        if not achados:
            continue
        st.subheader(f"{CORES[severidade]} {TITULOS[severidade]}")
        for achado in achados:
            with st.container(border=True):
                st.markdown(f"**{achado.titulo}**")
                st.markdown(achado.detalhe)
                if achado.acao:
                    st.markdown(f"**O que fazer:** {achado.acao}")
                if achado.referencia:
                    st.caption(f"Referência: {achado.referencia}")

    st.divider()
    with st.expander("Ver como tabela (para colar no material)"):
        st.dataframe(diagnostico.tabela(), width="stretch")

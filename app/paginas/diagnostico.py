"""Tela de diagnostico: o app criticando o modelo antes de voce defender o numero."""

from __future__ import annotations

import streamlit as st

from valuation.diagnostico import ALERTA, ERRO, INFORMACAO

from valuation.formulas import rotulo_do_indicador

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

    # **Antes do "nenhum achado".** Numa série trimestral parte das verificações
    # não roda, e uma lista curta se lê como aprovação — "sem achado" e "não
    # verificado" não são a mesma coisa. É a mesma distinção que o aviso logo
    # acima já faz para quem não importou demonstração nenhuma.
    if diagnostico.omitidas:
        st.warning(
            "**{n} verificações não rodaram**, porque a série importada é de "
            "trimestres isolados e elas confrontam a premissa — que é de um "
            "exercício — com o histórico da companhia. Num trimestre, um "
            "indicador que mistura fluxo com estoque sai a um quarto, e o achado "
            "**inverte de sinal**. Ficaram de fora: {quais}.".format(
                n=len(diagnostico.omitidas),
                quais=", ".join(rotulo_do_indicador(i) for i in diagnostico.omitidas),
            )
        )
        st.caption(
            "Para habilitá-las, importe em **Ano móvel rolante** — doze meses "
            "encerrados em cada trimestre — ou em **Anual**."
        )

    if len(diagnostico) == 0:
        # **"Passou" e "não foi testado" não são a mesma coisa**, e o verde da
        # aprovação logo abaixo de "7 verificações não rodaram" se contradiz na
        # mesma tela. Visto no navegador: nenhum teste pegaria, porque as duas
        # peças estão certas em separado.
        if diagnostico.omitidas:
            st.info(
                "**Nenhum achado entre as verificações que rodaram.** As que "
                "ficaram de fora estão listadas acima — o modelo não foi "
                "reprovado por elas, mas também não foi aprovado."
            )
        else:
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

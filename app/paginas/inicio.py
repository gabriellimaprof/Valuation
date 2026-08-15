"""Tela inicial: o que o app faz e onde a empresa esta no fluxo."""

from __future__ import annotations

import streamlit as st

from .. import estado
from ..componentes import etapa, formatar
from ..textos import AVISO_FINAL, BOAS_VINDAS, PASSOS


def render() -> None:
    etapa("Começo", "Valuation de empresas", "Do histórico ao modelo em Excel")
    st.markdown(BOAS_VINDAS)

    empresa = estado.empresa()
    resultado = estado.resultado()

    st.divider()
    st.subheader("Onde você está")

    colunas = st.columns(4)
    colunas[0].metric("Empresa", empresa.nome)
    colunas[1].metric(
        "Histórico importado",
        f"{len(estado.demonstracoes().anos)} anos" if estado.tem_historico() else "não",
    )
    colunas[2].metric(
        "Horizonte projetado",
        f"{empresa.operacionais.horizonte} anos" if empresa.operacionais else "—",
    )
    if resultado is not None:
        colunas[3].metric(
            "Equity Value",
            formatar(resultado.equity_value, "moeda", empresa.unidade),
        )
    else:
        colunas[3].metric("Equity Value", "—")

    st.divider()
    st.subheader("O caminho completo")
    st.caption(
        "Você não precisa seguir na ordem — mas se está começando, ela é a mais "
        "produtiva."
    )

    for indice, (nome, resumo, detalhe) in enumerate(PASSOS, start=1):
        with st.container(border=True):
            colunas = st.columns([1, 12])
            colunas[0].markdown(f"### {indice}")
            colunas[1].markdown(f"**{nome} — {resumo}**  \n{detalhe}")

    st.divider()
    st.caption(AVISO_FINAL)

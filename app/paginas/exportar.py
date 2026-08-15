"""Tela de exportacao: modelo em Excel com formulas vivas e premissas em YAML."""

from __future__ import annotations

import tempfile
from dataclasses import asdict
from pathlib import Path

import streamlit as st
import yaml

from valuation import exportar_excel

from .. import estado
from ..componentes import aviso_sem_modelo, etapa

MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def render() -> None:
    etapa("Passo 10", "Exportar", "Leve o modelo para o Excel, ou salve as premissas")

    resultado = estado.resultado()
    if resultado is None:
        aviso_sem_modelo(estado.erro_do_modelo())
        return

    st.markdown(
        "As abas **Premissas**, **Custo de Capital**, **Projeção** e **DCF** saem com "
        "fórmulas do Excel de verdade, não com valores colados. Quem receber o arquivo "
        "muda uma premissa e o modelo inteiro recalcula, e um revisor rastreia cada "
        "número até a origem."
    )
    st.caption(
        "Convenção de cores da planilha: azul é premissa editável, preto é fórmula da "
        "própria aba, verde é referência a outra aba."
    )

    st.divider()
    st.subheader("O que incluir")
    colunas = st.columns(3)
    incluir_sensibilidade = colunas[0].checkbox(
        "Tabela de sensibilidade",
        value="tabela_sensibilidade" in st.session_state,
        disabled="tabela_sensibilidade" not in st.session_state,
        help="Gere a tabela na tela de Sensibilidade para habilitar.",
    )
    incluir_cenarios = colunas[1].checkbox(
        "Cenários",
        value="tabela_cenarios" in st.session_state,
        disabled="tabela_cenarios" not in st.session_state,
    )
    incluir_simulacao = colunas[2].checkbox(
        "Monte Carlo",
        value="simulacao" in st.session_state,
        disabled="simulacao" not in st.session_state,
        help="Rode a simulação na tela de Sensibilidade para habilitar.",
    )

    if "decomposicao_tsr" in st.session_state:
        st.caption(
            "A decomposição do TSR entra como aba própria, também com fórmulas vivas."
        )
    else:
        st.caption(
            "Passe pela tela de **Retorno esperado** para que o TSR entre na planilha."
        )

    comparaveis = estado.comparaveis()
    if comparaveis:
        st.caption(f"{len(comparaveis)} comparável(is) serão incluídos na aba de múltiplos.")

    st.divider()
    if st.button("Gerar planilha", type="primary"):
        _gerar(
            resultado,
            incluir_sensibilidade,
            incluir_cenarios,
            incluir_simulacao,
        )

    if "excel_gerado" in st.session_state:
        caminho = Path(st.session_state["excel_gerado"])
        if caminho.exists():
            st.download_button(
                "Baixar modelo em Excel",
                data=caminho.read_bytes(),
                file_name=f"valuation_{_slug(estado.empresa().nome)}.xlsx",
                mime=MIME_XLSX,
                type="primary",
            )

    st.divider()
    _salvar_projeto()


def _gerar(resultado, sensibilidade: bool, cenarios: bool, simulacao: bool) -> None:
    from valuation.multiplos import Alvo

    destino = Path(tempfile.gettempdir()) / "valuation_modelo.xlsx"
    comparaveis = estado.comparaveis()

    alvo = None
    if comparaveis:
        from .multiplos import _alvo_atual

        alvo = _alvo_atual()

    try:
        exportar_excel(
            resultado,
            destino,
            sensibilidade=st.session_state.get("tabela_sensibilidade") if sensibilidade else None,
            cenarios=st.session_state.get("tabela_cenarios") if cenarios else None,
            simulacao=st.session_state.get("simulacao") if simulacao else None,
            comparaveis=comparaveis or None,
            alvo=alvo,
            retorno=st.session_state.get("decomposicao_tsr"),
            acionista=st.session_state.get("projecao_acionista"),
        )
    except Exception as erro:  # noqa: BLE001 - queremos mostrar a causa ao usuario
        st.error(f"Não consegui gerar a planilha: {erro}")
        return

    st.session_state["excel_gerado"] = str(destino)
    st.success("Planilha gerada. Use o botão abaixo para baixar.")
    st.rerun()


def _salvar_projeto() -> None:
    """Baixa o valuation inteiro como arquivo de texto, para retomar depois."""
    from valuation.projeto import serializar

    st.subheader("Salvar este valuation")
    st.markdown(
        "Baixa **tudo** num arquivo só: premissas, demonstrações importadas, "
        "comparáveis e as convenções de cálculo. Para retomar, suba o arquivo em "
        "**Dados → Retomar valuation salvo**."
    )
    st.caption(
        "É YAML de propósito: dá para abrir num editor, versionar em Git, revisar "
        "em pull request e comparar duas versões de um mesmo valuation com um diff."
    )

    try:
        texto = serializar(estado.projeto_atual())
    except Exception as erro:  # noqa: BLE001 - o usuario precisa saber a causa
        st.error(f"Não consegui montar o arquivo: {erro}")
        return

    nome = f"{_slug(estado.empresa().nome)}.yaml"
    st.download_button(
        "Baixar o valuation (.yaml)",
        data=texto.encode("utf-8"),
        file_name=nome,
        mime="text/yaml",
        type="primary",
    )
    tamanho = len(texto.encode("utf-8")) / 1024
    st.caption(
        f"{nome} · {tamanho:,.0f} KB · também aceito pela linha de comando: "
        f"`valuation dcf {nome} --excel modelo.xlsx`".replace(",", ".")
    )

    with st.expander("Ver o conteúdo do arquivo"):
        st.code(texto, language="yaml")


def _slug(nome: str) -> str:
    from valuation.importacao import normalizar

    return normalizar(nome).replace(" ", "_") or "empresa"

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
    etapa("Passo 9", "Exportar", "Leve o modelo para o Excel, ou salve as premissas")

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
    _premissas_em_texto()


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
        )
    except Exception as erro:  # noqa: BLE001 - queremos mostrar a causa ao usuario
        st.error(f"Não consegui gerar a planilha: {erro}")
        return

    st.session_state["excel_gerado"] = str(destino)
    st.success("Planilha gerada. Use o botão abaixo para baixar.")
    st.rerun()


def _premissas_em_texto() -> None:
    st.subheader("Premissas em YAML")
    st.markdown(
        "O mesmo modelo como arquivo de texto: dá para versionar em Git, revisar em "
        "pull request, comparar duas versões de um valuation e reproduzir o número "
        "meses depois. É também o formato aceito pela linha de comando."
    )

    empresa = estado.empresa()
    dados = {
        "nome": empresa.nome,
        "data_base": empresa.data_base or "",
        "moeda": empresa.moeda,
        "unidade": empresa.unidade,
        "prejuizo_fiscal_acumulado": empresa.prejuizo_fiscal_acumulado,
        "macro": asdict(empresa.macro),
        "custo_capital": asdict(empresa.custo_capital),
        "operacionais": asdict(empresa.operacionais) if empresa.operacionais else None,
        "perpetuidade": asdict(empresa.perpetuidade),
        "ponte": asdict(empresa.ponte),
    }
    texto = yaml.safe_dump(dados, allow_unicode=True, sort_keys=False, default_flow_style=False)

    st.code(texto, language="yaml")
    st.download_button(
        "Baixar premissas (.yaml)",
        data=texto.encode("utf-8"),
        file_name=f"{_slug(empresa.nome)}.yaml",
        mime="text/yaml",
    )
    st.caption(
        f"Depois, na linha de comando: `valuation dcf {_slug(empresa.nome)}.yaml "
        "--excel modelo.xlsx`"
    )


def _slug(nome: str) -> str:
    from valuation.importacao import normalizar

    return normalizar(nome).replace(" ", "_") or "empresa"

"""Tela de exportacao: modelo em Excel com formulas vivas e premissas em YAML."""

from __future__ import annotations

import tempfile
from dataclasses import asdict
from pathlib import Path

import streamlit as st
import yaml

from valuation import biblioteca, exportar_excel

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
    _relatorio(resultado)

    st.divider()
    _salvar_projeto()


def _relatorio(resultado) -> None:
    """O relatorio estruturado: tudo que o app apurou, num documento so."""
    from valuation.margem import expectativas_implicitas, margem_de_seguranca, valor_de_referencia
    from valuation.qualidade import avaliar_qualidade
    from valuation.relatorio import montar, sumario

    st.subheader("Relatório estruturado")
    st.markdown(
        "Reúne num documento só o que a empresa entregou, o que o modelo assume, "
        "quanto vale, o que o preço embute e o que pode dar errado — com a seção "
        "final dizendo o que **não** foi verificado. É a primeira camada do "
        "trabalho, a que consome horas e não exige julgamento."
    )
    st.caption(
        "Markdown de propósito: rodar de novo daqui a três meses e comparar com um "
        "diff mostra exatamente o que mudou no raciocínio. Um PDF novo só mostra "
        "que mudou alguma coisa."
    )

    analise = estado.analise()
    diagnostico = estado.diagnostico()
    qualidade = None
    if analise is not None:
        try:
            qualidade = avaliar_qualidade(analise)
        except ValueError:
            qualidade = None

    margem = expectativas = None
    guardado = estado.preco()
    if guardado:
        try:
            valor, chave = valor_de_referencia(resultado, bool(guardado["por_acao"]))
            margem = margem_de_seguranca(valor, float(guardado["valor"]))
            expectativas = expectativas_implicitas(
                estado.empresa(), float(guardado["valor"]), metrica=chave,
                **estado.convencoes(),
            )
        except ValueError:
            margem = expectativas = None

    faltando = []
    if analise is None:
        faltando.append("histórico (importe em **Dados**)")
    if guardado is None:
        faltando.append("preço de mercado (informe em **Margem de segurança**)")
    if faltando:
        st.info(
            "O relatório sai assim mesmo, dizendo o que faltou. Para ficar completo: "
            + "; ".join(faltando)
            + "."
        )

    with st.spinner("Montando o relatório..."):
        texto = montar(
            resultado,
            analise=analise,
            qualidade=qualidade,
            diagnostico=diagnostico,
            margem=margem,
            expectativas=expectativas,
        )

    st.session_state["relatorio"] = texto
    st.caption(sumario(diagnostico))

    st.download_button(
        "Baixar o relatório (.md)",
        data=texto.encode("utf-8"),
        file_name=f"relatorio_{_slug(estado.empresa().nome)}.md",
        mime="text/markdown",
        type="primary",
    )

    with st.expander("Ver o relatório"):
        st.markdown(texto)


def _gerar(resultado, sensibilidade: bool, cenarios: bool, simulacao: bool) -> None:
    from valuation.multiplos import Alvo

    destino = estado.pasta_temporaria() / "valuation_modelo.xlsx"
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
    colunas = st.columns(2)
    with colunas[0]:
        st.download_button(
            "Baixar o valuation (.yaml)",
            data=texto.encode("utf-8"),
            file_name=nome,
            mime="text/yaml",
            type="primary",
        )
    with colunas[1]:
        _guardar_na_biblioteca()
    tamanho = len(texto.encode("utf-8")) / 1024
    st.caption(
        f"{nome} · {tamanho:,.0f} KB · também aceito pela linha de comando: "
        f"`valuation dcf {nome} --excel modelo.xlsx`".replace(",", ".")
    )

    with st.expander("Ver o conteúdo do arquivo"):
        st.code(texto, language="yaml")


def _guardar_na_biblioteca() -> None:
    """Grava direto na pasta local, quando a biblioteca esta ligada.

    So aparece com ``VALUATION_BIBLIOTECA`` definida. Sem ela o app nao tem para
    onde gravar, e o botao nao existe -- em vez de existir e falhar.
    """
    if not biblioteca.esta_ligada():
        return

    if st.button("Guardar na biblioteca", type="secondary"):
        try:
            caminho = biblioteca.guardar(estado.projeto_atual())
        except (OSError, biblioteca.BibliotecaDesligada) as erro:
            st.error(f"Não consegui guardar: {erro}")
            return
        st.success(f"Guardado em `{caminho}`.")
    st.caption(f"Pasta: `{biblioteca.diretorio()}`")


def _slug(nome: str) -> str:
    from valuation.importacao import normalizar

    return normalizar(nome).replace(" ", "_") or "empresa"

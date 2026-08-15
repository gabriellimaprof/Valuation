"""Tela de dados: importar demonstracoes, conferir o que foi reconhecido e corrigir."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

from valuation.historico import sugerir_premissas
from valuation.importacao import (
    CONTAS,
    POR_CHAVE,
    aplicar_mapeamento_manual,
    gerar_template,
    importar,
)

from .. import estado
from ..componentes import etapa, tabela_formatada

ESCALAS = {
    "Os valores já estão na unidade que quero usar": (1, None),
    "Estão em unidades (R$ 1) e quero R$ milhões": (1_000_000, "R$ milhões"),
    "Estão em milhares (R$ mil) e quero R$ milhões": (1_000, "R$ milhões"),
    "Estão em milhares (R$ mil) e quero manter R$ mil": (1, "R$ mil"),
}


def render() -> None:
    etapa(
        "Passo 1",
        "Dados da empresa",
        "Importe as demonstrações financeiras ou preencha o essencial à mão",
    )

    aba_importar, aba_template, aba_manual = st.tabs(
        ["Importar planilha", "Baixar template", "Preencher à mão"]
    )

    with aba_importar:
        _importar()
    with aba_template:
        _template()
    with aba_manual:
        _manual()


def _importar() -> None:
    st.markdown(
        "Aceita export da **CVM/B3**, de **terminal** (Economatica, Bloomberg, "
        "Capital IQ), o **template do app** ou qualquer planilha com anos nas "
        "colunas e contas nas linhas. O app procura sozinho onde está o cabeçalho, "
        "reconhece as contas pelo código ou pelo nome e padroniza os sinais."
    )

    arquivo = st.file_uploader(
        "Planilha de demonstrações financeiras",
        type=["xlsx", "xls", "csv", "tsv"],
        key="upload_dfs",
    )
    colunas = st.columns([2, 1, 1])
    nome_empresa = colunas[0].text_input("Nome da empresa", value=estado.empresa().nome)
    anos_maximos = colunas[1].number_input(
        "Anos a considerar", min_value=2, max_value=20, value=6,
        help="Mantém apenas os anos mais recentes do arquivo.",
    )
    escala_escolhida = colunas[2].selectbox("Escala dos valores", list(ESCALAS))

    if arquivo is None:
        st.info("Envie um arquivo para começar, ou use as outras abas.")
        _mostrar_importacao_atual()
        return

    if st.button("Importar", type="primary"):
        _processar(arquivo, nome_empresa, int(anos_maximos), escala_escolhida)

    _mostrar_importacao_atual()


def _processar(arquivo, nome_empresa: str, anos_maximos: int, escala: str) -> None:
    destino = Path(tempfile.gettempdir()) / f"valuation_{arquivo.name}"
    destino.write_bytes(arquivo.getbuffer())

    try:
        dfs = importar(
            destino,
            empresa=nome_empresa or arquivo.name,
            anos_maximos=anos_maximos,
        )
    except (ValueError, FileNotFoundError) as erro:
        st.error(f"Não consegui importar: {erro}")
        return

    divisor, nova_unidade = ESCALAS[escala]
    if divisor != 1:
        dfs = dfs.escalar(divisor, nova_unidade)
    elif nova_unidade:
        dfs = type(dfs)(**{**dfs.__dict__, "unidade": nova_unidade})

    estado.definir_demonstracoes(dfs)
    st.session_state["arquivo_importado"] = str(destino)
    st.success(
        f"Importado: {len(dfs.valores.index)} contas em {len(dfs.anos)} anos "
        f"({dfs.anos[0]}–{dfs.anos[-1]})."
    )
    st.rerun()


def _mostrar_importacao_atual() -> None:
    dfs = estado.demonstracoes()
    if dfs is None:
        return

    st.divider()
    st.subheader(f"{dfs.empresa} — {dfs.anos[0]} a {dfs.anos[-1]}")
    st.caption(f"Valores em {dfs.unidade}. Origem: {dfs.origem or 'entrada manual'}.")

    for aviso in dfs.avisos:
        st.warning(aviso)

    aba_dre, aba_bp, aba_dfc, aba_conferencia = st.tabs(
        ["Resultado", "Balanço", "Fluxo de caixa", "O que o app entendeu"]
    )
    for aba, chave in ((aba_dre, "dre"), (aba_bp, "bp"), (aba_dfc, "dfc")):
        with aba:
            tabela = dfs.tabela(chave)
            if tabela.empty:
                st.info("Nenhuma conta desta demonstração foi encontrada no arquivo.")
            else:
                st.dataframe(
                    tabela_formatada(tabela, "moeda"), width="stretch"
                )

    with aba_conferencia:
        _conferencia(dfs)

    st.divider()
    if st.button("Usar este histórico para sugerir as premissas", type="primary"):
        _aplicar_sugestao(dfs)


def _conferencia(dfs) -> None:
    """Tela de auditoria da importacao: o que casou, o que foi derivado, o que sobrou."""
    st.markdown("**Contas reconhecidas**")
    st.caption("Cada conta canônica e a linha da planilha de onde ela veio.")
    if dfs.mapeamento:
        st.dataframe(
            pd.DataFrame(
                [
                    {"Conta": POR_CHAVE[k].rotulo, "Linha original": v}
                    for k, v in dfs.mapeamento.items()
                ]
            ).set_index("Conta"),
            width="stretch",
        )

    if dfs.derivadas:
        st.markdown("**Contas calculadas**")
        st.caption("Não vieram no arquivo; o app deduziu a partir das outras.")
        st.dataframe(
            pd.DataFrame(
                [
                    {"Conta": POR_CHAVE[k].rotulo, "Como foi obtida": v}
                    for k, v in dfs.derivadas.items()
                ]
            ).set_index("Conta"),
            width="stretch",
        )

    if not dfs.nao_reconhecidas:
        st.success("Todas as linhas da planilha foram classificadas.")
        return

    st.markdown("**Linhas que o app não reconheceu**")
    st.caption(
        "Nada foi descartado em silêncio. Se alguma delas é uma conta que o modelo "
        "usa, aponte aqui qual é."
    )

    opcoes = ["(ignorar)"] + [c.rotulo for c in CONTAS]
    rotulo_para_chave = {c.rotulo: c.chave for c in CONTAS}
    escolhas: dict[str, str] = {}

    for indice, linha in enumerate(dfs.nao_reconhecidas[:40]):
        colunas = st.columns([3, 2])
        colunas[0].text(linha.rotulo)
        escolha = colunas[1].selectbox(
            "conta", opcoes, key=f"mapa_{indice}", label_visibility="collapsed"
        )
        if escolha != "(ignorar)":
            escolhas[linha.rotulo] = rotulo_para_chave[escolha]

    caminho = st.session_state.get("arquivo_importado")
    if escolhas and caminho and st.button("Aplicar correções"):
        try:
            corrigido = aplicar_mapeamento_manual(dfs, caminho, escolhas)
        except (ValueError, FileNotFoundError) as erro:
            st.error(f"Não consegui aplicar: {erro}")
            return
        estado.definir_demonstracoes(corrigido)
        st.success(f"{len(escolhas)} linha(s) remapeada(s).")
        st.rerun()


def _aplicar_sugestao(dfs) -> None:
    analise = estado.analise()
    if analise is None:
        st.error("Não foi possível analisar o histórico importado.")
        return

    try:
        sugestao = sugerir_premissas(analise, horizonte=5)
    except ValueError as erro:
        st.error(f"Não consegui derivar premissas: {erro}")
        return

    estado.substituir_bloco("operacionais", sugestao.operacionais)
    estado.substituir_bloco("ponte", sugestao.ponte)
    estado.substituir_bloco("custo_capital", sugestao.custo_capital)
    estado.atualizar({"nome": dfs.empresa, "unidade": dfs.unidade})

    st.success("Premissas preenchidas a partir do histórico.")
    st.markdown("**De onde veio cada uma**")
    for chave, justificativa in sugestao.justificativas.items():
        st.markdown(f"- **{chave}**: {justificativa}")
    for alerta in sugestao.alertas:
        st.warning(alerta)


def _template() -> None:
    st.markdown(
        "Se você não tem um export pronto, baixe o template, preencha e importe de "
        "volta pela primeira aba. As contas já vêm nomeadas do jeito que o app "
        "reconhece."
    )
    colunas = st.columns(2)
    ano_final = colunas[0].number_input(
        "Último ano", min_value=2000, max_value=2100, value=2025
    )
    quantidade = colunas[1].number_input(
        "Quantos anos", min_value=2, max_value=15, value=5
    )

    anos = list(range(int(ano_final) - int(quantidade) + 1, int(ano_final) + 1))
    destino = Path(tempfile.gettempdir()) / "template_demonstracoes.xlsx"
    gerar_template(destino, anos=anos, empresa=estado.empresa().nome)

    st.download_button(
        "Baixar template preenchível",
        data=destino.read_bytes(),
        file_name="template_demonstracoes.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary",
    )


def _manual() -> None:
    st.markdown(
        "Para um valuation rápido, o modelo só precisa da receita do ano base e dos "
        "saldos do balanço. O histórico é opcional — mas sem ele as premissas ficam "
        "sem âncora e o diagnóstico perde as comparações mais úteis."
    )

    empresa = estado.empresa()
    operacionais = empresa.operacionais
    ponte = empresa.ponte

    with st.form("dados_manuais"):
        colunas = st.columns(2)
        nome = colunas[0].text_input("Nome da empresa", value=empresa.nome)
        unidade = colunas[1].text_input("Unidade dos valores", value=empresa.unidade)

        st.markdown("**Ano base**")
        colunas = st.columns(2)
        receita = colunas[0].number_input(
            "Receita líquida", value=float(operacionais.receita_base), step=10.0
        )
        ano_base = colunas[1].number_input(
            "Ano base", min_value=2000, max_value=2100,
            value=int(operacionais.ano_base) or 2025,
        )

        st.markdown("**Balanço na data-base**")
        colunas = st.columns(3)
        divida = colunas[0].number_input(
            "Dívida bruta", value=float(ponte.divida_bruta), step=10.0
        )
        caixa = colunas[1].number_input("Caixa", value=float(ponte.caixa), step=10.0)
        acoes = colunas[2].number_input(
            "Ações em circulação",
            value=float(ponte.acoes_em_circulacao or 0.0),
            step=1.0,
            help="Na mesma unidade dos valores (se está em milhões, informe em milhões).",
        )

        colunas = st.columns(3)
        minoritarios = colunas[0].number_input(
            "Minoritários", value=float(ponte.minoritarios), step=1.0
        )
        contingencias = colunas[1].number_input(
            "Contingências", value=float(ponte.contingencias), step=1.0
        )
        prejuizo = colunas[2].number_input(
            "Prejuízo fiscal acumulado",
            value=float(empresa.prejuizo_fiscal_acumulado),
            step=10.0,
            help="Abate lucro futuro, com a trava de 30% ao ano.",
        )

        if st.form_submit_button("Salvar", type="primary"):
            from dataclasses import replace

            estado.substituir_bloco(
                "operacionais",
                replace(operacionais, receita_base=receita, ano_base=int(ano_base)),
            )
            estado.substituir_bloco(
                "ponte",
                replace(
                    ponte,
                    divida_bruta=divida,
                    caixa=caixa,
                    minoritarios=minoritarios,
                    contingencias=contingencias,
                    acoes_em_circulacao=acoes or None,
                ),
            )
            estado.atualizar(
                {
                    "nome": nome,
                    "unidade": unidade,
                    "prejuizo_fiscal_acumulado": prejuizo,
                }
            )
            st.success("Dados salvos.")

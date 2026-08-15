"""Ponto de entrada do app.

    streamlit run app/main.py

O app nao grava nada em disco: todo o estado vive na sessao. Isso mantem os
dados de cada empresa dentro da propria sessao e deixa o mesmo codigo pronto
para rodar em um servidor compartilhado sem retrabalho.
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

# Permite `streamlit run app/main.py` a partir da raiz do repositorio, sem
# depender de o pacote estar instalado no ambiente.
RAIZ = Path(__file__).resolve().parent.parent
for caminho in (str(RAIZ), str(RAIZ / "src")):
    if caminho not in sys.path:
        sys.path.insert(0, caminho)

from app import estado  # noqa: E402
from app.componentes import formatar  # noqa: E402
from app.paginas import (  # noqa: E402
    custo_capital,
    dados,
    diagnostico,
    exportar,
    historico,
    inicio,
    multiplos,
    premissas,
    sensibilidade,
    valor,
)
from app.tema import aplicar_css  # noqa: E402

st.set_page_config(
    page_title="Valuation",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)


def _barra_lateral() -> None:
    """Resumo permanente do modelo, visivel de qualquer tela.

    Ter o WACC e o valor sempre a vista muda como se usa o app: da para mexer em
    uma premissa e ver o efeito sem trocar de tela, que e exatamente o ciclo de
    trabalho de quem esta sensibilizando um modelo.
    """
    with st.sidebar:
        empresa = estado.empresa()
        st.markdown(f"### {empresa.nome}")
        st.caption(f"Valores em {empresa.unidade}")

        resultado = estado.resultado()
        if resultado is None:
            st.error("As premissas atuais não fecham.")
            erro = estado.erro_do_modelo()
            if erro:
                st.caption(erro)
            return

        st.metric(
            "Equity Value",
            formatar(resultado.equity_value, "moeda", empresa.unidade),
        )
        colunas = st.columns(2)
        colunas[0].metric("WACC", formatar(resultado.custo_capital.wacc_brl, "pct2"))
        colunas[1].metric(
            "g perpétuo",
            formatar(empresa.perpetuidade.crescimento_perpetuo, "pct2"),
        )
        if resultado.valor_por_acao is not None:
            st.metric(
                "Valor por ação", formatar(resultado.valor_por_acao, "numero")
            )
        st.caption(
            f"{formatar(resultado.dcf.peso_perpetuidade, 'pct')} do valor vem da "
            "perpetuidade"
        )

        diag = estado.diagnostico()
        if diag is not None and len(diag):
            st.divider()
            erros = len(diag.erros)
            alertas = len(diag.alertas)
            if erros:
                st.error(f"{erros} erro(s) no diagnóstico")
            elif alertas:
                st.warning(f"{alertas} alerta(s) no diagnóstico")


def main() -> None:
    estado.iniciar()
    aplicar_css()

    # Toda tela expoe uma funcao `render`, entao o caminho de URL precisa ser
    # declarado: sem isso o Streamlit o infere do nome da funcao e as dez
    # paginas colidem no mesmo endereco.
    paginas = [
        st.Page(inicio.render, title="Início", icon="🏠", url_path="inicio", default=True),
        st.Page(dados.render, title="Dados", icon="📥", url_path="dados"),
        st.Page(historico.render, title="Histórico", icon="📈", url_path="historico"),
        st.Page(premissas.render, title="Premissas", icon="✏️", url_path="premissas"),
        st.Page(
            custo_capital.render,
            title="Custo de capital",
            icon="⚖️",
            url_path="custo-de-capital",
        ),
        st.Page(valor.render, title="Valor", icon="💰", url_path="valor"),
        st.Page(
            sensibilidade.render,
            title="Sensibilidade",
            icon="🎲",
            url_path="sensibilidade",
        ),
        st.Page(multiplos.render, title="Múltiplos", icon="🔍", url_path="multiplos"),
        st.Page(
            diagnostico.render, title="Diagnóstico", icon="🩺", url_path="diagnostico"
        ),
        st.Page(exportar.render, title="Exportar", icon="📤", url_path="exportar"),
    ]

    navegacao = st.navigation(paginas, position="sidebar")
    _barra_lateral()
    navegacao.run()


main()

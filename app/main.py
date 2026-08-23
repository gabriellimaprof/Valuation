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

from app import estado, navegacao  # noqa: E402
from app.componentes import formatar, proximo_passo  # noqa: E402
from app.paginas import (  # noqa: E402
    custo_capital,
    dados,
    diagnostico,
    exportar,
    historico,
    inicio,
    margem,
    multiplos,
    premissas,
    retorno,
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

        # Banco e seguradora nao sao avaliados por FCFF ao WACC, e anunciar
        # aqui um Equity Value e um WACC que a tela de Valor recusou a usar
        # seria contradizer, na barra lateral, o que a tela principal explica.
        from valuation.bancos import e_instituicao_financeira

        dfs = estado.demonstracoes()
        if dfs is not None and e_instituicao_financeira(dfs):
            st.info(
                "Instituição financeira: o valor sai do **lucro residual**, em "
                "**Valor**, e não de um DCF ao WACC."
            )
            return

        resultado = estado.resultado()
        if resultado is None:
            st.error("As premissas atuais não fecham.")
            erro = estado.erro_do_modelo()
            if erro:
                st.caption(erro)
            return

        # Sem a unidade dentro do numero: a barra lateral e estreita, e
        # "930,0 R$ milhoes" sai truncado em "930,0 R$ mil…". A legenda acima ja
        # diz em que unidade tudo aqui esta.
        st.metric(
            "Equity Value", formatar(resultado.equity_value, "moeda"), border=True
        )
        colunas = st.columns(2)
        colunas[0].metric(
            "WACC", formatar(resultado.custo_capital.wacc_brl, "pct"), border=True
        )
        colunas[1].metric(
            "g perpétuo",
            formatar(empresa.perpetuidade.crescimento_perpetuo, "pct"),
            border=True,
        )
        if resultado.valor_por_acao is not None:
            st.metric(
                "Valor por ação",
                formatar(resultado.valor_por_acao, "numero"),
                border=True,
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
    # declarado: sem isso o Streamlit o infere do nome da funcao e as doze
    # paginas colidem no mesmo endereco.
    #
    # A ordem, os titulos e os icones vivem em `navegacao.PASSOS`, e nao aqui:
    # o Inicio desenha o mesmo caminho e o rodape de cada tela linka para o
    # proximo, e tres copias da mesma lista divergem na primeira mudanca.
    telas = {
        "inicio": inicio.render,
        "dados": dados.render,
        "historico": historico.render,
        "premissas": premissas.render,
        "custo_capital": custo_capital.render,
        "valor": valor.render,
        "retorno": retorno.render,
        "margem": margem.render,
        "sensibilidade": sensibilidade.render,
        "multiplos": multiplos.render,
        "diagnostico": diagnostico.render,
        "exportar": exportar.render,
    }
    paginas = {
        passo.chave: st.Page(
            telas[passo.chave],
            title=passo.titulo,
            icon=passo.icone_material,
            url_path=passo.url,
            default=passo.chave == "inicio",
        )
        for passo in navegacao.PASSOS
    }
    navegacao.registrar(paginas)

    menu = st.navigation(list(paginas.values()), position="sidebar")
    _barra_lateral()
    menu.run()

    # O rodape do caminho fica aqui, e nao no fim de cada `render`: e a mesma
    # peca em doze telas, e doze copias divergem. Depois do `run`, ele cai no
    # fim da tela que acabou de ser desenhada.
    # O casamento e pelo titulo, e nao pela URL: a pagina marcada como `default`
    # e servida na raiz e devolve `url_path` vazio, entao comparar por URL
    # deixaria justamente o Inicio sem rodape.
    atual = next((p.chave for p in navegacao.PASSOS if p.titulo == menu.title), None)
    if atual:
        proximo_passo(atual)


# O Streamlit executa o arquivo de entrada como ``__main__``, entao a guarda nao
# muda nada para quem roda o app -- e impede que **importar** este modulo suba a
# interface inteira como efeito colateral. Sem ela, um teste que so queria
# chamar ``_barra_lateral`` renderizava o app todo, e o resultado dependia de
# outro teste ja ter importado o modulo antes.
if __name__ == "__main__":
    main()

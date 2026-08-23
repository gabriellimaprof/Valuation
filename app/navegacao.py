"""O caminho do app como dado, e nao espalhado pelas telas.

O app e um **encadeamento**: dado bruto vira historico, historico vira premissa,
premissa vira valor. A ordem estava escrita em tres lugares -- a barra lateral do
``main``, a lista "o caminho completo" do Inicio e a cabeca de quem usa -- e um
usuario que terminava uma tela nao tinha como seguir sem voltar ao menu.

Aqui a ordem e uma lista so. Dela saem as paginas do ``st.navigation``, os
cartoes do Inicio e o rodape "proximo passo" de cada tela. Acrescentar uma etapa
passa a ser acrescentar uma linha.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Passo:
    """Uma tela do caminho, com o que ela pede e o que ela entrega."""

    chave: str
    titulo: str
    url: str
    icone: str
    resumo: str
    # A acao da tela, em voz de comando -- "Importe as demonstracoes". O titulo
    # diz onde voce esta; a acao diz o que fazer ali, e e o que o Inicio mostra.
    acao: str = "" 
    # O que precisa estar pronto para a tela dizer algo. ``None`` = nada; a tela
    # abre util em qualquer estado.
    exige: str | None = None

    @property
    def icone_material(self) -> str:
        return f":material/{self.icone}:"


# Icones do conjunto Material, e nao emoji. Emoji renderiza com a fonte do
# sistema operacional: muda de desenho entre Windows, macOS e Linux, nao herda a
# cor do tema e desalinha da altura do texto. Os nomes sao validados pelo
# Streamlit -- nome errado quebra o app na hora, o que e o erro visivel.
PASSOS: tuple[Passo, ...] = (
    Passo(
        "inicio", "Início", "inicio", "home",
        "O caminho inteiro, e onde você está nele.",
        acao="Comece por aqui",
    ),
    Passo(
        "dados", "Dados", "dados", "database",
        "Importe as demonstrações da CVM ou preencha à mão.",
        acao="Importe as demonstrações ou preencha à mão",
    ),
    Passo(
        "historico", "Histórico", "historico", "monitoring",
        "Margens, retorno sobre o capital e reinvestimento.",
        exige="demonstracoes",
        acao="Entenda o que a empresa entregou",
    ),
    Passo(
        "premissas", "Premissas", "premissas", "edit_note",
        "Projete o futuro a partir do que já aconteceu.",
        acao="Projete o futuro a partir do passado",
    ),
    Passo(
        "custo_capital", "Custo de capital", "custo-de-capital", "balance",
        "Beta, risco-país e estrutura de capital alvo.",
        acao="Defina a taxa de desconto",
    ),
    Passo(
        "valor", "Valor", "valor", "paid",
        "Fluxos descontados, perpetuidade e a ponte até o acionista.",
        acao="Veja o resultado e de onde ele vem",
    ),
    Passo(
        "retorno", "Retorno esperado", "retorno", "trending_up",
        "A TIR e de onde ela vem, aberta em lucro, múltiplo e dividendo.",
        acao="Descubra a TIR e de onde ela vem",
    ),
    Passo(
        "margem", "Margem de segurança", "margem", "shield",
        "Quanto o preço precisa cair para o risco valer a pena.",
        acao="Saiba a que preço o risco compensa",
    ),
    Passo(
        "sensibilidade", "Sensibilidade", "sensibilidade", "tune",
        "O que acontece com o valor quando a premissa erra.",
        acao="Descubra a faixa, não o ponto",
    ),
    Passo(
        "multiplos", "Múltiplos", "multiplos", "compare_arrows",
        "O que os comparáveis dizem, ao lado do que o DCF diz.",
        acao="Confronte com o mercado",
    ),
    Passo(
        "diagnostico", "Diagnóstico", "diagnostico", "stethoscope",
        "O modelo criticado por dentro, antes de você defendê-lo.",
        acao="Deixe o app criticar seu modelo",
    ),
    Passo(
        "exportar", "Exportar", "exportar", "download",
        "Planilha com fórmulas vivas e o relatório em markdown.",
        acao="Leve o modelo para fora do app",
    ),
)

POR_CHAVE = {passo.chave: passo for passo in PASSOS}


def proximo(chave: str) -> Passo | None:
    """O passo seguinte no caminho, ou ``None`` no fim dele."""
    for indice, passo in enumerate(PASSOS):
        if passo.chave == chave:
            return PASSOS[indice + 1] if indice + 1 < len(PASSOS) else None
    return None


def anterior(chave: str) -> Passo | None:
    """O passo anterior, ou ``None`` no comeco."""
    for indice, passo in enumerate(PASSOS):
        if passo.chave == chave:
            return PASSOS[indice - 1] if indice else None
    return None


def numero(chave: str) -> int:
    """Posicao no caminho, contando a partir do Inicio como zero."""
    for indice, passo in enumerate(PASSOS):
        if passo.chave == chave:
            return indice
    raise KeyError(f"passo desconhecido: {chave!r}")


# ---------------------------------------------------------------------------
# As paginas de verdade
# ---------------------------------------------------------------------------

REGISTRO = "_paginas_do_app"


def registrar(paginas: dict[str, object]) -> None:
    """Guarda as ``st.Page`` construidas, para o rodape poder linkar para elas.

    ``st.page_link`` num app com ``st.navigation`` exige o **objeto** da pagina,
    e nao um caminho de URL: passar a string leva ao "page not found". Como so o
    ``main`` constroi as paginas, elas ficam aqui, na sessao -- e nao num global
    de modulo, que atravessaria sessoes de usuarios diferentes no mesmo processo.
    """
    import streamlit as st

    st.session_state[REGISTRO] = paginas


def pagina(chave: str):
    """A ``st.Page`` de um passo, ou ``None`` se o app ainda nao as registrou."""
    import streamlit as st

    return st.session_state.get(REGISTRO, {}).get(chave)

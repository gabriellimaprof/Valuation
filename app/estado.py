"""Estado da sessao.

Tudo vive em ``st.session_state`` e nada e gravado em disco. Isso e uma decisao
de arquitetura, nao de preguica: sem estado local, o mesmo codigo roda na
maquina do analista hoje e em um servidor compartilhado amanha, sem retrabalho e
sem que dados de um cliente vazem para a sessao de outro.
"""

from __future__ import annotations

import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Any

import streamlit as st

from valuation import (
    Alvo,
    Comparavel,
    Empresa,
    PremissasCustoCapital,
    PremissasMacro,
    PremissasOperacionais,
    PremissasPerpetuidade,
    PonteValor,
    avaliar,
    substituir_varios,
)
from valuation.diagnostico import Diagnostico, diagnosticar
from valuation.historico import AnaliseHistorica, analisar
from valuation.importacao import Demonstracoes
from valuation.projeto import Projeto

CHAVE_EMPRESA = "empresa"
CHAVE_DFS = "demonstracoes"
CHAVE_COMPARAVEIS = "comparaveis"
CHAVE_ALVO = "alvo"
CHAVE_CONFIG = "config"
CHAVE_PASTA = "pasta_temporaria"
CHAVE_PRECO = "preco_pedido"


def pasta_temporaria() -> Path:
    """Pasta de arquivos temporarios exclusiva desta sessao.

    O app escreve alguns arquivos de apoio -- a planilha de conferencia da
    importacao, o modelo em Excel, o template. Com nome fixo em ``/tmp``, duas
    sessoes no mesmo servidor escrevem no mesmo caminho: a planilha de uma
    empresa passa a ser lida como a de outra, sem erro nenhum na tela. Uma pasta
    por sessao elimina isso sem precisar coordenar nomes.
    """
    caminho = st.session_state.get(CHAVE_PASTA)
    if caminho is None:
        caminho = tempfile.mkdtemp(prefix="valuation_")
        st.session_state[CHAVE_PASTA] = caminho
    pasta = Path(caminho)
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta


# O nome que a empresa tem antes de alguem dizer qual empresa e. Fica nomeado
# porque o import precisa reconhece-lo para saber que pode substitui-lo.
NOME_PADRAO = "Nova empresa"


def _empresa_inicial() -> Empresa:
    """Empresa de partida: plausivel o suficiente para o app abrir funcionando.

    Comecar de um modelo vazio faria a primeira tela ser uma parede de campos em
    branco. Comecar de um exemplo coerente deixa o usuario ver o mecanismo
    inteiro rodando antes de trocar os numeros pelos dele.
    """
    return Empresa(
        nome=NOME_PADRAO,
        macro=PremissasMacro(),
        custo_capital=PremissasCustoCapital(
            beta_alavancado_setor=1.0, divida_pl_setor=0.4, divida_pl_alvo=0.4
        ),
        operacionais=PremissasOperacionais(
            receita_base=1000.0,
            crescimento_receita=[0.08, 0.07, 0.06, 0.05, 0.045],
            margem_ebitda=[0.20] * 5,
            depreciacao_pct_receita=[0.045] * 5,
            capex_pct_receita=[0.05] * 5,
            capital_giro_pct_receita=[0.12] * 5,
        ),
        perpetuidade=PremissasPerpetuidade(
            crescimento_perpetuo=0.045, roic_perpetuidade=0.15
        ),
        ponte=PonteValor(divida_bruta=400.0, caixa=120.0, acoes_em_circulacao=100.0),
        unidade="R$ milhões",
    )


def iniciar() -> None:
    """Garante que a sessao tem todas as chaves esperadas."""
    st.session_state.setdefault(CHAVE_EMPRESA, _empresa_inicial())
    st.session_state.setdefault(CHAVE_DFS, None)
    st.session_state.setdefault(CHAVE_COMPARAVEIS, [])
    st.session_state.setdefault(CHAVE_ALVO, None)
    st.session_state.setdefault(
        CHAVE_CONFIG,
        {
            "meio_de_ano": True,
            "tipo_fluxo": "fcff",
            "setor": None,
            "pais": "Brasil",
            # Saldo de divida bruta ao fim de cada ano projetado. So o FCFE
            # o usa, e sem ele o FCFE nao existe: e a variacao da divida que
            # separa o fluxo do acionista do fluxo da firma.
            "divida_por_ano": None,
            # O papel da companhia na B3. Mora aqui, e nao numa chave solta da
            # sessao, porque **o `config` viaja no projeto salvo**: escolhido
            # uma vez, ele volta com o valuation em vez de ter de ser digitado
            # de novo. O cadastro da CVM nao o traz, e a busca por nome acha
            # so 40% -- perder essa escolha custa caro.
            "ticker": None,
        },
    )


# ---------------------------------------------------------------------------
# Empresa
# ---------------------------------------------------------------------------


def empresa() -> Empresa:
    return st.session_state[CHAVE_EMPRESA]


def definir_empresa(nova: Empresa) -> None:
    st.session_state[CHAVE_EMPRESA] = nova


def atualizar(alteracoes: dict[str, Any]) -> Empresa:
    """Aplica alteracoes por caminho pontilhado e guarda o resultado.

    As alteracoes vao juntas em uma unica operacao para que a validacao das
    premissas veja o estado final, e nao um intermediario incoerente.
    """
    nova = substituir_varios(empresa(), alteracoes)
    definir_empresa(nova)
    return nova


def substituir_bloco(campo: str, valor: Any) -> Empresa:
    """Troca um bloco inteiro de premissas (operacionais, ponte, custo de capital)."""
    nova = replace(empresa(), **{campo: valor})
    definir_empresa(nova)
    return nova


# ---------------------------------------------------------------------------
# Configuracao de calculo
# ---------------------------------------------------------------------------


def config() -> dict[str, Any]:
    return st.session_state[CHAVE_CONFIG]


def definir_config(chave: str, valor: Any) -> None:
    """Guarda uma convencao na sessao -- e, por tabela, no projeto salvo."""
    st.session_state[CHAVE_CONFIG][chave] = valor


def convencoes() -> dict[str, Any]:
    """Convencoes de calculo repassadas a toda analise derivada.

    Sensibilidade, cenarios e Monte Carlo precisam rodar exatamente sob as
    mesmas convencoes do caso base; do contrario o cenario "base" nao reproduz
    o numero principal e o modelo perde credibilidade na primeira conferencia.
    """
    c = config()
    convencoes: dict[str, Any] = {
        "meio_de_ano": c["meio_de_ano"],
        "tipo_fluxo": c["tipo_fluxo"],
    }
    # O cronograma so viaja quando o fluxo e o do acionista. Mandar junto no
    # FCFF nao mudaria o numero, mas faria a sensibilidade carregar uma premissa
    # que a tela nao mostra -- e premissa invisivel e a que ninguem confere.
    if c["tipo_fluxo"] == "fcfe":
        convencoes["divida_por_ano"] = c.get("divida_por_ano") and list(
            c["divida_por_ano"]
        ) or _divida_constante()
    return convencoes


def _divida_constante() -> list[float] | None:
    """Divida parada no saldo de hoje, por todo o horizonte.

    E o padrao porque o FCFE **nao existe sem cronograma**: sem ele a tela
    oferecia a opcao e o modelo respondia que nao fecha, sem dizer que faltava.
    Divida constante e a hipotese que a maioria dos modelos assume sem dizer, e
    ela nao e neutra -- com variacao zero, o FCFE fica abaixo do FCFF pelo juro
    depois de imposto. O editor na tela de Valor existe para trocar isso por um
    cronograma de verdade.
    """
    e = empresa()
    if e is None or e.operacionais is None:
        return None
    anos = len(e.operacionais.crescimento_receita)
    return [float(e.ponte.divida_bruta)] * anos


# ---------------------------------------------------------------------------
# Demonstracoes e analise historica
# ---------------------------------------------------------------------------


def demonstracoes() -> Demonstracoes | None:
    return st.session_state[CHAVE_DFS]


def definir_demonstracoes(dfs: Demonstracoes | None) -> None:
    """Guarda as demonstracoes e adota o nome da companhia importada.

    A barra lateral, o titulo da planilha e o cabecalho do relatorio saem de
    ``empresa.nome``, e ele continuava "Nova empresa" depois de importar a WEG --
    entao o app mostrava, e **exportava**, um valuation da WEG assinado como
    "Nova empresa".

    So substitui o nome padrao: quem renomeou a empresa a mao escolheu aquele
    nome, e reimportar nao pode desfazer a escolha pelas costas dele.
    """
    st.session_state[CHAVE_DFS] = dfs
    if dfs is None or not dfs.empresa:
        return
    atual = empresa()
    if atual.nome == NOME_PADRAO:
        definir_empresa(replace(atual, nome=dfs.empresa))


def tem_historico() -> bool:
    dfs = demonstracoes()
    return dfs is not None and bool(dfs.anos)


def analise() -> AnaliseHistorica | None:
    """Analise historica da sessao, ou ``None`` se ainda nao ha demonstracoes."""
    dfs = demonstracoes()
    if dfs is None or not dfs.anos:
        return None
    try:
        return analisar(dfs)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Preco pedido
# ---------------------------------------------------------------------------


def preco() -> dict[str, float | bool] | None:
    """O preco em avaliacao, compartilhado entre as telas que precisam dele.

    Retorno esperado, Margem de seguranca e o relatorio fazem a mesma pergunta a
    partir do mesmo numero. Guardar em cada tela faria as tres discordarem entre
    si sem que nada acusasse, que e o pior tipo de divergencia num material que
    vai para o cliente.
    """
    return st.session_state.get(CHAVE_PRECO)


def definir_preco(valor: float, por_acao: bool) -> None:
    st.session_state[CHAVE_PRECO] = {"valor": float(valor), "por_acao": bool(por_acao)}


# ---------------------------------------------------------------------------
# Comparaveis
# ---------------------------------------------------------------------------


def comparaveis() -> list[Comparavel]:
    return st.session_state[CHAVE_COMPARAVEIS]


def definir_comparaveis(lista: list[Comparavel]) -> None:
    st.session_state[CHAVE_COMPARAVEIS] = lista


def alvo() -> Alvo | None:
    return st.session_state[CHAVE_ALVO]


def definir_alvo(novo: Alvo | None) -> None:
    st.session_state[CHAVE_ALVO] = novo


# ---------------------------------------------------------------------------
# Resultado
# ---------------------------------------------------------------------------


def resultado():
    """Valuation da empresa atual, ou ``None`` se as premissas nao fecham.

    Devolver ``None`` em vez de propagar a excecao permite que cada tela decida
    como reagir: a de premissas mostra o erro junto do campo, a de valor mostra
    um aviso e some com os graficos.
    """
    try:
        return avaliar(empresa(), **convencoes())
    except ValueError:
        return None


def erro_do_modelo() -> str | None:
    """Mensagem do erro que impede o calculo, se houver."""
    try:
        avaliar(empresa(), **convencoes())
        return None
    except ValueError as erro:
        return str(erro)


def diagnostico() -> Diagnostico | None:
    resultado_atual = resultado()
    if resultado_atual is None:
        return None
    return diagnosticar(
        resultado_atual,
        analise=analise(),
        retorno=st.session_state.get("decomposicao_tsr"),
    )


# ---------------------------------------------------------------------------
# Salvar e retomar o trabalho
# ---------------------------------------------------------------------------


def projeto_atual() -> Projeto:
    """Empacota o estado da sessao inteiro em um objeto salvavel."""
    return Projeto(
        empresa=empresa(),
        demonstracoes=demonstracoes(),
        comparaveis=comparaveis(),
        alvo=alvo(),
        config=dict(config()),
    )


def aplicar_projeto(projeto: Projeto) -> None:
    """Substitui o estado da sessao pelo conteudo de um projeto carregado.

    Substitui em vez de mesclar: retomar um valuation salvo tem que devolver
    exatamente aquele valuation, sem restos da analise que estava aberta antes.
    """
    definir_empresa(projeto.empresa)
    definir_demonstracoes(projeto.demonstracoes)
    definir_comparaveis(list(projeto.comparaveis))
    definir_alvo(projeto.alvo)
    st.session_state[CHAVE_CONFIG] = {
        **{
            "meio_de_ano": True,
            "tipo_fluxo": "fcff",
            "setor": None,
            "pais": "Brasil",
            "ticker": None,
            # Saldo de divida bruta ao fim de cada ano projetado. So o FCFE
            # o usa, e sem ele o FCFE nao existe: e a variacao da divida que
            # separa o fluxo do acionista do fluxo da firma.
            "divida_por_ano": None,
        },
        **projeto.config,
    }
    # Analises derivadas pertencem ao modelo anterior e ficariam desatualizadas.
    for chave in (
        "tabela_sensibilidade",
        "tabela_cenarios",
        "simulacao",
        "excel_gerado",
        "decomposicao_tsr",
    ):
        st.session_state.pop(chave, None)


# ---------------------------------------------------------------------------
# Retorno esperado (usado pelo diagnostico e pela exportacao)
# ---------------------------------------------------------------------------


def definir_decomposicao_tsr(decomposicao) -> None:
    st.session_state["decomposicao_tsr"] = decomposicao


def decomposicao_tsr():
    return st.session_state.get("decomposicao_tsr")

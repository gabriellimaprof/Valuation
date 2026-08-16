"""Tela de dados: importar demonstracoes, conferir o que foi reconhecido e corrigir."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

from valuation import biblioteca
from valuation.historico import sugerir_premissas
from valuation.importacao import (
    CONTAS,
    POR_CHAVE,
    aplicar_mapeamento_manual,
    gerar_template,
    importar,
)
from valuation.importacao.cvm import (
    FONTE_CVM,
    ErroCVM,
    anos_disponiveis,
    buscar_companhias,
    carregar_cadastro,
    importar_cvm,
)
from valuation.importacao.esquema import extrair_codigo_cvm

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

    # A aba da biblioteca so existe quando ela foi ligada por configuracao: num
    # servidor a variavel nao e definida e o app segue sem estado em disco.
    rotulos = ["Retomar valuation salvo", "Buscar na CVM", "Importar planilha"]
    if biblioteca.esta_ligada():
        rotulos.insert(0, "Biblioteca")
    rotulos += ["Baixar template", "Preencher à mão"]

    abas = dict(zip(rotulos, st.tabs(rotulos)))

    if "Biblioteca" in abas:
        with abas["Biblioteca"]:
            _biblioteca()
    with abas["Retomar valuation salvo"]:
        _retomar()
    with abas["Buscar na CVM"]:
        _cvm()
    with abas["Importar planilha"]:
        _importar()
    with abas["Baixar template"]:
        _template()
    with abas["Preencher à mão"]:
        _manual()

    # A conferencia fica fora das abas, e nao dentro de cada origem, porque o
    # Streamlit executa o corpo de todas as abas em cada rerun: chamada de dois
    # lugares, ela registraria os mesmos widgets duas vezes e o app quebraria
    # com chave duplicada. Fora das abas ela tambem passa a ser o que o nome diz
    # -- uma tela de conferencia so, comum a qualquer origem de importacao.
    _mostrar_importacao_atual()


def _biblioteca() -> None:
    """Lista os valuations guardados na pasta local e permite abri-los."""
    pasta = biblioteca.diretorio()
    st.markdown(
        "Os valuations que você guardou nesta máquina. Cada um é um arquivo "
        "**.yaml** na pasta abaixo — dá para versionar em Git, copiar ou abrir "
        "num editor sem passar pelo app."
    )
    st.caption(f"Pasta: `{pasta}` · definida em `{biblioteca.VARIAVEL}`.")

    entradas = biblioteca.listar()
    if not entradas:
        st.info(
            "Nenhum valuation guardado ainda. Monte um e use **Exportar → Guardar "
            "na biblioteca**."
        )
        return

    for indice, entrada in enumerate(entradas):
        colunas = st.columns([4, 2, 2, 1, 1])
        colunas[0].markdown(f"**{entrada.empresa}**")
        colunas[0].caption(entrada.nome_do_arquivo)
        colunas[1].caption(entrada.periodo + (f" · {entrada.unidade}" if entrada.unidade else ""))
        colunas[2].caption(entrada.atualizado_em.strftime("%d/%m/%Y %H:%M"))

        if not entrada.legivel:
            colunas[1].caption(":red[não consegui ler]")
            colunas[3].caption("—")
        elif colunas[3].button("Abrir", key=f"abrir_{indice}"):
            _abrir_da_biblioteca(entrada)

        if colunas[4].button("Excluir", key=f"excluir_{indice}"):
            biblioteca.excluir(entrada.caminho)
            st.rerun()

    _comparar_versoes(entradas)


def _comparar_versoes(entradas) -> None:
    """Compara um valuation guardado com o que está aberto, e diz o que moveu o valor."""
    from valuation.comparacao import comparar

    legiveis = [e for e in entradas if e.legivel]
    if not legiveis:
        return

    st.divider()
    st.markdown("**Comparar com o valuation aberto**")
    st.caption(
        "Um diff do arquivo diz o que mudou. Isto diz **quanto cada mudança "
        "valeu** — as premissas interagem, então somar efeitos isolados não "
        "reproduz o total. A ponte é construída uma premissa por vez, e fecha."
    )

    rotulos = {f"{e.empresa} · {e.nome_do_arquivo}": e for e in legiveis}
    escolhido = st.selectbox("Versão guardada", list(rotulos), key="comparar_com")
    if not st.button("Comparar"):
        return

    try:
        antiga = biblioteca.abrir(rotulos[escolhido].caminho)
    except (ValueError, FileNotFoundError) as erro:
        st.error(f"Não consegui abrir: {erro}")
        return

    resultado = comparar(antiga.empresa, estado.empresa(), **estado.convencoes())
    _mostrar_comparacao(resultado, rotulos[escolhido].empresa)


def _mostrar_comparacao(resultado, nome_antigo: str) -> None:
    from ..componentes import formatar

    unidade = estado.empresa().unidade
    colunas = st.columns(3)
    colunas[0].metric(f"{nome_antigo} (guardado)", formatar(resultado.valor_antes, "moeda", unidade))
    colunas[1].metric("Aberto agora", formatar(resultado.valor_depois, "moeda", unidade))
    colunas[2].metric(
        "Variação",
        formatar(resultado.variacao, "moeda", unidade),
        delta=formatar(resultado.variacao_relativa, "pct"),
    )

    for aviso in resultado.avisos:
        st.warning(aviso)

    if not resultado.movimentos:
        st.info("As premissas das duas versões são iguais.")
        return

    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Premissa": m.rotulo,
                    "Antes": _texto_premissa(m.antes),
                    "Depois": _texto_premissa(m.depois),
                    "Moveu o valor": formatar(m.efeito, "moeda", unidade),
                }
                for m in resultado.por_efeito
            ]
        ).set_index("Premissa"),
        width="stretch",
    )

    if abs(resultado.nao_atribuido) > 0:
        st.caption(
            "Não atribuído a nenhuma premissa isolada: "
            + formatar(resultado.nao_atribuido, "moeda", unidade)
        )


def _texto_premissa(valor) -> str:
    """Premissa em texto curto, com percentuais legíveis e listas resumidas."""
    from ..componentes import formatar

    if isinstance(valor, (list, tuple)):
        if not valor:
            return "—"
        if all(isinstance(v, float) and abs(v) < 1 for v in valor):
            return ", ".join(formatar(v, "pct") for v in valor)
        return ", ".join(str(v) for v in valor)
    if isinstance(valor, float) and abs(valor) < 1:
        return formatar(valor, "pct2")
    if isinstance(valor, float):
        return formatar(valor, "moeda")
    return str(valor)


def _abrir_da_biblioteca(entrada) -> None:
    try:
        projeto = biblioteca.abrir(entrada.caminho)
    except (ValueError, FileNotFoundError) as erro:
        st.error(f"Não consegui abrir {entrada.nome_do_arquivo}: {erro}")
        return
    estado.aplicar_projeto(projeto)
    st.success(f"{entrada.empresa} restaurado.")
    st.rerun()


def _retomar() -> None:
    """Carrega um arquivo .yaml salvo pelo app e devolve a analise inteira."""
    from valuation.projeto import desserializar

    st.markdown(
        "Suba o arquivo **.yaml** que você baixou na tela de **Exportar**. Ele traz "
        "de volta tudo: premissas, demonstrações importadas, comparáveis e as "
        "convenções de cálculo — exatamente como você deixou."
    )

    arquivo = st.file_uploader(
        "Arquivo do valuation", type=["yaml", "yml"], key="upload_projeto"
    )
    if arquivo is None:
        st.info(
            "Ainda não salvou nenhum? Monte um valuation e baixe o arquivo em "
            "**Exportar → Salvar este valuation**."
        )
        return

    try:
        projeto = desserializar(
            arquivo.getvalue().decode("utf-8"), origem=arquivo.name
        )
    except (ValueError, UnicodeDecodeError) as erro:
        st.error(f"Não consegui abrir o arquivo: {erro}")
        return

    st.success(f"Arquivo lido: **{projeto.empresa.nome}**")
    colunas = st.columns(3)
    colunas[0].metric(
        "Histórico",
        f"{len(projeto.demonstracoes.anos)} anos"
        if projeto.demonstracoes is not None
        else "sem histórico",
    )
    colunas[1].metric(
        "Horizonte",
        f"{projeto.empresa.operacionais.horizonte} anos"
        if projeto.empresa.operacionais
        else "—",
    )
    colunas[2].metric("Comparáveis", len(projeto.comparaveis))

    st.warning(
        "Carregar substitui o que está aberto agora. Se houver trabalho não salvo "
        "na sessão atual, baixe antes em **Exportar**."
    )
    if st.button("Carregar este valuation", type="primary"):
        estado.aplicar_projeto(projeto)
        st.success("Valuation restaurado.")
        st.rerun()


# A CVM sempre publica em reais (o leitor ja corrige ESCALA_MOEDA), entao aqui
# a pergunta e so em que unidade o usuario quer trabalhar -- e nao, como na
# importacao de planilha, em que unidade o arquivo veio.
UNIDADES_CVM = {
    "R$ milhões": (1_000_000, "R$ milhões"),
    "R$ mil": (1_000, "R$ mil"),
    "R$ bilhões": (1_000_000_000, "R$ bilhões"),
    "Reais (R$ 1)": (1, "R$"),
}

# Historico longo o bastante para o ciclo aparecer: pega a pandemia, a inflacao
# de 2021-2022 e a normalizacao seguinte, que e o periodo que da contexto a
# qualquer projecao feita hoje.
ANO_PADRAO_INICIAL = 2019


@st.cache_data(show_spinner=False, ttl=60 * 60 * 24)
def _catalogo_cvm():
    """Cadastro de companhias abertas, baixado uma vez por dia."""
    return carregar_cadastro()


@st.cache_data(show_spinner=False, ttl=60 * 60 * 24)
def _anos_cvm() -> list[int]:
    return anos_disponiveis()


def _cvm() -> None:
    """Importa direto dos Dados Abertos da CVM: escolher empresa e ano."""
    st.markdown(
        "Busque a companhia pelo **nome** ou pelo **CNPJ** e escolha os anos. O app "
        "baixa a **DFP** de dados.cvm.gov.br, converte para o mesmo vocabulário das "
        "outras origens e cai na mesma tela de conferência. Os arquivos ficam em "
        "cache: o segundo valuation da mesma empresa não baixa nada de novo."
    )

    try:
        catalogo = _catalogo_cvm()
    except ErroCVM as erro:
        st.error(f"Não consegui obter o cadastro de companhias da CVM: {erro}")
        return

    st.caption(f"{len(catalogo):,} companhias com registro ativo na CVM.".replace(",", "."))

    termo = st.text_input(
        "Empresa",
        key="busca_cvm",
        placeholder="WEG, Petrobras, Vivara… ou 84.429.695/0001-11",
        help="Nome social, nome comercial ou CNPJ (com ou sem pontuação).",
    )

    if not termo.strip():
        st.info("Digite parte do nome ou o CNPJ para começar.")
        return

    achados = buscar_companhias(termo, catalogo)
    if not achados:
        st.warning(
            f"Nenhuma companhia com registro ativo casou com “{termo}”. Empresas de "
            "capital fechado e registros cancelados não entram nos Dados Abertos."
        )
        return

    rotulos = {f"{c.nome} — {c.cnpj}": c for c in achados}
    escolhido = st.selectbox(f"{len(achados)} resultado(s)", list(rotulos))
    companhia = rotulos[escolhido]

    colunas = st.columns(3)
    colunas[0].metric("Código CVM", companhia.codigo_cvm)
    colunas[1].metric("Setor", companhia.setor or "—")
    colunas[2].metric("Mercado", companhia.mercado or "—")

    anos_ok = _anos_cvm()
    # De 2019 ate o ultimo exercicio com dado. O arquivo do ano corrente existe
    # desde janeiro, mas quase vazio -- a DFP de um exercicio so e entregue no
    # ano seguinte --, entao deixa-lo marcado faria toda importacao nascer com
    # um aviso de ano sem dado. Ele continua na lista para quem fecha o
    # exercicio social em marco e ja publicou.
    from datetime import date

    completos = [a for a in anos_ok if a < date.today().year] or anos_ok
    padrao = [a for a in completos if a >= ANO_PADRAO_INICIAL] or completos[-6:]
    colunas = st.columns([3, 1])
    anos = colunas[0].multiselect(
        "Exercícios",
        options=sorted(anos_ok, reverse=True),
        default=padrao,
        help="Um arquivo por ano, cerca de 13 MB cada. Só o primeiro download demora.",
    )
    unidade = colunas[1].selectbox("Unidade", list(UNIDADES_CVM))

    if not anos:
        st.info("Escolha ao menos um exercício. Para projetar, o ideal são 5 ou 6.")
        return

    incluir_ltm = st.checkbox(
        "Acrescentar o ano móvel (últimos 12 meses, do ITR)",
        value=False,
        help=(
            "Soma ao último exercício fechado o acumulado do ano corrente e "
            "subtrai o mesmo período do ano anterior. É o número atualizado até "
            "o trimestre mais recente — e não um exercício social."
        ),
    )

    if st.button("Importar da CVM", type="primary"):
        _processar_cvm(companhia, sorted(anos), unidade, incluir_ltm)

    _cache_da_cvm()


def _cache_da_cvm() -> None:
    """Mostra o tamanho do cache e permite limpa-lo.

    Os zips ficam numa pasta que o usuario nunca abre e nada apaga; doze anos
    passam de 150 MB. Melhor mostrar do que deixar crescer calado.
    """
    from valuation.importacao.cvm import diretorio_cache, limpar_cache, tamanho_do_cache

    bytes_usados = tamanho_do_cache()
    if bytes_usados < 50 * 1024 * 1024:
        return

    megas = f"{bytes_usados / 1e6:,.0f}".replace(",", ".")
    colunas = st.columns([3, 1])
    colunas[0].caption(
        f"Arquivos da CVM em cache: {megas} MB em `{diretorio_cache()}`. "
        "Limpar só custa baixar de novo o que for usado."
    )
    if colunas[1].button("Limpar cache"):
        removidos = limpar_cache()
        st.success(f"{removidos} arquivo(s) removido(s).")
        st.rerun()


def _processar_cvm(
    companhia, anos: list[int], unidade: str, incluir_ltm: bool = False
) -> None:
    destino = estado.pasta_temporaria() / f"cvm_{companhia.codigo_cvm}.xlsx"
    faixa = f"{anos[0]}–{anos[-1]}" if len(anos) > 1 else str(anos[0])

    try:
        with st.spinner(f"Baixando a DFP de {companhia.nome} ({faixa})…"):
            dfs = importar_cvm(companhia, anos, planilha=destino)
    except ErroCVM as erro:
        st.error(f"Não consegui importar da CVM: {erro}")
        return

    if incluir_ltm:
        dfs = _acrescentar_ltm(companhia, dfs)

    divisor, nova_unidade = UNIDADES_CVM[unidade]
    if divisor != 1:
        dfs = dfs.escalar(divisor, nova_unidade)

    estado.definir_demonstracoes(dfs)
    # A tela de conferencia reprocessa este arquivo quando o usuario corrige um
    # mapeamento, do mesmo jeito que faz com uma planilha enviada por upload.
    st.session_state["arquivo_importado"] = str(destino)
    st.success(
        f"Importado da CVM: {len(dfs.valores.index)} contas em {len(dfs.anos)} "
        f"exercício(s) ({dfs.anos[0]}–{dfs.anos[-1]})."
    )
    st.rerun()


def _acrescentar_ltm(companhia, dfs):
    """Junta o ano móvel como coluna mais recente da série anual.

    A coluna é rotulada pelo ano de encerramento do período móvel, e **substitui**
    um exercício de mesmo rótulo que ainda esteja incompleto. Sem substituir,
    apareceriam duas colunas com o mesmo ano e o gráfico mostraria um degrau que
    não existe.
    """
    from valuation.importacao.cvm import importar_ltm

    try:
        with st.spinner("Montando o ano móvel a partir do ITR…"):
            ltm = importar_ltm(companhia, catalogo=_catalogo())
    except ErroCVM as erro:
        st.warning(f"Importei os exercícios, mas não consegui montar o ano móvel: {erro}")
        return dfs

    rotulo = ltm.anos[-1]
    valores = dfs.valores.drop(columns=[rotulo], errors="ignore").join(
        ltm.valores, how="outer"
    )
    valores = valores[sorted(valores.columns)]

    from dataclasses import replace

    return replace(
        dfs,
        valores=valores,
        avisos=list(dfs.avisos) + list(ltm.avisos),
        fonte={**dfs.fonte, "ltm": ltm.fonte.get("ltm")},
    )


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
        return

    if st.button("Importar", type="primary"):
        _processar(arquivo, nome_empresa, int(anos_maximos), escala_escolhida)


def _processar(arquivo, nome_empresa: str, anos_maximos: int, escala: str) -> None:
    destino = estado.pasta_temporaria() / f"valuation_{arquivo.name}"
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

    _atualizar_da_cvm(dfs)

    for aviso in dfs.avisos:
        st.warning(aviso)

    aba_dre, aba_bp, aba_dfc, aba_conferencia = st.tabs(
        ["Resultado", "Balanço", "Fluxo de caixa", "O que o app entendeu"]
    )
    for aba, chave in ((aba_dre, "dre"), (aba_bp, "bp"), (aba_dfc, "dfc")):
        with aba:
            _demonstracao(dfs, chave)

    with aba_conferencia:
        _conferencia(dfs)

    st.divider()
    if st.button("Usar este histórico para sugerir as premissas", type="primary"):
        _aplicar_sugestao(dfs)


def _anos_a_acrescentar(
    salvos: list[int], disponiveis: list[int], ano_corrente: int
) -> list[int]:
    """Exercícios que surgiram depois do último já importado.

    Só avança no tempo: a conta ingênua — todos os disponíveis menos os salvos —
    faria um clique em "Atualizar" descer até 2010 e baixar uma década que o
    usuário deliberadamente não pediu. O ano corrente fica de fora porque a DFP
    de um exercício só é entregue no ano seguinte.
    """
    if not salvos:
        return []
    return sorted(a for a in disponiveis if max(salvos) < a < ano_corrente)


def _atualizar_da_cvm(dfs) -> None:
    """Rebusca na CVM a mesma companhia, incluindo exercícios novos.

    Só aparece quando as demonstrações guardam de onde vieram. É o que separa
    "sei dizer a origem" de "sei ir buscar de novo": um valuation retomado seis
    meses depois incorpora o exercício que saiu no meio, sem refazer a busca.
    """
    fonte = getattr(dfs, "fonte", None) or {}
    if fonte.get("tipo") != FONTE_CVM:
        return

    salvos = [int(a) for a in fonte.get("anos", [])]
    if not salvos:
        return
    try:
        disponiveis = _anos_cvm()
    except ErroCVM:
        return

    from datetime import date

    novos = _anos_a_acrescentar(salvos, disponiveis, date.today().year)

    colunas = st.columns([3, 1])
    if novos:
        colunas[0].info(
            "A CVM já publicou " + ", ".join(str(a) for a in novos)
            + " para outras companhias. Atualizar refaz a busca incluindo esse(s) "
            "exercício(s)."
        )
    else:
        colunas[0].caption(
            "Importado da CVM. Atualizar rebusca os mesmos exercícios — útil se a "
            "companhia reapresentou a DFP."
        )

    if colunas[1].button("Atualizar da CVM"):
        _reimportar_da_cvm(dfs, sorted(set(salvos) | set(novos)))


def _reimportar_da_cvm(dfs, anos: list[int]) -> None:
    fonte = dfs.fonte
    codigo = int(fonte["codigo_cvm"])
    destino = estado.pasta_temporaria() / f"cvm_{codigo}.xlsx"
    antes = set(dfs.anos)

    try:
        with st.spinner("Rebuscando na CVM…"):
            novo = importar_cvm(codigo, anos, planilha=destino)
    except ErroCVM as erro:
        st.error(f"Não consegui atualizar: {erro}")
        return

    # A unidade e o nome vieram de escolhas que o usuário já fez; refazer a
    # importação não pode desfazê-las pelas costas dele.
    if dfs.unidade != novo.unidade:
        divisor = next(
            (d for d, u in UNIDADES_CVM.values() if u == dfs.unidade), None
        )
        if divisor:
            novo = novo.escalar(divisor, dfs.unidade)
    novo = type(novo)(**{**novo.__dict__, "empresa": dfs.empresa})

    estado.definir_demonstracoes(novo)
    st.session_state["arquivo_importado"] = str(destino)

    ganhos = sorted(set(novo.anos) - antes)
    st.success(
        f"Atualizado: {novo.anos[0]}–{novo.anos[-1]}."
        + (f" Exercício(s) novo(s): {', '.join(str(a) for a in ganhos)}." if ganhos else "")
    )
    st.rerun()


def _demonstracao(dfs, chave: str) -> None:
    """Mostra a demonstração publicada inteira, ou as contas do modelo.

    A publicada é uma árvore: `1.01.01` está dentro de `1.01`, que está dentro
    de `1`. É a quebra que explica de onde vem o total, então ela é o padrão —
    as contas canônicas são o recorte que o motor consome, útil para conferir o
    que entrou no modelo, mas menor do que a demonstração.
    """
    arvore = dfs.arvore(chave)
    canonicas = dfs.tabela(chave)

    if arvore.empty and canonicas.empty:
        st.info("Nenhuma conta desta demonstração foi encontrada no arquivo.")
        return

    if arvore.empty:
        st.dataframe(tabela_formatada(canonicas, "moeda"), width="stretch")
        return

    completa = st.toggle(
        "Demonstração publicada, com a abertura",
        value=True,
        key=f"completa_{chave}",
        help=(
            "Ligado: todas as linhas como a companhia publicou, com o recuo "
            "mostrando a hierarquia. Desligado: só as contas que o modelo usa."
        ),
    )

    if completa:
        st.caption(
            f"{len(arvore)} linhas. O recuo é o nível do plano de contas — cada "
            "conta é a soma das que aparecem recuadas abaixo dela."
        )
        st.dataframe(
            tabela_formatada(arvore, "moeda"),
            width="stretch",
            height=min(760, 40 + 35 * len(arvore)),
        )
    elif canonicas.empty:
        st.info("Nenhuma conta do modelo veio desta demonstração.")
    else:
        st.dataframe(tabela_formatada(canonicas, "moeda"), width="stretch")


LIMITE_CONFERENCIA = 40


def _relevancia(linha) -> tuple[int, str]:
    """Ordena as linhas não reconhecidas da mais sintética para a mais analítica.

    O nível vem do código do plano de contas: ``6.02.02`` (capex, três níveis)
    interessa muito mais que ``1.01.06.01.01`` (imposto a recuperar, cinco). Em
    planilha sem código todos empatam em zero e a ordem continua alfabética,
    como era antes.
    """
    codigo = extrair_codigo_cvm(linha.rotulo)
    return (codigo.count(".") if codigo else 0, linha.rotulo)


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

    linhas = sorted(dfs.nao_reconhecidas, key=_relevancia)

    # A DFP traz centenas de linhas analíticas por empresa. Sem o filtro, a
    # lista chegava ordenada por código e as primeiras — as únicas que cabiam na
    # tela — eram justamente as de quarto e quinto nível, que ninguém mapeia: a
    # linha de capex da DFC ficava na posição 212 de 237, fora de alcance.
    origens = sorted({linha.aba for linha in linhas})
    if len(origens) > 1:
        quantas = {o: sum(1 for l in linhas if l.aba == o) for o in origens}
        escolhida = st.radio(
            "Onde procurar",
            ["Todas", *origens],
            format_func=lambda o: o if o == "Todas" else f"{o} ({quantas[o]})",
            horizontal=True,
            key="filtro_conferencia",
        )
        if escolhida != "Todas":
            linhas = [l for l in linhas if l.aba == escolhida]

    visiveis = linhas[:LIMITE_CONFERENCIA]
    if len(linhas) > LIMITE_CONFERENCIA:
        st.caption(
            f"Mostrando {LIMITE_CONFERENCIA} de {len(linhas)} linhas, das contas "
            "mais sintéticas para as mais analíticas. As que ficaram de fora são "
            "subcontas detalhadas — se precisar de uma delas, filtre pela "
            "demonstração acima."
        )

    opcoes = ["(ignorar)"] + [c.rotulo for c in CONTAS]
    rotulo_para_chave = {c.rotulo: c.chave for c in CONTAS}
    escolhas: dict[str, str] = {}

    for linha in visiveis:
        colunas = st.columns([3, 2])
        colunas[0].text(linha.rotulo)
        escolha = colunas[1].selectbox(
            "conta",
            opcoes,
            # A chave acompanha a linha, e nao a posicao: com o filtro ligado as
            # posicoes mudam, e uma escolha ja feita saltaria para outra conta.
            key=f"mapa_{linha.aba}|{linha.rotulo}",
            label_visibility="collapsed",
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
    destino = estado.pasta_temporaria() / "template_demonstracoes.xlsx"
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

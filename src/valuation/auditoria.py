"""De-para da leitura: cada conta canonica contra a linha que a alimentou.

Por que este modulo existe
--------------------------

O projeto acumulou reclassificacoes deliberadas -- arrendamento devolvido a
divida, juro trazido para o operacional, pagamento tirado do capital de giro,
outorga movida para o investimento. Cada uma foi medida quando entrou, mas
medida **isoladamente**. Confiar no conjunto exige outra coisa: passar a base
inteira e perguntar, conta por conta, de onde cada numero veio e se ele fecha
com os que deveriam limita-lo.

E uma auditoria, nao um teste. Testes fixam casos conhecidos; isto varre o que
ninguem olhou e devolve onde o vocabulario nao alcanca, onde a identidade nao
fecha e onde uma conta filha ficou maior que a conta pai.

Tres familias de verificacao
----------------------------

**Identidades.** Somas que a contabilidade obriga: ativo = passivo, as secoes da
DFC somando a variacao de caixa, a decomposicao do FCO. Elas sao o teste mais
direto de classificacao: se capex caiu no financiamento, a soma deixa de fechar.

**Contencao.** Conta filha nao pode exceder a conta que a contem. Arrendamento
nao passa da divida de que faz parte; caixa nao passa do ativo circulante. Sao
as verificacoes que pegam numero no lugar errado **sem** que nenhuma soma
quebre -- e por isso as mais valiosas.

**Origem.** Para cada conta canonica, quais codigos da CVM a alimentaram e em
quantas companhias. Uma conta que na maioria vem de ``3.01`` e numa companhia
vem de ``3.02`` nao dispara identidade nenhuma, e esta errada.

O que a auditoria **nao** faz: dizer qual leitura e a certa quando duas sao
defensaveis. Ela mostra a divergencia e quem decide e quem le.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .importacao.esquema import POR_CHAVE

# Tolerancia relativa para uma identidade ser considerada fechada. Acima disto
# ha erro de leitura, nao arredondamento de centavos.
TOLERANCIA = 0.01

GRAVE = "grave"
ATENCAO = "atencao"


def _periodo_do_achado(rotulo) -> int | str:
    """O rotulo como ele e: ``2024`` inteiro, ``2T25`` texto."""
    try:
        return int(str(rotulo).strip())
    except (TypeError, ValueError):
        return str(rotulo)


@dataclass(frozen=True)
class Achado:
    """Uma divergencia encontrada numa companhia."""

    codigo_cvm: int
    empresa: str
    # O rotulo do periodo, e nao o ano: numa serie trimestral a coluna e "2T25",
    # e forcar `int` aqui derrubava a auditoria inteira. Converter para o
    # exercicio tambem nao serve -- tres trimestres do mesmo ano viram a mesma
    # linha de achado e o analista nao sabe qual quebrou.
    ano: int | str
    verificacao: str
    severidade: str
    detalhe: str
    desvio: float = float("nan")


@dataclass(frozen=True)
class Auditoria:
    """Resultado de varrer um conjunto de companhias."""

    achados: list[Achado] = field(default_factory=list)
    companhias: int = 0
    origens: dict[str, dict[str, int]] = field(default_factory=dict)
    cobertura: dict[str, int] = field(default_factory=dict)

    def tabela(self) -> pd.DataFrame:
        if not self.achados:
            return pd.DataFrame(
                columns=["codigo_cvm", "empresa", "ano", "verificacao", "severidade", "detalhe"]
            )
        return pd.DataFrame(
            [
                {
                    "codigo_cvm": a.codigo_cvm,
                    "empresa": a.empresa,
                    "ano": a.ano,
                    "verificacao": a.verificacao,
                    "severidade": a.severidade,
                    "detalhe": a.detalhe,
                    "desvio": a.desvio,
                }
                for a in self.achados
            ]
        )

    def resumo(self) -> pd.DataFrame:
        """Quantas companhias falham em cada verificacao."""
        tabela = self.tabela()
        if tabela.empty:
            return pd.DataFrame(columns=["companhias", "severidade"])
        agrupado = tabela.groupby("verificacao").agg(
            companhias=("codigo_cvm", "nunique"),
            severidade=("severidade", "first"),
            pior_desvio=("desvio", "max"),
        )
        agrupado["% da base"] = agrupado["companhias"] / max(self.companhias, 1)
        return agrupado.sort_values("companhias", ascending=False)

    def tabela_de_origens(self, minimo: int = 1) -> pd.DataFrame:
        """O de-para: conta canonica x codigo da CVM que a alimentou."""
        linhas = []
        for chave, contagem in self.origens.items():
            total = sum(contagem.values())
            for codigo, n in sorted(contagem.items(), key=lambda x: -x[1]):
                if n < minimo:
                    continue
                linhas.append(
                    {
                        "conta": chave,
                        "rotulo": POR_CHAVE[chave].rotulo if chave in POR_CHAVE else "",
                        "codigo CVM": codigo,
                        "companhias": n,
                        "% da conta": n / total if total else float("nan"),
                    }
                )
        return pd.DataFrame(linhas)

    def origens_minoritarias(self, limite: float = 0.05) -> pd.DataFrame:
        """Codigos que alimentam uma conta em poucas companhias.

        E onde mora o erro silencioso: a conta que vem de ``3.01`` em 400
        companhias e de outro codigo em duas nao quebra identidade nenhuma.
        """
        tabela = self.tabela_de_origens()
        if tabela.empty:
            return tabela
        return tabela[tabela["% da conta"] < limite].sort_values(
            ["conta", "companhias"], ascending=[True, False]
        )


# ---------------------------------------------------------------------------
# As verificacoes
# ---------------------------------------------------------------------------


def _desvio(obtido: float, esperado: float, escala: float) -> float:
    if not np.isfinite(escala) or escala == 0:
        return float("nan")
    return abs(obtido - esperado) / abs(escala)


# (nome, chaves necessarias, funcao que devolve (obtido, esperado, escala))
def _identidades(valores: pd.Series) -> list[tuple[str, str, float, str]]:
    """Identidades contabeis de um ano, ja com o texto do achado."""
    def v(chave: str) -> float:
        return float(valores.get(chave, np.nan))

    checagens: list[tuple[str, str, float, str]] = []

    ativo, passivo = v("ativo_total"), v("passivo_total")
    if np.isfinite(ativo) and np.isfinite(passivo):
        d = _desvio(ativo, passivo, ativo)
        checagens.append(
            ("ativo = passivo", GRAVE, d, f"ativo {ativo:,.0f} contra passivo {passivo:,.0f}")
        )

    fco, fci, fcf = v("fluxo_operacional"), v("fluxo_investimento"), v("fluxo_financiamento")
    cambio = v("variacao_cambial_caixa")
    variacao = v("variacao_caixa")
    if all(np.isfinite(x) for x in (fco, fci, fcf, variacao)):
        soma = fco + fci + fcf + (cambio if np.isfinite(cambio) else 0.0)
        d = _desvio(soma, variacao, variacao)
        checagens.append(
            (
                "secoes da DFC somam a variacao de caixa",
                GRAVE,
                d,
                f"soma {soma:,.0f} contra variacao {variacao:,.0f}",
            )
        )

    geracao, giro = v("caixa_das_operacoes"), v("variacao_capital_giro")
    outros = v("outros_operacionais")
    reclassificado = v("pagamentos_reclassificados_do_giro")
    # O juro trazido do financiamento reduziu o FCO **sem** aparecer em nenhum
    # dos tres termos, que sao lidos de 6.01.xx. Sem descontar aqui, a auditoria
    # acusava a propria padronizacao: era o caso de 126 companhias, e em
    # Panatlantica a diferenca dava exatamente os R$ 59,75 mi reclassificados.
    do_financiamento = v("juros_pagos_no_financiamento")
    if all(np.isfinite(x) for x in (geracao, giro, fco)):
        # ``outros_operacionais`` (6.01.03) e o terceiro termo, e ele nao e
        # residual: auditada a base, a decomposicao fecha em 96,8% das
        # companhias com ele e em 47,1% sem. Antes de le-lo, esta verificacao
        # acusava 69% da base -- estava errada a verificacao, nao os dados.
        soma = (
            geracao
            + giro
            + (outros if np.isfinite(outros) else 0.0)
            - (reclassificado if np.isfinite(reclassificado) else 0.0)
            - (do_financiamento if np.isfinite(do_financiamento) else 0.0)
        )
        d = _desvio(soma, fco, fco)
        checagens.append(
            (
                "geracao + giro explicam o FCO",
                ATENCAO,
                d,
                f"geracao+giro+outros {soma:,.0f} contra FCO {fco:,.0f}",
            )
        )

    receita, cpv, bruto = v("receita_liquida"), v("custo_produtos_vendidos"), v("lucro_bruto")
    if all(np.isfinite(x) for x in (receita, cpv, bruto)):
        d = _desvio(receita - cpv, bruto, receita)
        checagens.append(
            (
                "receita - CPV = lucro bruto",
                GRAVE,
                d,
                f"receita-CPV {receita - cpv:,.0f} contra bruto {bruto:,.0f}",
            )
        )

    ebit, ebitda_dep = v("ebit"), v("depreciacao_amortizacao")
    if np.isfinite(ebit) and np.isfinite(ebitda_dep) and ebitda_dep < 0:
        checagens.append(
            ("D&A com sinal negativo", ATENCAO, 1.0, f"D&A = {ebitda_dep:,.0f}")
        )

    return checagens


# Conta filha e a conta que deveria conte-la. Nenhuma dessas quebra identidade
# quando esta errada, e e justamente por isso que precisam de verificacao.
# Nao entra aqui: lucro liquido contra lucro bruto. A auditoria acusou 29
# companhias, e as 29 estavam certas -- Itausa tem lucro liquido de R$ 14 bi
# sobre lucro bruto de R$ 2,4 bi porque vive de equivalencia patrimonial, e a
# CESP teve credito fiscal. Verificacao que acusa o legitimo nao e verificacao.
CONTENCOES: tuple[tuple[str, str, str], ...] = (
    ("arrendamento_curto_prazo", "divida_curto_prazo", "arrendamento dentro da divida curta"),
    ("arrendamento_longo_prazo", "divida_longo_prazo", "arrendamento dentro da divida longa"),
    ("debentures_curto_prazo", "divida_curto_prazo", "debentures dentro da divida curta"),
    ("debentures_longo_prazo", "divida_longo_prazo", "debentures dentro da divida longa"),
    ("caixa_equivalentes", "ativo_circulante", "caixa dentro do circulante"),
    ("estoques", "ativo_circulante", "estoques dentro do circulante"),
    ("contas_receber", "ativo_circulante", "recebiveis dentro do circulante"),
    ("divida_curto_prazo", "passivo_circulante", "divida curta dentro do circulante"),
    ("ativo_circulante", "ativo_total", "circulante dentro do ativo"),
    ("patrimonio_liquido", "passivo_total", "patrimonio dentro do passivo"),
)


def _contencoes(valores: pd.Series) -> list[tuple[str, str, float, str]]:
    achados = []
    for filha, pai, descricao in CONTENCOES:
        a, b = float(valores.get(filha, np.nan)), float(valores.get(pai, np.nan))
        if not (np.isfinite(a) and np.isfinite(b)) or b <= 0 or a <= 0:
            continue
        if a > b * (1 + TOLERANCIA):
            achados.append(
                (descricao, GRAVE, (a - b) / b, f"{filha}={a:,.0f} > {pai}={b:,.0f}")
            )
    return achados


# Contas que so fazem sentido com um sinal. Guardadas como magnitude pelo
# vocabulario, entao valor negativo aqui e erro de leitura, nao de publicacao.
SEMPRE_POSITIVAS = (
    "receita_liquida",
    "ativo_total",
    "passivo_total",
    "custo_produtos_vendidos",
    "capex",
    "juros_pagos",
    "arrendamento_curto_prazo",
    "arrendamento_longo_prazo",
)


def _sinais(valores: pd.Series) -> list[tuple[str, str, float, str]]:
    achados = []
    for chave in SEMPRE_POSITIVAS:
        valor = float(valores.get(chave, np.nan))
        if np.isfinite(valor) and valor < 0:
            achados.append(
                (f"{chave} com sinal negativo", ATENCAO, 1.0, f"{chave} = {valor:,.0f}")
            )
    return achados


def auditar(dfs, codigo_cvm: int = 0) -> list[Achado]:
    """Roda todas as verificacoes sobre uma companhia ja importada."""
    achados: list[Achado] = []
    for ano in dfs.anos:
        valores = dfs.valores[ano]
        verificacoes = _identidades(valores) + _contencoes(valores) + _sinais(valores)
        for nome, severidade, desvio, detalhe in verificacoes:
            limite = TOLERANCIA if severidade == GRAVE else 0.05
            if not np.isfinite(desvio) or desvio <= limite:
                continue
            achados.append(
                Achado(
                    codigo_cvm=codigo_cvm,
                    empresa=dfs.empresa,
                    ano=_periodo_do_achado(ano),
                    verificacao=nome,
                    severidade=severidade,
                    detalhe=detalhe,
                    desvio=float(desvio),
                )
            )
    return achados


def _codigo_da_origem(origem: str) -> str:
    """Extrai o codigo CVM de uma anotacao de mapeamento."""
    origem = (origem or "").strip()
    if not origem:
        return "(derivada)"
    if origem.startswith("linhas") or origem.startswith("juros") or origem.startswith("pagamentos"):
        return "(regra somada)"
    primeiro = origem.split(" + ")[0].split(" - ")[0].strip()
    return primeiro or "(sem codigo)"


def auditar_base(
    codigos: list[int],
    anos: list[int],
    cache=None,
    catalogo=None,
    progresso=None,
    importar=None,
) -> Auditoria:
    """Varre a base inteira e devolve achados, cobertura e o de-para de origens.

    ``importar`` troca a fonte sem duplicar esta funcao: por padrao e a DFP
    anual, mas a **serie trimestral** e montada por outro caminho e nunca tinha
    passado por aqui. Recebe ``(codigo, anos, cache, catalogo)`` e devolve
    ``Demonstracoes``.
    """
    if importar is None:
        from .importacao.cvm import importar_cvm

        importar = lambda codigo, anos, cache, catalogo: importar_cvm(  # noqa: E731
            codigo, anos, cache=cache, catalogo=catalogo
        )

    achados: list[Achado] = []
    origens: dict[str, dict[str, int]] = {}
    cobertura: dict[str, int] = {}
    medidas = 0

    for i, codigo in enumerate(codigos, 1):
        if progresso is not None:
            progresso(i, len(codigos))
        try:
            dfs = importar(codigo, anos, cache, catalogo)
        except Exception:
            continue
        medidas += 1
        achados.extend(auditar(dfs, codigo))

        for chave in dfs.valores.index:
            serie = dfs.valores.loc[chave]
            if not serie.notna().any():
                continue
            cobertura[chave] = cobertura.get(chave, 0) + 1
            codigo_origem = _codigo_da_origem(dfs.mapeamento.get(chave, ""))
            origens.setdefault(chave, {})
            origens[chave][codigo_origem] = origens[chave].get(codigo_origem, 0) + 1

    return Auditoria(
        achados=achados, companhias=medidas, origens=origens, cobertura=cobertura
    )


# ---------------------------------------------------------------------------
# Cobertura de regra somada: o que a conta bruta mede errado
# ---------------------------------------------------------------------------

# Capex, juros pagos e dividendos pagos nao existem como linha unica na CVM --
# abaixo dos totais de secao o plano e conta livre --, e sao remontados por soma
# em ``REGRAS_SOMADAS``. Medir a cobertura dividindo "quantas tem a conta" pelo
# total da base **mede a coisa errada**: companhia que nao pagou dividendo nao
# tem linha de dividendo, e contar isso como falha da regra infla o problema e
# esconde o de verdade.
#
# ``MENCIONA`` e deliberadamente largo: a pergunta aqui e "a companhia fala
# disso?", e nao "isto e a conta". Falso positivo vira caso para olhar, que e o
# resultado desejado.
MENCIONA: dict[str, tuple[re.Pattern, tuple[str, ...]]] = {
    "capex": (re.compile(r"imobiliz|intang[ií]|ativo fixo|permanente", re.I), ("6.02",)),
    "juros_pagos": (re.compile(r"juro|encargo financeir", re.I), ("6.01", "6.03")),
    "dividendos_pagos": (
        re.compile(r"dividendo|capital pr[óo]prio|\bjcp\b", re.I),
        ("6.01", "6.03"),
    ),
}


@dataclass(frozen=True)
class CoberturaSomada:
    """Cobertura de uma conta remontada por soma, com o denominador certo.

    ``ausente`` sao as companhias em que **nenhuma linha da DFC menciona o
    conceito** -- nao ha o que achar, e elas nao pertencem ao denominador.
    ``escapou`` sao aquelas em que ha linha mencionando e a regra nao pegou. So
    esta ultima e defeito.
    """

    conta: str
    achou: int
    ausente: int
    escapou: int
    rotulos_que_escapam: dict[str, int] = field(default_factory=dict)

    @property
    def cobertura(self) -> float:
        """Sobre quem tem o conceito, e nao sobre a base inteira."""
        com_conceito = self.achou + self.escapou
        return self.achou / com_conceito if com_conceito else float("nan")

    @property
    def cobertura_aparente(self) -> float:
        """A conta ingenua, guardada para mostrar o quanto ela engana."""
        total = self.achou + self.ausente + self.escapou
        return self.achou / total if total else float("nan")


def medir_cobertura_somada(
    codigos: list[int],
    ano: int,
    cache=None,
    catalogo=None,
    progresso=None,
) -> list[CoberturaSomada]:
    """Separa "a regra falhou" de "a companhia nao tem isso".

    Medido no DFP consolidado de 2024, a diferenca entre as duas leituras nao e
    detalhe -- em dividendos pagos, **172 das 467 companhias simplesmente nao
    pagaram dividendo**:

    ======================  ==========  =========  =======================
    conta                   aparente    real       o que explica a diferenca
    ======================  ==========  =========  =======================
    capex                   88%         **96%**    35 sem capex nenhum
    juros_pagos             76%         **86%**    55 nao abrem juro pago
    dividendos_pagos        61%         **96%**    172 nao pagaram dividendo
    ======================  ==========  =========  =======================

    E a maior parte do que ainda escapa e a regra **recusando certo**: venda de
    imobilizado nao e capex, JCP nao e juro, dividendo recebido nao e dividendo
    pago. Das 131 linhas de "juros sobre emprestimos" que sobram, **104 estao em
    ``6.01.01``** -- ajuste ao lucro, competencia e nao caixa. Soma-las contaria
    despesa que nunca virou desembolso.
    """
    from .importacao.cvm import importar_cvm

    resultado: dict[str, dict] = {
        chave: {"achou": 0, "ausente": 0, "escapou": 0, "rotulos": {}}
        for chave in MENCIONA
    }

    for i, codigo in enumerate(codigos, 1):
        if progresso is not None:
            progresso(i, len(codigos))
        try:
            dfs = importar_cvm(codigo, [ano], cache=cache, catalogo=catalogo)
        except Exception:
            continue
        arvore = dfs.detalhe
        if arvore is None or arvore.empty:
            continue

        for chave, (padrao, prefixos) in MENCIONA.items():
            valor = _valor(dfs, chave, ano)
            if np.isfinite(valor) and valor != 0:
                resultado[chave]["achou"] += 1
                continue

            candidatas = _linhas_que_mencionam(arvore, ano, padrao, prefixos)
            if not candidatas:
                resultado[chave]["ausente"] += 1
                continue
            resultado[chave]["escapou"] += 1
            for rotulo in candidatas:
                r = resultado[chave]["rotulos"]
                r[rotulo.strip()] = r.get(rotulo.strip(), 0) + 1

    return [
        CoberturaSomada(
            conta=chave,
            achou=dados["achou"],
            ausente=dados["ausente"],
            escapou=dados["escapou"],
            rotulos_que_escapam=dados["rotulos"],
        )
        for chave, dados in resultado.items()
    ]


def _linhas_que_mencionam(
    arvore, ano: int, padrao: re.Pattern, prefixos: tuple[str, ...]
) -> list[str]:
    """Rotulos da arvore que falam do conceito, **com valor**, na secao certa.

    **Linha zerada nao e escape.** Muita companhia publica "Dividendos pagos"
    com valor zero no ano em que nao pagou; conta-la como "a regra nao pegou"
    repoe, por outro caminho, o mesmo erro que esta medicao existe para corrigir
    -- os escapes de dividendos passam de 12 para 90 sem este filtro.
    """
    if ano not in arvore.columns:
        return []
    codigos = arvore["codigo"].astype(str)
    na_secao = codigos.str.startswith(tuple(p + "." for p in prefixos))
    detalhada = codigos.str.count(r"\.") >= 2
    fala = arvore["rotulo"].astype(str).str.contains(padrao)
    valores = pd.to_numeric(arvore[ano], errors="coerce")
    tem_valor = valores.notna() & (valores != 0)
    return [
        str(r).strip()
        for r in arvore.loc[na_secao & detalhada & fala & tem_valor, "rotulo"]
    ]


def _valor(dfs, chave: str, ano: int) -> float:
    try:
        return float(dfs.valor(chave, ano))
    except Exception:
        return float("nan")


@dataclass(frozen=True)
class ContaSomadaNaCompanhia:
    """O estado de uma conta remontada por soma, numa companhia so.

    A versao de base responde "a regra cobre quanto?"; esta responde a pergunta
    que o analista faz olhando **a empresa dele**: o app achou capex, e se nao
    achou, e porque a companhia nao tem ou porque a regra nao alcancou?

    A distincao decide o que fazer: **ausente** nao pede nada, **escapou** pede
    mapeamento manual da linha.
    """

    conta: str
    valor: float
    origem: str
    linhas_que_mencionam: list[str]

    @property
    def situacao(self) -> str:
        if np.isfinite(self.valor) and self.valor != 0:
            return "encontrada"
        return "escapou" if self.linhas_que_mencionam else "ausente"


def conferir_contas_somadas(demonstracoes, ano: int | None = None) -> list[ContaSomadaNaCompanhia]:
    """Capex, juros pagos e dividendos pagos: achou, nao tem, ou escapou?

    Capex, juro pago e dividendo pago **nao existem como linha unica** na CVM --
    abaixo dos totais de secao o plano e conta livre --, e sao remontados por
    soma. Quando a soma nao acha nada, a tela precisa dizer **qual dos dois
    motivos**: companhia que nao pagou dividendo nao tem linha de dividendo, e
    tratar isso como falha da leitura manda o analista procurar o que nao existe.

    Medido na base de 2024, a diferenca entre os dois motivos e quase todo o
    problema: em dividendos pagos, **172 das 467 companhias simplesmente nao
    pagaram**, e a cobertura vai de 61% aparente para 96% real.
    """
    anos = list(demonstracoes.anos)
    if not anos:
        return []
    ano = ano if ano is not None else anos[-1]
    arvore = getattr(demonstracoes, "detalhe", None)

    saida = []
    for chave, (padrao, prefixos) in MENCIONA.items():
        valor = _valor(demonstracoes, chave, ano)
        mencionam: list[str] = []
        if not (np.isfinite(valor) and valor != 0) and arvore is not None and not arvore.empty:
            mencionam = _linhas_que_mencionam(arvore, ano, padrao, prefixos)
        saida.append(
            ContaSomadaNaCompanhia(
                conta=chave,
                valor=valor,
                origem=demonstracoes.mapeamento.get(chave, ""),
                linhas_que_mencionam=mencionam,
            )
        )
    return saida


# ---------------------------------------------------------------------------
# Linha de comando
# ---------------------------------------------------------------------------

# `python -m valuation.auditoria` estava documentado como a forma de rodar isto,
# e o modulo nao tinha entrada nenhuma: o comando importava, saia com codigo 0 e
# **nao imprimia nada**. Falha silenciosa em ferramenta de verificacao e o pior
# caso possivel -- quem roda le "sem achados" onde deveria ler "nao rodou".


# Zip vazio nao conta -- a guarda de `pares.safra()` ja separa isso --, mas o
# exercicio **aberto** e outro caso e passa por ela. Contagem por exercicio no
# cache, medida em agosto de 2026:
#
#     2023: 474    2024: 467    2025: 437    2026: **7**
#
# O arquivo de 2026 existe e tem conteudo de verdade: sao as companhias cujo
# exercicio social fecha no meio do ano. Auditar essas 7 anunciando ter varrido
# a base e o modo de falha que esta ferramenta existe para nao ter, entao o
# padrao recua para o ultimo exercicio fechado. `--anos 2026` continua valendo
# para quem quiser exatamente aquelas 7.
FRACAO_DE_EXERCICIO_FECHADO = 0.5


def _ultimo_exercicio_fechado(baixados: list[int], cache) -> int:
    """O ultimo exercicio com base publicada, e nao o ultimo arquivo baixado."""
    from .importacao.cvm import listar_companhias_do_ano

    if len(baixados) < 2:
        return baixados[-1]
    # So os dois ultimos sao abertos: ler todos custaria um zip por exercicio.
    ultimo, anterior = baixados[-1], baixados[-2]
    quantas = len(listar_companhias_do_ano(ultimo, cache=cache))
    antes = len(listar_companhias_do_ano(anterior, cache=cache))
    if antes and quantas < antes * FRACAO_DE_EXERCICIO_FECHADO:
        return anterior
    return ultimo


def _cli(argv: list[str] | None = None) -> int:
    import argparse
    from pathlib import Path

    from .importacao.cvm import carregar_cadastro, listar_companhias_do_ano

    analisador = argparse.ArgumentParser(
        prog="python -m valuation.auditoria",
        description="Varre a base da CVM e reporta achados, cobertura e o de-para de origens.",
    )
    analisador.add_argument(
        "--anos",
        default="",
        help="Exercícios separados por vírgula (padrão: o último baixado no cache).",
    )
    analisador.add_argument(
        "--cache",
        default=str(Path.home() / ".cache" / "valuation" / "cvm"),
        help="Pasta com os zips da CVM já baixados.",
    )
    analisador.add_argument(
        "--limite", type=int, default=0, help="Audita só as N primeiras companhias."
    )
    analisador.add_argument(
        "--csv", default="", help="Grava a tabela de achados neste arquivo."
    )
    args = analisador.parse_args(argv)

    cache = Path(args.cache)
    if args.anos:
        anos = [int(a) for a in args.anos.split(",") if a.strip()]
    else:
        from .pares import _anos_de_dfp_no_cache

        baixados = _anos_de_dfp_no_cache(cache)
        if not baixados:
            print(f"Nenhum zip de DFP com conteúdo em {cache}. Importe uma companhia primeiro.")
            return 1
        anos = [_ultimo_exercicio_fechado(baixados, cache)]

    catalogo = carregar_cadastro(cache / "cad_cia_aberta.csv")
    codigos = listar_companhias_do_ano(anos[-1], cache=cache)
    if args.limite:
        codigos = codigos[: args.limite]

    print(f"Auditando {len(codigos)} companhias em {', '.join(str(a) for a in anos)}…")

    def progresso(i: int, total: int) -> None:
        if i % 50 == 0 or i == total:
            print(f"  {i}/{total}", flush=True)

    resultado = auditar_base(
        codigos, anos, cache=cache, catalogo=catalogo, progresso=progresso
    )

    tabela = resultado.tabela()
    print(f"\n{len(tabela)} achados em {resultado.companhias} companhias lidas.")
    if not tabela.empty:
        print()
        print(tabela.to_string(index=False, max_colwidth=60))
    if args.csv:
        tabela.to_csv(args.csv, index=False, encoding="utf-8")
        print(f"\nTabela gravada em {args.csv}")

    # Achado nao e falha de execucao: a base tem inconsistencia publicada, e
    # sair com codigo diferente de zero faria a ferramenta parecer quebrada.
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_cli())

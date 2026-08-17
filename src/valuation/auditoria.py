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

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .importacao.esquema import POR_CHAVE

# Tolerancia relativa para uma identidade ser considerada fechada. Acima disto
# ha erro de leitura, nao arredondamento de centavos.
TOLERANCIA = 0.01

GRAVE = "grave"
ATENCAO = "atencao"


@dataclass(frozen=True)
class Achado:
    """Uma divergencia encontrada numa companhia."""

    codigo_cvm: int
    empresa: str
    ano: int
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
                    ano=int(ano),
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
) -> Auditoria:
    """Varre a base inteira e devolve achados, cobertura e o de-para de origens."""
    from .importacao.cvm import importar_cvm

    achados: list[Achado] = []
    origens: dict[str, dict[str, int]] = {}
    cobertura: dict[str, int] = {}
    medidas = 0

    for i, codigo in enumerate(codigos, 1):
        if progresso is not None:
            progresso(i, len(codigos))
        try:
            dfs = importar_cvm(codigo, anos, cache=cache, catalogo=catalogo)
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

"""A secao de investimento aberta: o que e capex e o que so passa por ali.

O app tinha ``capex`` como conta unica e o resto do ``6.02`` sumia -- e o resto e
metade da secao. Medido no DFP consolidado de 2024, a secao de investimento tem
**3.530 linhas** e a regra de capex aceita 673: as outras 2.857 nao desapareciam
do fluxo (``fluxo_investimento`` continua sendo o total publicado), mas ninguem
via **do que** elas eram feitas.

A pergunta que originou isto: *"existem coisas lancadas no FCI que nao sao
capex, como resgates e aplicacoes em TVM"*. Sao, e em volume: 381 das linhas de
2024 falam de aplicacao financeira, TVM ou resgate. Elas ja eram corretamente
recusadas pela regra de capex -- **zero delas entra** --, mas ficavam num balde
sem nome.

O que muda com esta decomposicao
--------------------------------

``capex`` responde "quanto foi para ativo fixo". Ela nao responde as tres
perguntas que vem junto e mudam a leitura do fluxo:

* **Comprou empresa ou comprou maquina?** Aquisicao de participacao consome caixa
  de investimento igual, e nao repoe ativo operacional -- projetar capex a partir
  de um ano com aquisicao superestima a manutencao para sempre.
* **O caixa "investido" saiu da empresa?** Aplicar em TVM e mover caixa de bolso,
  nao investir: o **delta** (aplicacoes menos resgates) e o que de fato deixou o
  caixa disponivel, e no ano seguinte costuma voltar.
* **Quanto sobra sem nome?** Um balde de "outros" grande e sinal de que a leitura
  nao entendeu a companhia, e ele aparece em vez de ser diluido nos demais.

A regra que esta peca segue, como a ponte do FCO
------------------------------------------------

**Ela tem de fechar com o total publicado.** Uma decomposicao que nao reconstroi
o ``6.02`` descreve outra companhia; quando nao fecha, a diferenca vira uma linha
com nome (``nao_classificado``) em vez de ser escondida num componente.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np
import pandas as pd

# Os padroes sao aplicados **na ordem em que aparecem aqui**, e a ordem e a
# decisao: "Aquisicao de participacao societaria" fala de aquisicao e de
# participacao, e tem de cair em participacoes e nao em capex. O primeiro que
# casa leva a linha.
#
# TVM vem antes de tudo porque "Aplicacoes financeiras" contem "aplicac", que e
# verbo de capex -- e a razao de a regra de capex exigir que o rotulo cite
# imobilizado ou intangivel.
CATEGORIAS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "tvm",
        re.compile(
            r"aplica[çc][õo]?[eé]?s?\s+financeir|t[íi]tulos e valores|\bTVM\b|"
            r"valores mobili|resgate|aplica[çc][ãa]o financeira|"
            r"t[íi]tulos p[úu]blicos|certificad[oa]s? de dep[óo]sito",
            re.I,
        ),
    ),
    (
        "participacoes",
        re.compile(
            r"participa[çc][ãa]o|controlada|coligada|combina[çc][ãa]o de neg|"
            r"aquisi[çc][ãa]o de empresa|incorpora[çc][ãa]o|societ[áa]ri|"
            r"investiment[oa]s? em|jv\b|joint",
            re.I,
        ),
    ),
    ("imobilizado", re.compile(r"imobiliz|ativo fixo|permanente", re.I)),
    ("intangivel", re.compile(r"intang[íi]|software|[áa]gio|goodwill", re.I)),
)

# Verbos que marcam **entrada** de caixa dentro da secao de investimento. Nao
# mudam a classificacao -- venda de imobilizado continua sendo imobilizado --,
# mas separam capex de desinvestimento dentro do mesmo balde.
_ENTRADA = re.compile(
    r"venda|aliena[çc]|baixa|recebiment|recebid|desinvestiment|dividendos? receb",
    re.I,
)


@dataclass(frozen=True)
class ComposicaoDoInvestimento:
    """A secao ``6.02`` aberta por natureza, com o resto nomeado.

    Todos os valores guardam o **sinal publicado**: saida negativa, entrada
    positiva. E deliberado -- a secao inteira soma para o total publicado, e
    inverter sinal por componente quebraria a identidade que justifica a peca.
    """

    imobilizado: float
    intangivel: float
    participacoes: float
    outros_capex: float
    tvm_liquido: float
    outros_nao_capex: float
    nao_classificado: float
    total_publicado: float
    ano: int | str

    @property
    def capex(self) -> float:
        """Ativo fixo e intangivel: o que repoe e amplia a operacao.

        **Participacao nao entra.** Comprar empresa consome o mesmo caixa e nao
        repoe ativo operacional -- projetar manutencao a partir de um ano com
        aquisicao superestima o capex para sempre.
        """
        return self.imobilizado + self.intangivel + self.outros_capex

    @property
    def soma(self) -> float:
        return (
            self.capex
            + self.participacoes
            + self.tvm_liquido
            + self.outros_nao_capex
            + self.nao_classificado
        )

    @property
    def fecha(self) -> bool:
        """A decomposicao reconstroi o total publicado?

        Por construcao ela fecha, porque ``nao_classificado`` absorve o residuo.
        O que esta propriedade responde e se o **residuo e material**: acima de
        1% do total, a leitura nao entendeu a companhia e o numero por natureza
        nao deve ser usado sem olhar as linhas.
        """
        if not np.isfinite(self.total_publicado) or self.total_publicado == 0:
            return not self.nao_classificado
        return abs(self.nao_classificado / self.total_publicado) <= 0.01

    def linhas(self) -> list[tuple[str, float]]:
        """Os componentes na ordem em que se leem, com o total no fim."""
        return [
            ("Aquisição de imobilizado", self.imobilizado),
            ("Aquisição de intangível", self.intangivel),
            ("Aquisição de investimentos (participações)", self.participacoes),
            ("Outros capex", self.outros_capex),
            ("Δ TVM (aplicações − resgates)", self.tvm_liquido),
            ("Outros, não capex", self.outros_nao_capex),
            ("Não classificado", self.nao_classificado),
            ("= Fluxo de investimento publicado", self.total_publicado),
        ]


def _folhas_do_investimento(detalhe: pd.DataFrame, ano) -> list[tuple[list[str], float]]:
    """As linhas mais externas de ``6.02``, para nao somar pai e filha.

    A CVM publica a arvore inteira -- ``6.02.01`` e ``6.02.01.01`` no mesmo
    arquivo --, e somar as duas conta o mesmo desembolso duas vezes. Fica so a
    linha que **nao tem descendente publicado**, que e a mesma regra que
    ``_somar_arrendamento_fora_da_divida`` usa.
    """
    codigos = [
        str(c) for c in detalhe["codigo"] if str(c).startswith("6.02.")
    ]
    externas = [
        c
        for c in codigos
        if not any(o != c and o.startswith(c + ".") for o in codigos)
    ]
    escolhidas = set(externas)

    # **A categoria costuma estar no pai, e o detalhe na folha.** A CVM publica
    # `6.02.01 Imobilizado` com filhas `Aquisicao de maquinas` e `Aquisicao de
    # edificacoes` -- nenhuma das duas cita imobilizado, e classificar so pela
    # folha as jogaria em "outros". O rotulo de cada linha vem acompanhado dos
    # **rotulos dos ancestrais**, do mais proximo ao mais distante, para a
    # classificacao poder herdar quando a folha nao se identifica.
    por_codigo = {
        str(linha["codigo"]): str(linha["rotulo"]) for _, linha in detalhe.iterrows()
    }

    def com_ancestrais(codigo: str) -> list[str]:
        rotulos = [por_codigo.get(codigo, "")]
        partes = codigo.split(".")
        for corte in range(len(partes) - 1, 1, -1):
            pai = ".".join(partes[:corte])
            if pai in por_codigo:
                rotulos.append(por_codigo[pai])
        return rotulos

    linhas = []
    for _, linha in detalhe.iterrows():
        codigo = str(linha["codigo"])
        if codigo not in escolhidas:
            continue
        valor = linha.get(ano)
        if valor is None or not np.isfinite(valor):
            continue
        linhas.append((com_ancestrais(codigo), float(valor)))
    return linhas


def compor_investimento(demonstracoes, ano=None) -> ComposicaoDoInvestimento | None:
    """Abre a secao de investimento por natureza. ``None`` sem arvore publicada.

    Precisa do ``detalhe`` porque **a abertura nao existe em conta canonica**: o
    vocabulario tem ``capex`` e ``fluxo_investimento``, e o que esta no meio so
    aparece nas linhas que a companhia publicou.
    """
    detalhe = getattr(demonstracoes, "detalhe", None)
    if detalhe is None or detalhe.empty:
        return None
    ano = ano if ano is not None else demonstracoes.ano_base
    if ano is None or ano not in detalhe.columns:
        return None

    linhas = _folhas_do_investimento(detalhe, ano)
    if not linhas:
        return None

    baldes = {
        "imobilizado": 0.0,
        "intangivel": 0.0,
        "participacoes": 0.0,
        "outros_capex": 0.0,
        "tvm": 0.0,
        "outros_nao_capex": 0.0,
    }
    for rotulos, valor in linhas:
        # A folha decide; so quando ela nao se identifica e que o pai decide por
        # ela. A ordem importa: `Aplicacoes financeiras` dentro de um bloco
        # chamado `Imobilizado` continua sendo TVM.
        categoria = None
        for rotulo in rotulos:
            categoria = next(
                (nome for nome, padrao in CATEGORIAS if padrao.search(rotulo)), None
            )
            if categoria is not None:
                break
        rotulo = rotulos[0]
        if categoria == "tvm":
            baldes["tvm"] += valor
        elif categoria == "participacoes":
            baldes["participacoes"] += valor
        elif categoria in ("imobilizado", "intangivel"):
            # Venda de imobilizado nao e capex: mesma natureza, direcao oposta.
            # Ela vai para "outros, nao capex" para o capex nao sair liquido de
            # desinvestimento -- projetar manutencao a partir de um numero
            # liquido subestima o desembolso.
            if _ENTRADA.search(rotulo):
                baldes["outros_nao_capex"] += valor
            else:
                baldes[categoria] += valor
        else:
            baldes["outros_nao_capex"] += valor

    try:
        total = float(demonstracoes.valor("fluxo_investimento", ano))
    except Exception:  # noqa: BLE001 -- sem a conta, o total vem da soma
        total = float("nan")
    if not np.isfinite(total):
        total = sum(baldes.values())

    return ComposicaoDoInvestimento(
        imobilizado=baldes["imobilizado"],
        intangivel=baldes["intangivel"],
        participacoes=baldes["participacoes"],
        outros_capex=baldes["outros_capex"],
        tvm_liquido=baldes["tvm"],
        outros_nao_capex=baldes["outros_nao_capex"],
        nao_classificado=total - sum(baldes.values()),
        total_publicado=total,
        ano=ano,
    )

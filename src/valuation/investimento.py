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

# **Direcao e um eixo proprio, e nao um detalhe de imobilizado.** A primeira
# versao so marcava entrada dentro do balde de imobilizado, e por isso a Ultrapar
# saia com venda zero: a linha dela e "Caixa gerado com a venda de
# **investimento** e bens", que caia em participacoes sem que ninguem notasse
# que era entrada. Nem tudo que gera caixa no FCI e venda de ativo fixo -- ha
# venda de participacao, dividendo e juro recebido de investida, reducao de
# capital em controlada. Nada disso e capex, e tudo isso entra no caixa.
_ENTRADA = re.compile(
    r"venda|aliena[çc]|baixa|recebiment|recebid|desinvestiment|"
    r"redu[çc][ãa]o de capital|caixa gerado|dividendos?|juros sobre capital|jcp|"
    r"resgate de investiment",
    re.I,
)
# Proventos de investida: entram no caixa e nao sao venda de nada.
_PROVENTOS = re.compile(r"dividendos?|juros sobre capital|jcp|rendiment", re.I)


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
    venda_de_ativos: float
    venda_de_investimentos: float
    proventos_recebidos: float
    outras_entradas: float
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
    def entradas(self) -> float:
        """Tudo que **gerou caixa** na secao de investimento.

        Nao e so venda de imobilizado: ha venda de participacao, dividendo e
        juro recebido de investida, reducao de capital em controlada. Nenhum
        deles e capex, e todos entram no caixa -- ignora-los subestima o que a
        companhia gerou.
        """
        return (
            self.venda_de_ativos
            + self.venda_de_investimentos
            + self.proventos_recebidos
            + self.outras_entradas
        )

    def caixa_livre(self, fluxo_operacional: float) -> tuple[float, float]:
        """Fluxo livre sem e **com** a venda de ativo.

        O app calculava `FCO - capex` e parava ali. Venda de imobilizado nao
        reduz o capex -- capex liquido de desinvestimento subestima a
        manutencao --, **mas o dinheiro entrou**, e ignora-lo subestima o caixa
        que a companhia gerou.

        Medido no DFP consolidado, exercicios de 2021 a 2024: **180 companhias**
        tem venda de ativo na secao de investimento e **114 delas (63%) a
        repetem em tres ou mais dos quatro exercicios** -- nao e evento pontual
        na maioria. Em **34 de 161** medidas ela passa de 10% do fluxo livre; na
        Ultrapar sao R$ 1.386,3 mi contra R$ 682,8 mi de FCL (203%), na Cosan
        128%.

        Devolve os dois numeros em vez de escolher: o primeiro e o caixa da
        operacao depois de repor ativo, o segundo e o caixa que de fato sobrou.
        Uma companhia que **recicla ativo como parte do negocio** -- shopping,
        locadora, incorporadora -- so se le pelo segundo; uma que vendeu a sede
        uma vez, so pelo primeiro. Qual dos dois vale e leitura de quem conhece
        a companhia, e por isso a peca nao escolhe.
        """
        sem = fluxo_operacional - abs(self.capex)
        return sem, sem + self.entradas

    @property
    def soma(self) -> float:
        return (
            self.capex
            + self.participacoes
            + self.entradas
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
            ("(+) Venda de ativo (imobilizado, intangível)", self.venda_de_ativos),
            ("(+) Venda de investimentos (participações)", self.venda_de_investimentos),
            ("(+) Dividendos e juros recebidos", self.proventos_recebidos),
            ("(+) Outras entradas", self.outras_entradas),
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
        "venda_de_ativos": 0.0,
        "venda_de_investimentos": 0.0,
        "proventos_recebidos": 0.0,
        "outras_entradas": 0.0,
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
        # **Direcao antes de natureza, exceto no TVM.** O TVM entra pelo delta --
        # aplicar e resgatar sao a mesma conta indo e voltando --, mas nas
        # demais a direcao decide o balde: aquisicao consome caixa e venda
        # gera, e somar as duas daria um liquido que esconde as duas pontas.
        e_entrada = bool(_ENTRADA.search(rotulo))
        if categoria == "tvm":
            baldes["tvm"] += valor
        elif _PROVENTOS.search(rotulo):
            # Dividendo e juro de investida entram no caixa e nao sao venda de
            # nada -- linha propria, porque recorrem em quem tem coligada.
            baldes["proventos_recebidos"] += valor
        elif e_entrada and categoria == "participacoes":
            baldes["venda_de_investimentos"] += valor
        elif e_entrada and categoria in ("imobilizado", "intangivel"):
            # Venda de ativo **nao abate o capex** -- capex liquido de
            # desinvestimento subestima a manutencao --, mas o dinheiro entrou.
            baldes["venda_de_ativos"] += valor
        elif e_entrada:
            baldes["outras_entradas"] += valor
        elif categoria == "participacoes":
            baldes["participacoes"] += valor
        elif categoria in ("imobilizado", "intangivel"):
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
        venda_de_ativos=baldes["venda_de_ativos"],
        venda_de_investimentos=baldes["venda_de_investimentos"],
        proventos_recebidos=baldes["proventos_recebidos"],
        outras_entradas=baldes["outras_entradas"],
        tvm_liquido=baldes["tvm"],
        outros_nao_capex=baldes["outros_nao_capex"],
        nao_classificado=total - sum(baldes.values()),
        total_publicado=total,
        ano=ano,
    )


# Fracao dos exercicios em que a entrada precisa aparecer para deixar de ser
# evento. **Nao e lei**: e o corte que separa "vendeu a sede uma vez" de
# "recicla ativo como parte do negocio", e a leitura final e de quem conhece a
# companhia. Medido no DFP consolidado de 2021 a 2024: das 180 companhias com
# venda de ativo no FCI, **114 (63%) a repetem em tres dos quatro exercicios**.
FRACAO_QUE_RECORRE = 0.60


@dataclass(frozen=True)
class RecorrenciaDaEntrada:
    """Uma natureza de entrada, com quantos exercicios a trouxeram."""

    natureza: str
    anos_com: int
    anos_medidos: int
    mediana: float
    ultimo: float

    @property
    def recorre(self) -> bool:
        if not self.anos_medidos:
            return False
        return self.anos_com / self.anos_medidos >= FRACAO_QUE_RECORRE

    @property
    def leitura(self) -> str:
        if self.recorre:
            return (
                f"aparece em {self.anos_com} dos {self.anos_medidos} exercícios — "
                "**parece parte do negócio**, e a geração de caixa sem ela fica "
                "subestimada"
            )
        return (
            f"aparece em {self.anos_com} dos {self.anos_medidos} exercícios — "
            "**parece evento**, e projetar com ela superestima"
        )


NATUREZAS_DE_ENTRADA = (
    ("venda_de_ativos", "Venda de ativo (imobilizado, intangível)"),
    ("venda_de_investimentos", "Venda de investimentos (participações)"),
    ("proventos_recebidos", "Dividendos e juros recebidos"),
    ("outras_entradas", "Outras entradas"),
)


def recorrencia_das_entradas(demonstracoes) -> list[RecorrenciaDaEntrada]:
    """Quais entradas do FCI **recorrem**, e quais parecem evento.

    A distincao muda o que se faz com o numero, e nao so como se le: uma
    companhia que recicla ativo como parte do negocio -- shopping, locadora,
    incorporadora -- gera caixa ali todo ano, e ler o fluxo livre sem isso a
    subestima. Uma que vendeu a sede uma vez tem o oposto: projetar com a venda
    superestima.

    **Os dados nao separam os dois casos, a frequencia separa** -- e mesmo ela
    apenas sugere. Por isso a peca devolve a contagem e a leitura, e nao um
    veredito: quem conhece a companhia decide.

    Devolve so as naturezas que apareceram ao menos uma vez; natureza que nunca
    apareceu nao e informacao, e listaria quatro linhas vazias para a maioria.
    """
    anos = [a for a in getattr(demonstracoes, "anos", []) or []]
    if not anos:
        return []

    por_natureza: dict[str, list[float]] = {c: [] for c, _ in NATUREZAS_DE_ENTRADA}
    medidos = 0
    for ano in anos:
        composicao = compor_investimento(demonstracoes, ano)
        if composicao is None:
            continue
        medidos += 1
        for chave, _ in NATUREZAS_DE_ENTRADA:
            por_natureza[chave].append(float(getattr(composicao, chave)))

    resultado = []
    for chave, rotulo in NATUREZAS_DE_ENTRADA:
        valores = por_natureza[chave]
        com = [v for v in valores if abs(v) > 0]
        if not com:
            continue
        resultado.append(
            RecorrenciaDaEntrada(
                natureza=rotulo,
                anos_com=len(com),
                anos_medidos=medidos,
                mediana=float(np.median(com)),
                ultimo=valores[-1] if valores else 0.0,
            )
        )
    return resultado

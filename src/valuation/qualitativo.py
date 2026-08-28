"""Evidencia quantitativa para as perguntas qualitativas. Nao as respostas.

A tentacao, num app que ja le a CVM inteira, e escrever "a empresa tem vantagem
competitiva solida" e mandar para o cliente. Isso seria inventar: nenhuma conta
deste repositorio sabe se a marca e forte, se o contrato de concessao vence em
2031 ou se o concorrente novo levantou capital semana passada.

O que da para fazer -- e e a metade que consome tempo -- e **reunir a evidencia
que cada pergunta pede**. Rivalidade se discute melhor sabendo se a margem e
estavel ha cinco anos ou oscila dez pontos; barreira de entrada se discute
melhor sabendo se o ROIC ficou acima do WACC em todos os anos ou em nenhum.
A leitura continua sendo de quem tem o julgamento, e por isso cada bloco sai com
o campo de resposta em branco.

Um cuidado que vale explicar: **cada forca declara o que os dados nao alcancam**.
Ameaca de substitutos nao tem contrapartida contabil nenhuma, e omitir a secao
faria parecer que a pergunta nao existe. Ela aparece dizendo que so o analista
responde.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from . import referencias

# Anos com ROIC acima do WACC a partir dos quais o retorno excedente deixa de
# parecer sorte de ciclo. Nao e prova de fosso -- e o que faz a pergunta valer.
ANOS_DE_RETORNO_EXCEDENTE = 3
# Oscilacao de margem, em pontos percentuais, que separa negocio estavel de
# negocio exposto. Faixa de leitura, nao lei.
MARGEM_ESTAVEL = 0.03


@dataclass(frozen=True)
class Evidencia:
    """Uma pergunta do framework, com o que os numeros dizem sobre ela."""

    tema: str
    pergunta: str
    medido: list[str] = field(default_factory=list)
    limite: str = ""

    @property
    def tem_dado(self) -> bool:
        return bool(self.medido)


def _pct(valor: float, casas: int = 1) -> str:
    if not np.isfinite(valor):
        return "n/d"
    return f"{valor * 100:.{casas}f}%".replace(".", ",")


def _dias(valor: float) -> str:
    if not np.isfinite(valor):
        return "n/d"
    return f"{valor:,.0f} dias".replace(",", ".")


def _numero(valor: float, casas: int = 2) -> str:
    if not np.isfinite(valor):
        return "n/d"
    return f"{valor:,.{casas}f}".replace(",", "@").replace(".", ",").replace("@", ".")


def _serie(analise, nome: str):
    return analise.linha(nome).replace([np.inf, -np.inf], np.nan).dropna()


def _com_referencia(indicador: str, valor: float, analise=None) -> str:
    """O percentil na base, colado ao numero -- **quando ele se aplica**.

    `analise` existe so para reconhecer banco e seguradora: o universo de
    referencia os exclui de proposito, entao um percentil ali compara a
    instituicao com 445 companhias a que ela nao pertence. O ponto de corte fica
    aqui, e nao em cada bloco, porque o percentil aparece em oito lugares e
    esquecer um deles devolveria justamente o numero que parece informacao e
    nao e.
    """
    if analise is not None and _e_financeira(analise):
        return ""
    onde = referencias.descrever(indicador, valor)
    return f" — {onde}" if onde else ""


def _rivalidade(analise) -> Evidencia:
    medido = []
    margens = _serie(analise, "Margem EBITDA")
    if not margens.empty:
        mediana = float(margens.median())
        medido.append(
            f"Margem EBITDA mediana de {_pct(mediana)}"
            f"{_com_referencia('Margem EBITDA', mediana, analise)}."
        )
    if len(margens) >= 3:
        amplitude = float(margens.max() - margens.min())
        estavel = amplitude <= MARGEM_ESTAVEL
        medido.append(
            f"Entre {_pct(float(margens.min()))} e {_pct(float(margens.max()))} no "
            f"período — variação de {_pct(amplitude)}, o que é "
            + ("estreito para um negócio exposto a preço." if estavel else
               "largo o bastante para a margem depender de ciclo ou de mix.")
        )
    return Evidencia(
        tema="Rivalidade entre concorrentes",
        pergunta=(
            "A empresa consegue defender preço, ou a concorrência dita a margem?"
        ),
        medido=medido,
        limite=(
            "Margem estável pode vir de disciplina de preço, de contrato indexado "
            "ou de um ciclo favorável que ainda não virou. Os números não separam "
            "as três."
        ),
    )


def _fornecedores(analise) -> Evidencia:
    medido = []
    pmp = analise.mediana("Prazo medio de pagamento (dias)")
    if np.isfinite(pmp):
        medido.append(f"Paga fornecedores em {_dias(pmp)}, na mediana.")
    bruta = analise.mediana("Margem bruta")
    if np.isfinite(bruta):
        medido.append(f"Margem bruta mediana de {_pct(bruta)}.")
    return Evidencia(
        tema="Poder dos fornecedores",
        pergunta="Quem fica com a margem quando o insumo sobe?",
        medido=medido,
        limite=(
            "Prazo longo pode ser poder de barganha ou dificuldade de pagar. "
            "Concentração de fornecedores e cláusulas de repasse não estão nas "
            "demonstrações padronizadas."
        ),
    )


def _compradores(analise) -> Evidencia:
    medido = []
    pmr = analise.mediana("Prazo medio de recebimento (dias)")
    if np.isfinite(pmr):
        medido.append(f"Recebe dos clientes em {_dias(pmr)}, na mediana.")
    ciclo = analise.mediana("Ciclo de conversao de caixa (dias)")
    if np.isfinite(ciclo):
        leitura = (
            "o cliente financia a operação" if ciclo < 0 else "a empresa financia o cliente"
        )
        medido.append(f"Ciclo de caixa de {_dias(ciclo)} — {leitura}.")
    return Evidencia(
        tema="Poder dos compradores",
        pergunta="O cliente consegue exigir preço, prazo ou serviço?",
        medido=medido,
        limite=(
            "Concentração de clientes é o dado que decidiria isto, e as "
            "demonstrações padronizadas não a trazem — está nas notas "
            "explicativas, que o app não lê."
        ),
    )


def _entrantes(analise, resultado) -> Evidencia:
    medido = []
    capex = analise.mediana("Capex / Receita")
    if np.isfinite(capex):
        medido.append(
            f"Capex mediano de {_pct(capex)} da receita"
            f"{_com_referencia('Capex / Receita', capex, analise)}."
        )
    giro = analise.mediana("Giro do capital investido")
    if np.isfinite(giro):
        medido.append(
            f"Cada real de capital investido vira {_numero(giro)} de receita por ano."
        )
    return Evidencia(
        tema="Ameaça de entrantes",
        pergunta="Quanto custa montar um concorrente desta empresa?",
        medido=medido,
        limite=(
            "Capital é só uma das barreiras. Licença, marca, rede de distribuição "
            "e escala mínima não aparecem em conta nenhuma."
        ),
    )


def _substitutos() -> Evidencia:
    return Evidencia(
        tema="Ameaça de substitutos",
        pergunta="O que o cliente compraria se este produto sumisse amanhã?",
        medido=[],
        limite=(
            "**Nenhuma evidência quantitativa.** Não há linha de balanço que "
            "responda isto. Fica inteiramente com o analista — e aparece aqui "
            "justamente para não sumir da lista."
        ),
    )


def _fosso(analise, resultado) -> Evidencia:
    medido = []
    roics = _serie(analise, "ROIC")
    wacc = resultado.custo_capital.wacc_brl if resultado is not None else float("nan")

    if not roics.empty:
        mediana = float(roics.median())
        medido.append(f"ROIC mediano de {_pct(mediana)}{_com_referencia('ROIC', mediana, analise)}.")

    if not roics.empty and np.isfinite(wacc):
        acima = int((roics > wacc).sum())
        medido.append(
            f"Ficou acima do WACC de {_pct(wacc)} em {acima} dos {len(roics)} anos "
            f"apurados, com folga mediana de {_pct(float(roics.median() - wacc))}."
        )
        if len(roics) < ANOS_DE_RETORNO_EXCEDENTE:
            medido.append(
                f"Com apenas {len(roics)} ano(s) de ROIC apurado, não dá para dizer "
                "se o retorno excedente se sustenta ou foi um ano bom. Importe mais "
                "exercícios antes de tratar isso como vantagem."
            )
        elif acima >= ANOS_DE_RETORNO_EXCEDENTE:
            medido.append(
                "Retorno acima do custo de capital por vários anos seguidos é a "
                "assinatura contábil de uma vantagem — **é a pergunta a fazer, não "
                "a resposta**: falta dizer de onde ela vem e quanto tempo dura."
            )
        elif acima == 0:
            medido.append(
                "Não superou o custo de capital em nenhum ano do período. Crescer "
                "assim destrói valor, e a projeção precisa explicar o que muda."
            )

    return Evidencia(
        tema="Fosso (vantagem competitiva)",
        pergunta="De onde vem o retorno excedente, e por quanto tempo ele resiste?",
        medido=medido,
        limite=(
            "ROIC alto mostra que a vantagem existiu, não por que existiu nem se "
            "continua. Contabilidade mede o passado; fosso é afirmação sobre o "
            "futuro."
        ),
    )


# ---------------------------------------------------------------------------
# VRIO
# ---------------------------------------------------------------------------
#
# As quatro perguntas de Barney -- Valor, Raridade, Imitabilidade, Organizacao --
# nao se distribuem igualmente entre "da para medir" e "so o analista sabe", e o
# app nao finge que sim:
#
#   Valor          o excedente sobre o custo de capital, que o app calcula
#   Raridade       o percentil contra as companhias brasileiras medidas
#   Imitabilidade  quase nada: patente, contrato e marca nao estao na CVM
#   Organizacao    conversao de caixa e reinvestimento, que sao proxies fracos
#
# **Nao ha nota nem veredito**, e a ausencia e a decisao: pontuar de 1 a 5
# converte julgamento em numero e daria ao chute a aparencia de medida -- que e
# exatamente o que este modulo existe para nao fazer. Cada bloco entrega o que
# mediu e diz onde o julgamento comeca, como as cinco forcas.

# Percentil a partir do qual o indicador deixa de ser comum na base. Nao e
# raridade no sentido de Barney -- e o que faz a pergunta valer a pena.
PERCENTIL_INCOMUM = 0.80


def _vrio_valor(analise, resultado) -> Evidencia:
    """A vantagem gera valor? E a unica das quatro que o app mede de frente."""
    medido = []
    roics = _serie(analise, "ROIC")
    wacc = resultado.custo_capital.wacc_brl if resultado is not None else float("nan")
    if not roics.empty and np.isfinite(wacc):
        folga = float(roics.median() - wacc)
        medido.append(
            f"ROIC mediano de {_pct(float(roics.median()))} contra WACC de "
            f"{_pct(wacc)} — folga de {_pct(folga)}."
        )
        medido.append(
            "Valor, aqui, é o excedente sobre o custo de capital: sem ele as "
            "outras três perguntas não têm objeto."
            if folga > 0
            else "Sem excedente sobre o custo de capital não há vantagem a "
            "qualificar — as outras três perguntas ficam sem objeto."
        )
    return Evidencia(
        tema="VRIO — Valor",
        pergunta="O recurso permite explorar oportunidade ou neutralizar ameaça?",
        medido=medido,
        limite=(
            "O excedente diz que houve valor, não de qual recurso ele veio. "
            "Marca, rede de distribuição e contrato de longo prazo produzem o "
            "mesmo ROIC e pedem defesas diferentes."
        ),
    )


def _e_financeira(analise) -> bool:
    """A companhia publica no plano de banco ou seguradora?

    Importa aqui porque **o universo de referencia exclui essas companhias de
    proposito** -- comparar contra 445 companhias a que a instituicao nao
    pertence produz um percentil que parece informacao e nao e. O relatorio ja
    tinha essa consciencia (`_nao_se_aplica_ao_banco`); o modulo nao tinha, e a
    tela nova herdaria o defeito.
    """
    from .bancos import e_instituicao_financeira

    demonstracoes = getattr(analise, "demonstracoes", None)
    if demonstracoes is None:
        return False
    try:
        return e_instituicao_financeira(demonstracoes)
    except Exception:  # noqa: BLE001 -- ausencia de aviso nao e erro
        return False


def por_que_nao_se_aplica(analise) -> str | None:
    """Por que a evidencia nao serve a esta companhia, ou ``None``.

    **O problema e maior que o percentil.** Corrigir `_com_referencia` tirou o
    numero que comparava um banco com 445 companhias a que ele nao pertence, mas
    os **indicadores** continuam sendo os errados: medido no Bradesco, a
    rivalidade sai como "margem EBITDA mediana de 4,5%" e a ameaca de entrantes
    como "capex de 3,9% da receita -- o capital que um concorrente precisaria
    por para montar a mesma operacao". Um banco nao se monta com capex; se monta
    com licenca e capital regulatorio.

    O relatorio ja recusava a secao inteira no caminho do banco
    (`relatorio._nao_se_aplica_ao_banco`). A **tela** nao recusava, e mostrava
    esses numeros -- a protecao existia num consumidor e nao no outro. Por isso a
    razao mora aqui: quem consumir o modulo daqui em diante recebe a recusa
    junto com os blocos.
    """
    if not _e_financeira(analise):
        return None
    return (
        "**A evidência desta seção não descreve uma instituição financeira.** As "
        "perguntas continuam valendo — rivalidade, poder de barganha e fosso são "
        "centrais em banco —, mas os números que as sustentam aqui são de "
        "empresa não financeira: margem EBITDA, capex sobre receita e giro do "
        "capital investido. Medido no Bradesco, a rivalidade sairia como "
        "\"margem EBITDA de 4,5%\" e a barreira de entrada como \"capex de 3,9% "
        "da receita\" — um banco não se monta com capex, se monta com licença e "
        "capital regulatório. O percentil já é suprimido; os indicadores é que "
        "não transferem, e inventar equivalentes seria pior que a ausência."
    )


def _vrio_raridade(analise) -> Evidencia:
    """Quantos concorrentes tem o mesmo? E a que o percentil de fato responde."""
    if _e_financeira(analise):
        return Evidencia(
            tema="VRIO — Raridade",
            pergunta="Quantos concorrentes já controlam o mesmo recurso?",
            medido=[],
            limite=(
                "**O percentil não se aplica a esta companhia.** O universo de "
                "referência exclui bancos e seguradoras de propósito — margem "
                "EBITDA e conversão de caixa não querem dizer para um banco o "
                "que querem dizer no resto —, então comparar contra ele "
                "produziria um número com aparência de informação. Raridade "
                "aqui se discute contra os pares do próprio setor: carteira, "
                "custo de funding, base de depósito."
            ),
        )

    medido = []
    for indicador in ("ROIC", "Margem EBITDA", "Conversao de caixa (FCO / EBITDA)"):
        valor = analise.mediana(indicador)
        if not np.isfinite(valor):
            continue
        onde = _com_referencia(indicador, valor, analise)
        if not onde:
            continue
        posicao = referencias.posicao(indicador, valor)
        marca = (
            " — **incomum**"
            if np.isfinite(posicao) and posicao >= PERCENTIL_INCOMUM
            else ""
        )
        medido.append(f"{indicador} de {_pct(valor)}{onde}{marca}.")
    if medido:
        medido.append(
            "Percentil alto em vários indicadores ao mesmo tempo é o que separa "
            "**raro** de **bom ano**: um indicador sozinho oscila com o ciclo."
        )
    return Evidencia(
        tema="VRIO — Raridade",
        pergunta="Quantos concorrentes já controlam o mesmo recurso?",
        medido=medido,
        limite=(
            "O percentil compara com as companhias **abertas brasileiras** que o "
            "app mediu, e o concorrente relevante pode ser fechado, estrangeiro "
            "ou de outro setor. Ser incomum na base não é ser raro no mercado."
        ),
    )


def _vrio_imitabilidade(analise, resultado) -> Evidencia:
    """Custa caro copiar? Aqui o app quase nao tem o que dizer, e diz isso."""
    medido = []
    roics = _serie(analise, "ROIC")
    wacc = resultado.custo_capital.wacc_brl if resultado is not None else float("nan")
    if not roics.empty and np.isfinite(wacc) and len(roics) >= ANOS_DE_RETORNO_EXCEDENTE:
        acima = int((roics > wacc).sum())
        medido.append(
            f"O excedente resistiu em {acima} dos {len(roics)} anos apurados. "
            + (
                "Vantagem que sobrevive a vários exercícios é evidência "
                "**indireta** de que copiar custa caro — indireta porque o "
                "período pode simplesmente não ter tido entrante."
                if acima >= ANOS_DE_RETORNO_EXCEDENTE
                else "Excedente que não persiste é, na leitura mais simples, "
                "vantagem imitável — ou que nunca existiu."
            )
        )
    capex = analise.mediana("Capex / Receita")
    if np.isfinite(capex):
        medido.append(
            f"Capex mediano de {_pct(capex)} da receita"
            f"{_com_referencia('Capex / Receita', capex, analise)} — é o capital que um "
            "concorrente precisaria pôr para montar a mesma operação."
        )
    return Evidencia(
        tema="VRIO — Imitabilidade",
        pergunta="Quanto custa, para um concorrente, obter o mesmo recurso?",
        medido=medido,
        limite=(
            "**Esta é a pergunta que os dados menos alcançam.** Patente, marca, "
            "contrato de concessão, custo de troca e efeito de rede não aparecem "
            "em demonstração padronizada. Persistência de ROIC é sintoma, e "
            "sintoma não é causa: o que impede a cópia só a pesquisa diz."
        ),
    )


def _vrio_organizacao(analise) -> Evidencia:
    """A empresa esta organizada para capturar o que a vantagem permite?"""
    medido = []
    conversao = analise.mediana("Conversao de caixa (FCO / EBITDA)")
    if np.isfinite(conversao):
        medido.append(
            f"Converte {_pct(conversao)} do EBITDA em caixa operacional"
            f"{_com_referencia('Conversao de caixa (FCO / EBITDA)', conversao, analise)} — "
            "vantagem que não vira caixa não foi capturada."
        )
    reinvestimento = analise.mediana("Taxa de reinvestimento")
    if np.isfinite(reinvestimento):
        medido.append(
            f"Reinveste {_pct(reinvestimento)} do NOPAT"
            f"{_com_referencia('Taxa de reinvestimento', reinvestimento, analise)}."
        )
    payout = analise.mediana("Payout (dividendos / lucro)")
    if np.isfinite(payout):
        medido.append(f"Distribui {_pct(payout)} do lucro.")
    if medido:
        medido.append(
            "Reinvestir muito com ROIC alto amplia a vantagem; reinvestir muito "
            "com ROIC baixo a destrói mais rápido. O par é que se lê, e não cada "
            "número sozinho."
        )
    return Evidencia(
        tema="VRIO — Organização",
        pergunta="A empresa está organizada para capturar o que o recurso permite?",
        medido=medido,
        limite=(
            "Conversão de caixa e reinvestimento são proxies fracos de execução. "
            "Governança, incentivo de gestão, disciplina de alocação e cultura "
            "não têm linha contábil."
        ),
    )


def reunir_vrio(analise, resultado=None) -> list[Evidencia]:
    """As quatro perguntas de Barney, na ordem em que se respondem.

    A ordem importa: sem **valor** as outras tres nao tem objeto, e sem
    **raridade** a discussao de imitabilidade e sobre um recurso que todo mundo
    ja tem.
    """
    if analise is None:
        return []
    return [
        _vrio_valor(analise, resultado),
        _vrio_raridade(analise),
        _vrio_imitabilidade(analise, resultado),
        _vrio_organizacao(analise),
    ]


def reunir_evidencias(analise, resultado=None) -> list[Evidencia]:
    """As seis perguntas, na ordem em que se discutem, com o que os dados dizem.

    Sem ``analise`` nao ha o que reunir: as evidencias saem do historico, nao do
    modelo. Sem ``resultado``, o bloco de fosso perde a comparacao com o WACC e
    diz so o ROIC.
    """
    if analise is None:
        return []
    return [
        _rivalidade(analise),
        _fornecedores(analise),
        _compradores(analise),
        _entrantes(analise, resultado),
        _substitutos(),
        _fosso(analise, resultado),
    ]

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


def _com_referencia(indicador: str, valor: float) -> str:
    onde = referencias.descrever(indicador, valor)
    return f" — {onde}" if onde else ""


def _rivalidade(analise) -> Evidencia:
    medido = []
    margens = _serie(analise, "Margem EBITDA")
    if not margens.empty:
        mediana = float(margens.median())
        medido.append(
            f"Margem EBITDA mediana de {_pct(mediana)}"
            f"{_com_referencia('Margem EBITDA', mediana)}."
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
            f"{_com_referencia('Capex / Receita', capex)}."
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
        medido.append(f"ROIC mediano de {_pct(mediana)}{_com_referencia('ROIC', mediana)}.")

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

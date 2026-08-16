"""Comparar duas versoes do mesmo valuation: o que mudou e quanto moveu o valor.

Um diff de texto do arquivo salvo diz *o que* foi alterado. O que falta saber e
*quanto cada alteracao valeu* -- e isso nao sai do diff, porque as premissas
interagem: mexer em margem muda o NOPAT, que muda o reinvestimento, que muda o
fluxo. Somar efeitos isolados nao reproduz o total.

A ponte aqui e construida uma premissa por vez, acumulando: parte da versao
antiga e aplica as mudancas em sequencia, medindo o valor a cada passo. O
ultimo passo cai exatamente no valor da versao nova, entao as parcelas somam o
movimento inteiro sem sobra. A ordem importa -- o efeito atribuido a cada
premissa depende de quais ja foram aplicadas --, e por isso ela e declarada e
nao acidental.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .modelo import avaliar, substituir_varios
from .premissas import Empresa

# Caminhos que nao descrevem premissa e nao entram na comparacao.
_IGNORADOS = frozenset({"nome", "unidade", "data_base", "moeda"})


def _achatar(valor: Any, prefixo: str = "") -> dict[str, Any]:
    """Reduz a empresa a um dicionario de caminho pontilhado -> valor."""
    if dataclasses.is_dataclass(valor) and not isinstance(valor, type):
        plano: dict[str, Any] = {}
        for campo in dataclasses.fields(valor):
            filho = getattr(valor, campo.name)
            caminho = f"{prefixo}.{campo.name}" if prefixo else campo.name
            plano.update(_achatar(filho, caminho))
        return plano
    return {prefixo: valor}


def _mudou(antes: Any, depois: Any) -> bool:
    if isinstance(antes, (list, tuple)) and isinstance(depois, (list, tuple)):
        if len(antes) != len(depois):
            return True
        return any(_mudou(a, d) for a, d in zip(antes, depois))
    if isinstance(antes, float) and isinstance(depois, float):
        if np.isnan(antes) and np.isnan(depois):
            return False
        return not np.isclose(antes, depois, rtol=1e-12, atol=0.0)
    return antes != depois


@dataclass(frozen=True)
class Movimento:
    """Uma premissa que mudou, e quanto ela moveu o equity value."""

    caminho: str
    antes: Any
    depois: Any
    efeito: float

    @property
    def rotulo(self) -> str:
        return self.caminho.replace("_", " ").replace(".", " → ")


@dataclass(frozen=True)
class Comparacao:
    """Diferenca entre duas versoes, com a ponte do que moveu o valor."""

    valor_antes: float
    valor_depois: float
    movimentos: list[Movimento] = field(default_factory=list)
    nao_atribuido: float = 0.0
    avisos: list[str] = field(default_factory=list)

    @property
    def variacao(self) -> float:
        return self.valor_depois - self.valor_antes

    @property
    def variacao_relativa(self) -> float:
        if not np.isfinite(self.valor_antes) or self.valor_antes == 0:
            return float("nan")
        return self.variacao / abs(self.valor_antes)

    @property
    def por_efeito(self) -> list[Movimento]:
        """Movimentos do que mais moveu o valor para o que menos moveu."""
        return sorted(self.movimentos, key=lambda m: abs(m.efeito), reverse=True)

    def fecha(self, tolerancia: float = 1e-6) -> bool:
        """As parcelas somam a variacao total?"""
        soma = sum(m.efeito for m in self.movimentos) + self.nao_atribuido
        escala = max(abs(self.variacao), 1.0)
        return abs(soma - self.variacao) / escala <= tolerancia


def _valor(empresa: Empresa, **convencoes) -> float:
    try:
        return float(avaliar(empresa, **convencoes).equity_value)
    except ValueError:
        return float("nan")


def comparar(antes: Empresa, depois: Empresa, **convencoes) -> Comparacao:
    """Compara duas versoes e atribui a cada premissa o quanto ela moveu o valor.

    ``convencoes`` sao as mesmas de ``avaliar`` (meio_de_ano, tipo_fluxo) e
    precisam ser as de quem esta comparando: medir duas versoes sob convencoes
    diferentes mistura o efeito da premissa com o do metodo.
    """
    plano_antes = _achatar(antes)
    plano_depois = _achatar(depois)

    caminhos = [
        c
        for c in plano_antes
        if c in plano_depois
        and c.rsplit(".", 1)[-1] not in _IGNORADOS
        and _mudou(plano_antes[c], plano_depois[c])
    ]

    valor_antes = _valor(antes, **convencoes)
    valor_depois = _valor(depois, **convencoes)
    avisos: list[str] = []

    novos = set(plano_depois) - set(plano_antes)
    sumidos = set(plano_antes) - set(plano_depois)
    if novos or sumidos:
        avisos.append(
            "As duas versoes tem estruturas diferentes de premissas; comparei "
            "apenas os campos presentes nas duas."
        )

    movimentos: list[Movimento] = []
    corrente = antes
    acumulado = valor_antes
    for caminho in caminhos:
        try:
            corrente = substituir_varios(corrente, {caminho: plano_depois[caminho]})
        except (ValueError, TypeError) as erro:
            avisos.append(f"Nao consegui aplicar '{caminho}': {erro}")
            continue
        novo = _valor(corrente, **convencoes)
        # Um passo intermediario pode ser economicamente inviavel (g acima do
        # WACC no meio do caminho) sem que as pontas sejam. Efeito NaN e honesto:
        # aquele passo nao tem valor mensuravel, e a sobra vai para o residuo.
        efeito = novo - acumulado if np.isfinite(novo) and np.isfinite(acumulado) else float("nan")
        movimentos.append(
            Movimento(caminho, plano_antes[caminho], plano_depois[caminho], efeito)
        )
        if np.isfinite(novo):
            acumulado = novo

    medidos = sum(m.efeito for m in movimentos if np.isfinite(m.efeito))
    total = valor_depois - valor_antes
    residuo = total - medidos if np.isfinite(total) else float("nan")
    if np.isfinite(residuo) and abs(residuo) > max(abs(total), 1.0) * 1e-6:
        avisos.append(
            "Parte do movimento nao foi atribuida a nenhuma premissa isolada; "
            "premissas que interagem podem fazer isso."
        )

    return Comparacao(
        valor_antes=valor_antes,
        valor_depois=valor_depois,
        movimentos=movimentos,
        nao_atribuido=residuo if np.isfinite(residuo) else 0.0,
        avisos=avisos,
    )

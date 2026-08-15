"""Sensibilidade, cenarios e simulacao de Monte Carlo sobre o modelo.

As tres tecnicas respondem perguntas diferentes e se complementam:

* **Tabela de sensibilidade**: como o valor reage a duas premissas ao mesmo
  tempo (classicamente WACC x crescimento perpetuo).
* **Cenarios**: conjuntos coerentes de premissas com nome (base, otimista,
  pessimista), porque na pratica as premissas nao se movem isoladamente.
* **Monte Carlo**: a distribuicao do valor quando varias premissas variam
  simultaneamente segundo distribuicoes declaradas.

Combinacoes economicamente impossiveis (crescimento perpetuo acima da taxa de
desconto, por exemplo) resultam em ``NaN`` na tabela e em descarte contabilizado
no Monte Carlo, nunca em um numero silenciosamente errado.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .erros import CombinacaoInviavel
from .modelo import ResultadoValuation, avaliar, substituir_varios
from .premissas import Empresa

# Caminho especial: nao e uma premissa, e a propria taxa de desconto do DCF.
CAMINHO_WACC = "wacc"

_METRICAS = {
    "equity_value": lambda r: r.equity_value,
    "enterprise_value": lambda r: r.enterprise_value,
    "valor_por_acao": lambda r: r.valor_por_acao,
    "wacc": lambda r: r.dcf.taxa_desconto,
    "peso_perpetuidade": lambda r: r.dcf.peso_perpetuidade,
}


def _extrair(resultado: ResultadoValuation, metrica: str) -> float:
    if metrica not in _METRICAS:
        raise ValueError(
            f"metrica {metrica!r} desconhecida. Opcoes: {sorted(_METRICAS)}"
        )
    valor = _METRICAS[metrica](resultado)
    return float("nan") if valor is None else float(valor)


def avaliar_com(
    empresa: Empresa, alteracoes: dict[str, float], **kwargs
) -> ResultadoValuation:
    """Avalia a empresa com premissas alteradas por caminho pontilhado.

    O caminho especial ``"wacc"`` nao altera premissa nenhuma: ele forca a taxa
    de desconto do DCF, que e o que se quer ao montar uma tabela WACC x g.
    """
    alteracoes = dict(alteracoes)
    taxa = alteracoes.pop(CAMINHO_WACC, None)
    if taxa is not None:
        kwargs["taxa_desconto"] = taxa
    empresa_ajustada = substituir_varios(empresa, alteracoes)
    return avaliar(empresa_ajustada, **kwargs)


def tabela_sensibilidade(
    empresa: Empresa,
    eixo_linhas: tuple[str, list[float]],
    eixo_colunas: tuple[str, list[float]],
    metrica: str = "equity_value",
    **kwargs,
) -> pd.DataFrame:
    """Tabela bidimensional de sensibilidade.

    Exemplo tipico -- WACC nas linhas, crescimento perpetuo nas colunas::

        tabela_sensibilidade(
            empresa,
            ("wacc", [0.11, 0.12, 0.13]),
            ("perpetuidade.crescimento_perpetuo", [0.03, 0.04, 0.05]),
        )
    """
    caminho_l, valores_l = eixo_linhas
    caminho_c, valores_c = eixo_colunas
    if not valores_l or not valores_c:
        raise ValueError("Cada eixo precisa de ao menos um valor.")

    matriz = np.empty((len(valores_l), len(valores_c)))
    for i, vl in enumerate(valores_l):
        for j, vc in enumerate(valores_c):
            try:
                resultado = avaliar_com(
                    empresa, {caminho_l: vl, caminho_c: vc}, **kwargs
                )
                matriz[i, j] = _extrair(resultado, metrica)
            except CombinacaoInviavel:
                matriz[i, j] = float("nan")

    return pd.DataFrame(
        matriz,
        index=pd.Index([_rotular(caminho_l, v) for v in valores_l], name=caminho_l),
        columns=pd.Index([_rotular(caminho_c, v) for v in valores_c], name=caminho_c),
    )


def _rotular(caminho: str, valor: float) -> str:
    """Formata como percentual os caminhos que sao taxas, e como numero os demais."""
    e_taxa = caminho == CAMINHO_WACC or any(
        chave in caminho
        for chave in ("crescimento", "margem", "taxa", "inflacao", "roic", "pct", "rf_")
    )
    if e_taxa:
        return f"{valor * 100:.2f}%".replace(".", ",")
    return f"{valor:,.2f}".replace(".", ",")


def cenarios(
    empresa: Empresa,
    definicoes: dict[str, dict[str, float]],
    metricas: tuple[str, ...] = ("enterprise_value", "equity_value", "valor_por_acao"),
    **kwargs,
) -> pd.DataFrame:
    """Avalia conjuntos nomeados de premissas.

    ``definicoes`` mapeia o nome do cenario para as alteracoes daquele cenario::

        {"Pessimista": {"perpetuidade.crescimento_perpetuo": 0.02,
                        "operacionais.margem_ebitda": 0.18}}
    """
    linhas = {}
    for nome, alteracoes in definicoes.items():
        try:
            resultado = avaliar_com(empresa, alteracoes, **kwargs)
            linhas[nome] = {m: _extrair(resultado, m) for m in metricas}
        except CombinacaoInviavel as erro:
            linhas[nome] = {m: float("nan") for m in metricas}
            linhas[nome]["erro"] = str(erro)
    return pd.DataFrame(linhas)


@dataclass(frozen=True)
class Distribuicao:
    """Distribuicao de uma premissa para o Monte Carlo.

    Tipos aceitos e seus parametros:

    * ``"normal"``: ``media``, ``desvio``
    * ``"uniforme"``: ``minimo``, ``maximo``
    * ``"triangular"``: ``minimo``, ``moda``, ``maximo`` -- a escolha usual em
      valuation, porque especialistas conseguem opinar sobre piso, teto e caso
      mais provavel muito melhor do que sobre um desvio-padrao
    * ``"lognormal"``: ``media``, ``desvio`` da propria variavel (positiva)

    ``limite_inferior`` e ``limite_superior`` truncam as amostras, util para
    impedir margens negativas ou crescimentos absurdos.
    """

    caminho: str
    tipo: str
    parametros: dict[str, float] = field(default_factory=dict)
    limite_inferior: float | None = None
    limite_superior: float | None = None

    def amostrar(self, rng: np.random.Generator, n: int) -> np.ndarray:
        p = self.parametros
        if self.tipo == "normal":
            amostras = rng.normal(p["media"], p["desvio"], n)
        elif self.tipo == "uniforme":
            amostras = rng.uniform(p["minimo"], p["maximo"], n)
        elif self.tipo == "triangular":
            amostras = rng.triangular(p["minimo"], p["moda"], p["maximo"], n)
        elif self.tipo == "lognormal":
            media, desvio = p["media"], p["desvio"]
            if media <= 0:
                raise ValueError("A lognormal exige media positiva.")
            # Converte media/desvio da variavel para os parametros do log.
            var_log = np.log(1 + (desvio / media) ** 2)
            mu_log = np.log(media) - var_log / 2
            amostras = rng.lognormal(mu_log, np.sqrt(var_log), n)
        else:
            raise ValueError(f"tipo de distribuicao desconhecido: {self.tipo!r}")

        if self.limite_inferior is not None:
            amostras = np.maximum(amostras, self.limite_inferior)
        if self.limite_superior is not None:
            amostras = np.minimum(amostras, self.limite_superior)
        return amostras


@dataclass(frozen=True)
class ResultadoSimulacao:
    """Distribuicao simulada do valor, com as rodadas descartadas contabilizadas."""

    valores: np.ndarray
    metrica: str
    simulacoes: int
    descartadas: int
    amostras: dict[str, np.ndarray]

    def percentis(
        self, quantis: tuple[float, ...] = (5, 10, 25, 50, 75, 90, 95)
    ) -> pd.Series:
        return pd.Series(
            np.percentile(self.valores, quantis),
            index=[f"P{q:g}" for q in quantis],
            name=self.metrica,
        )

    def resumo(self) -> pd.Series:
        return pd.Series(
            {
                "Simulacoes validas": float(self.valores.size),
                "Descartadas (inviaveis)": float(self.descartadas),
                "Media": float(np.mean(self.valores)),
                "Desvio padrao": float(np.std(self.valores, ddof=1)),
                "Minimo": float(np.min(self.valores)),
                "Maximo": float(np.max(self.valores)),
                **self.percentis().to_dict(),
            },
            name=self.metrica,
        )

    def probabilidade_acima(self, limite: float) -> float:
        """Fracao das simulacoes com valor acima de ``limite``.

        Util para responder "qual a chance de o valor justificar o preco pedido?".
        """
        return float(np.mean(self.valores > limite))


def monte_carlo(
    empresa: Empresa,
    distribuicoes: list[Distribuicao],
    simulacoes: int = 10_000,
    metrica: str = "equity_value",
    semente: int | None = 42,
    **kwargs,
) -> ResultadoSimulacao:
    """Simula o valor da empresa variando varias premissas simultaneamente.

    A semente e fixada por padrao para que o mesmo modelo produza o mesmo
    resultado -- em trabalho de valuation, um numero que muda a cada execucao e
    indefensavel em revisao.

    Rodadas economicamente inviaveis (por exemplo crescimento perpetuo sorteado
    acima da taxa de desconto) sao descartadas e reportadas em
    ``descartadas``, em vez de distorcerem a distribuicao.
    """
    if not distribuicoes:
        raise ValueError("Informe ao menos uma distribuicao.")
    if simulacoes <= 0:
        raise ValueError("simulacoes deve ser positivo.")

    rng = np.random.default_rng(semente)
    amostras = {d.caminho: d.amostrar(rng, simulacoes) for d in distribuicoes}

    valores = np.empty(simulacoes)
    descartadas = 0
    for i in range(simulacoes):
        alteracoes = {caminho: float(serie[i]) for caminho, serie in amostras.items()}
        try:
            resultado = avaliar_com(empresa, alteracoes, **kwargs)
            valores[i] = _extrair(resultado, metrica)
        except CombinacaoInviavel:
            valores[i] = float("nan")
            descartadas += 1

    validos = valores[np.isfinite(valores)]
    if validos.size == 0:
        raise ValueError(
            "Nenhuma simulacao viavel. Revise as distribuicoes -- o caso mais "
            "comum e o crescimento perpetuo sorteado acima da taxa de desconto."
        )

    return ResultadoSimulacao(
        valores=validos,
        metrica=metrica,
        simulacoes=simulacoes,
        descartadas=descartadas,
        amostras=amostras,
    )

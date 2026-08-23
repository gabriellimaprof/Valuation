"""Margem de seguranca e as expectativas que o preco de mercado embute.

Um DCF entrega um valor. Sozinho, ele nao decide nada: a decisao mora na
distancia entre esse valor e o preco pedido, e no tamanho do erro que essa
distancia aguenta. E o que este modulo calcula.

Duas perguntas, e a segunda e a que muda a conversa
---------------------------------------------------

**Quanta folga ha?** ``margem_de_seguranca`` devolve a distancia entre valor e
preco pelos dois denominadores, porque eles respondem coisas diferentes e sao
confundidos o tempo todo. Comprar a 70 o que vale 100 e 30% de margem sobre o
valor e 42,9% de potencial sobre o preco. Quem exige "30% de margem" quase
sempre quer dizer o primeiro.

**O que o mercado precisa acreditar?** ``expectativas_implicitas`` inverte o
modelo: para cada premissa, qual valor faria o DCF dar exatamente o preco de
tela. E o DCF reverso, e ele desarma a discussao improdutiva sobre quem tem o
modelo certo. "Voce acha caro, eu acho barato" nao vai a lugar nenhum; "a este
preco o mercado embute margem de 12,4% contra os 18,7% que a empresa entregou
nos ultimos cinco anos" e uma afirmacao que da para checar.

Por que uma busca numerica, e nao uma formula
---------------------------------------------

Inverter Gordon na mao so funciona para o ``g``, e mesmo assim quebra quando o
reinvestimento e normalizado. Margem, capex e crescimento entram na projecao ano
a ano, passam pelo imposto e pelo capital de giro; nao ha forma fechada. A
bissecao roda o modelo inteiro a cada tentativa, entao vale para qualquer
premissa que o motor aceite -- e continua valendo quando o motor mudar.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .erros import CombinacaoInviavel
from .modelo import avaliar, substituir
from .premissas import Empresa

# Vereditos. Sao rotulos de leitura, nao recomendacao de investimento.
COM_MARGEM = "com margem"
JUSTO = "no valor"
CARO = "acima do valor"

# Exigencia usual de quem trabalha com margem de seguranca. E convencao de
# mercado, nao lei: Graham falava em um terco, Damodaran nao usa o conceito.
MARGEM_EXIGIDA = 0.30

# Premissas que valem inverter, com a faixa em que a busca procura.
#
# As faixas nao sao chutes: cobrem com folga o que a base brasileira de fato
# apresenta (ver ``referencias.BASE``, 447 companhias). O P95 de margem EBITDA e
# 60,1% e o P99 passa de 100%; o P95 de crescimento e 71,8%; o de capex sobre
# receita, 48,7%. Estreitar ate o P95 faria a busca responder "impossivel"
# justamente para as companhias atipicas, que sao as que mais precisam da
# resposta.
#
# ``crescimento_perpetuo`` e os premios de risco nao vem da base: o primeiro e
# limitado por cima pelo desconto, e os outros sao premios de mercado.
REVERSIVEIS: dict[str, tuple[str, tuple[float, float]]] = {
    "operacionais.margem_ebitda": ("Margem EBITDA", (0.005, 1.10)),
    "operacionais.crescimento_receita": ("Crescimento da receita", (-0.30, 0.80)),
    "operacionais.capex_pct_receita": ("Capex / receita", (0.0, 1.20)),
    "perpetuidade.crescimento_perpetuo": ("Crescimento perpétuo", (-0.05, 0.12)),
}

# **A premissa do desconto depende do caminho que monta o Ke.** No caminho em
# dolar quem carrega o risco do pais e ``risco_pais``; no local ele esta dentro
# da NTN-B e quem sobra e o premio de acoes local. Oferecer a premissa errada
# faz a busca varrer um numero que **nao move o valor** -- e devolver "nao ha
# premissa que justifique o preco" por um motivo que nao e do negocio.
PREMIO_REVERSIVEL = {
    "usd": ("custo_capital.risco_pais", "Prêmio de risco-país", (0.0, 0.30)),
    "local": ("custo_capital.erp_local", "Prêmio de risco local", (0.0, 0.30)),
}


def reversiveis_de(empresa) -> dict[str, tuple[str, tuple[float, float]]]:
    """As premissas que a busca pode varrer nesta empresa."""
    caminho, rotulo, faixa = PREMIO_REVERSIVEL[empresa.custo_capital.metodo]
    return {**REVERSIVEIS, caminho: (rotulo, faixa)}

PONTOS_DA_VARREDURA = 40
ITERACOES = 60


@dataclass(frozen=True)
class MargemDeSeguranca:
    """A distancia entre o valor calculado e o preco pedido."""

    valor: float
    preco: float
    exigida: float = MARGEM_EXIGIDA

    @property
    def margem(self) -> float:
        """Desconto sobre o **valor** -- o denominador de quem exige margem."""
        if not np.isfinite(self.valor) or self.valor == 0:
            return float("nan")
        return (self.valor - self.preco) / self.valor

    @property
    def potencial(self) -> float:
        """Alta sobre o **preco** -- o denominador de quem fala em upside."""
        if not np.isfinite(self.preco) or self.preco == 0:
            return float("nan")
        return (self.valor - self.preco) / self.preco

    @property
    def preco_maximo(self) -> float:
        """Ate quanto pagar sem abrir mao da margem exigida."""
        return self.valor * (1 - self.exigida)

    @property
    def veredito(self) -> str:
        if not np.isfinite(self.margem):
            return JUSTO
        if self.margem >= self.exigida:
            return COM_MARGEM
        # Preco exatamente igual ao valor e "no valor", nao "acima": a fronteira
        # do caro comeca quando o preco passa do valor.
        if self.margem >= 0:
            return JUSTO
        return CARO

    def resumo(self) -> str:
        if self.veredito == COM_MARGEM:
            return (
                f"Preço {_pct(abs(self.margem))} abaixo do valor, acima da margem "
                f"exigida de {_pct(self.exigida)}."
            )
        if self.veredito == JUSTO:
            if self.margem == 0:
                return "Preço exatamente igual ao valor calculado: margem zero."
            return (
                f"Preço {_pct(abs(self.margem))} abaixo do valor — há desconto, mas "
                f"menos do que os {_pct(self.exigida)} exigidos."
            )
        return f"Preço {_pct(abs(self.margem))} acima do valor calculado."


def _pct(valor: float, casas: int = 1) -> str:
    if not np.isfinite(valor):
        return "n/d"
    return f"{valor * 100:.{casas}f}%".replace(".", ",")


def margem_de_seguranca(
    valor: float, preco: float, exigida: float = MARGEM_EXIGIDA
) -> MargemDeSeguranca:
    """Compara valor e preco. Ambos na mesma base: ou totais, ou por acao."""
    if preco <= 0:
        raise ValueError("O preco precisa ser positivo.")
    if not -1 < exigida < 1:
        raise ValueError("A margem exigida e um decimal (0.30 para 30%).")
    return MargemDeSeguranca(valor=float(valor), preco=float(preco), exigida=exigida)


# ---------------------------------------------------------------------------
# O DCF reverso
# ---------------------------------------------------------------------------


def _metrica(resultado, nome: str) -> float:
    valor = {
        "equity_value": resultado.equity_value,
        "enterprise_value": resultado.enterprise_value,
        "valor_por_acao": resultado.valor_por_acao,
    }.get(nome)
    return float("nan") if valor is None else float(valor)


def _avaliar_em(
    empresa: Empresa, caminho: str, x: float, metrica: str, **kwargs
) -> float:
    """Roda o modelo com a premissa trocada. Combinacao inviavel vira NaN.

    NaN em vez de excecao porque a varredura precisa atravessar regioes
    impossiveis -- crescimento perpetuo acima do desconto, por exemplo -- sem
    parar na primeira delas.
    """
    try:
        return _metrica(avaliar(substituir(empresa, caminho, x), **kwargs), metrica)
    except (ValueError, ZeroDivisionError):
        return float("nan")


def premissa_implicita(
    empresa: Empresa,
    alvo: float,
    caminho: str,
    faixa: tuple[float, float] | None = None,
    metrica: str = "equity_value",
    **kwargs,
) -> float:
    """Valor da premissa que faz o modelo dar exatamente ``alvo``.

    Devolve ``nan`` quando nenhum valor dentro da faixa produz o alvo -- o que e
    uma resposta legitima e frequente: se a empresa vale menos que o preco em
    toda a faixa plausivel de margem, **nenhuma** margem justifica o preco, e
    fingir que existe uma seria pior do que dizer que nao existe.
    """
    if faixa is None:
        faixa = REVERSIVEIS.get(caminho, (None, (-1.0, 1.0)))[1]
    baixo, alto = faixa
    if not np.isfinite(alvo):
        return float("nan")

    grade = np.linspace(baixo, alto, PONTOS_DA_VARREDURA)
    valores = np.array(
        [_avaliar_em(empresa, caminho, float(x), metrica, **kwargs) for x in grade]
    )
    diferencas = valores - alvo

    # Procura a primeira troca de sinal entre pontos consecutivos validos.
    par = None
    ultimo = None
    for i, d in enumerate(diferencas):
        if not np.isfinite(d):
            continue
        if ultimo is not None and np.sign(d) != np.sign(diferencas[ultimo]):
            par = (grade[ultimo], grade[i])
            break
        if d == 0:
            return float(grade[i])
        ultimo = i

    if par is None:
        return float("nan")

    esquerda, direita = par
    f_esq = _avaliar_em(empresa, caminho, float(esquerda), metrica, **kwargs) - alvo
    for _ in range(ITERACOES):
        meio = (esquerda + direita) / 2
        f_meio = _avaliar_em(empresa, caminho, float(meio), metrica, **kwargs) - alvo
        if not np.isfinite(f_meio):
            return float("nan")
        if np.sign(f_meio) == np.sign(f_esq):
            esquerda, f_esq = meio, f_meio
        else:
            direita = meio
    return float((esquerda + direita) / 2)


def expectativas_implicitas(
    empresa: Empresa,
    preco: float,
    metrica: str = "equity_value",
    caminhos: dict[str, tuple[str, tuple[float, float]]] | None = None,
    **kwargs,
) -> pd.DataFrame:
    """Para cada premissa, o valor que justificaria o preco pedido.

    A coluna ``Diferenca`` e a que se le: ela diz **quanto** a premissa teria de
    ceder para o preco fazer sentido. Uma margem implicita 6 p.p. abaixo da
    entregue e uma afirmacao verificavel sobre o negocio; "acho caro" nao e.
    """
    caminhos = caminhos or reversiveis_de(empresa)
    linhas = []
    for caminho, (rotulo, faixa) in caminhos.items():
        atual = _valor_atual(empresa, caminho)
        implicita = premissa_implicita(
            empresa, preco, caminho, faixa=faixa, metrica=metrica, **kwargs
        )
        linhas.append(
            {
                "Premissa": rotulo,
                "No modelo": atual,
                "Implícita no preço": implicita,
                "Diferença": implicita - atual
                if np.isfinite(implicita) and np.isfinite(atual)
                else float("nan"),
                "caminho": caminho,
            }
        )
    return pd.DataFrame(linhas).set_index("Premissa")


def _valor_atual(empresa: Empresa, caminho: str) -> float:
    objeto = empresa
    for parte in caminho.split("."):
        objeto = getattr(objeto, parte, None)
        if objeto is None:
            return float("nan")
    if isinstance(objeto, list):
        return float(np.median(objeto))
    return float(objeto)


def margem_por_premissa(
    empresa: Empresa, preco: float, metrica: str = "equity_value", **kwargs
) -> pd.DataFrame:
    """Quanto cada premissa aguenta ceder antes de o valor encostar no preco.

    Mesmo calculo de ``expectativas_implicitas``, lido como folga em vez de como
    expectativa: e a forma de responder "de onde vem o risco desta tese".
    """
    tabela = expectativas_implicitas(empresa, preco, metrica=metrica, **kwargs)
    folga = tabela["Diferença"].abs()
    tabela = tabela.assign(Folga=folga).sort_values("Folga")
    return tabela.drop(columns=["Folga"])


def valor_de_referencia(resultado, por_acao: bool) -> tuple[float, str]:
    """O par (valor, metrica) coerente com a base de preco escolhida."""
    if por_acao:
        if resultado.valor_por_acao is None:
            raise CombinacaoInviavel(
                "Sem número de ações na ponte, não há valor por ação para comparar "
                "com a cotação."
            )
        return float(resultado.valor_por_acao), "valor_por_acao"
    return float(resultado.equity_value), "equity_value"

"""As três leituras do tempo: anual, trimestral e ano móvel rolante.

O app lia duas — o exercício fechado e um ano móvel, o do último trimestre. Falta
a terceira e falta a série: quem acompanha uma empresa quer ver **o trimestre
isolado ao longo do tempo** e **o ano móvel se movendo**, e não um ponto.

As três respondem perguntas diferentes, e misturá-las é o erro clássico:

* **Anual** — o exercício social fechado, auditado, comparável entre empresas.
  É o que sustenta valuation, e é o único que fecha com o que a companhia
  divulga como resultado do ano.
* **Trimestral isolado** — os três meses, sozinhos. Mostra inflexão: uma margem
  que virou no 3T aparece aqui e some no acumulado, diluída pelos trimestres
  anteriores. Carrega **sazonalidade**, então comparar 3T com 2T é comparar
  épocas do ano diferentes; o par certo é 3T contra 3T.
* **Ano móvel rolante** — doze meses encerrados em cada trimestre. Tira a
  sazonalidade sem esperar o exercício fechar, que é exatamente o que falta
  entre um balanço anual e o próximo.

O ano móvel **não é a soma dos quatro trimestres isolados** aqui, e a diferença
importa: o quarto trimestre do exercício anterior não existe no ITR — ele seria
o exercício fechado menos o acumulado de nove meses. A fórmula usada é a que a
CVM entrega direto::

    ano móvel = exercício anterior fechado
                + acumulado do exercício corrente
                − acumulado do mesmo período do exercício anterior

Contas de **balanço** não somam em nenhuma das três: são um saldo numa data, e
o saldo certo é o do fim do período.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .importador import Demonstracoes


def _rotulo_do_trimestre(data_refer: str) -> str:
    """``2025-09-30`` vira ``3T25`` — como o mercado escreve."""
    data = pd.to_datetime(data_refer)
    return f"{(data.month - 1) // 3 + 1}T{data.year % 100:02d}"


def _e_saldo(chave: str) -> bool:
    """A conta é um saldo numa data, e não um fluxo de período?"""
    from .esquema import POR_CHAVE

    conta = POR_CHAVE.get(chave)
    return conta is not None and conta.demonstracao in ("bp", "capital")


def montar_serie(
    partes: list[tuple[str, Demonstracoes]],
    empresa: str,
    unidade: str,
    origem: str,
    avisos: list[str] | None = None,
) -> Demonstracoes:
    """Junta demonstrações de vários períodos numa tabela com uma coluna cada.

    Cada parte vem com o rótulo do período. O ``mapeamento`` guarda de onde saiu
    cada conta, e o rótulo entra nele: numa série, "de onde veio" inclui
    **quando**.
    """
    if not partes:
        raise ValueError("Nao ha periodo nenhum para montar a serie.")

    chaves: list[str] = []
    for _, dfs in partes:
        for chave in dfs.valores.index:
            if chave not in chaves:
                chaves.append(chave)

    colunas = {}
    for rotulo, dfs in partes:
        coluna = {}
        for chave in chaves:
            try:
                valor = dfs.valor(chave)
            except Exception:
                valor = float("nan")
            coluna[chave] = valor if np.isfinite(valor) else float("nan")
        colunas[rotulo] = coluna

    tabela = pd.DataFrame(colunas, index=chaves)
    mapeamento = {chave: origem for chave in chaves}
    return Demonstracoes(
        empresa=empresa,
        valores=tabela,
        origem=origem,
        unidade=unidade,
        mapeamento=mapeamento,
        avisos=list(avisos or []),
        detalhe=partes[-1][1].detalhe,
    )

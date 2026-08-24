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


def periodo_do_rotulo(rotulo) -> tuple[int, int] | None:
    """``3T25`` vira ``(2025, 3)``; um ano vira ``None``.

    E o que separa uma serie trimestral de uma anual sem carregar um sinalizador
    pela pilha inteira: o rotulo ja diz o que a coluna e.
    """
    texto = str(rotulo).strip().upper()
    trimestre, separador, ano = texto.partition("T")
    if not separador or not trimestre.isdigit() or not ano.isdigit():
        return None
    numero = int(trimestre)
    if not 1 <= numero <= 4:
        return None
    # ``3T25`` e 2025; ``3T2025`` tambem, para quem escrever por extenso.
    valor = int(ano)
    return (valor if valor > 1900 else 2000 + valor, numero)


def ano_do_rotulo(rotulo) -> int | None:
    """O **exercicio** a que a coluna pertence: ``3T25`` e 2025, ``2024`` e 2024.

    Existe porque varias telas precisam do ano para escolher a safra do universo
    de pares ou o ano-base da planilha, e faziam ``int(dfs.anos[-1])`` -- que
    estoura numa serie trimestral. O ano do exercicio e a resposta certa para
    essas perguntas; o rotulo inteiro e a resposta certa para identificar a
    coluna, e as duas coisas nao sao a mesma.
    """
    periodo = periodo_do_rotulo(rotulo)
    if periodo is not None:
        return periodo[0]
    try:
        return int(str(rotulo).strip())
    except (TypeError, ValueError):
        return None


def anterior_comparavel(colunas) -> dict:
    """Com qual coluna cada coluna se compara para medir crescimento.

    Numa serie anual e a coluna anterior. Numa serie **trimestral** e o mesmo
    trimestre do exercicio anterior -- 3T25 contra 3T24 -- e nunca a coluna
    imediatamente a esquerda: comparar 1T25 com 3T24 mede a distancia entre
    epocas diferentes do ano **e** pula o 4T24, que nao esta na serie.

    Devolve so os pares que existem; o resto fica de fora e vira ``NaN``.
    """
    colunas = list(colunas)
    periodos = {coluna: periodo_do_rotulo(coluna) for coluna in colunas}
    if not all(periodos.values()):
        # Serie anual (ou mista, que nao se sabe ler): a coluna anterior.
        return dict(zip(colunas[1:], colunas[:-1]))

    por_periodo = {periodos[coluna]: coluna for coluna in colunas}
    pares = {}
    for coluna in colunas:
        ano, trimestre = periodos[coluna]
        anterior = por_periodo.get((ano - 1, trimestre))
        if anterior is not None:
            pares[coluna] = anterior
    return pares


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

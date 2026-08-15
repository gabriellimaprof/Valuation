"""Leitura bruta de planilhas: numeros, cabecalhos de ano e coluna de rotulos.

Planilhas de demonstracoes financeiras vem em formatos livres. Antes de tentar
reconhecer contas, e preciso responder tres perguntas mecanicas: onde estao os
anos, onde estao os nomes das contas, e como cada numero esta escrito.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

ANO_MINIMO = 1990
ANO_MAXIMO = 2100

_SO_NUMERO = re.compile(r"^[\d.,\s()\-+R$US]*$")
_ANO_EM_TEXTO = re.compile(r"(19|20)\d{2}")


def para_numero(valor) -> float:
    """Converte uma celula em numero, tolerando as convencoes de planilha.

    Trata separador brasileiro (``1.234,56``) e americano (``1,234.56``),
    negativos entre parenteses (``(123)``, convencao contabil), simbolos de
    moeda e tracos usados para indicar zero. Devolve ``NaN`` quando a celula
    nao representa um numero.
    """
    if valor is None:
        return float("nan")
    if isinstance(valor, (int, float, np.integer, np.floating)):
        return float("nan") if pd.isna(valor) else float(valor)

    texto = str(valor).strip()
    if not texto or texto in {"-", "--", "n/a", "N/A", "nd", "ND"}:
        return float("nan")

    negativo = texto.startswith("(") and texto.endswith(")")
    if negativo:
        texto = texto[1:-1]

    texto = re.sub(r"[R$US\s]", "", texto, flags=re.IGNORECASE)
    if not texto or not _SO_NUMERO.match(texto):
        return float("nan")

    tem_ponto, tem_virgula = "." in texto, "," in texto
    if tem_ponto and tem_virgula:
        # O separador decimal e o que aparece por ultimo.
        if texto.rfind(",") > texto.rfind("."):
            texto = texto.replace(".", "").replace(",", ".")
        else:
            texto = texto.replace(",", "")
    elif tem_virgula:
        # Virgula isolada: decimal se separar 1-2 casas, senao milhar.
        casas = len(texto.split(",")[-1])
        texto = texto.replace(",", "." if casas <= 2 else "")
    elif tem_ponto:
        partes = texto.split(".")
        if len(partes) > 2 or (len(partes) == 2 and len(partes[-1]) == 3):
            texto = texto.replace(".", "")

    try:
        numero = float(texto)
    except ValueError:
        return float("nan")
    return -numero if negativo else numero


def extrair_ano(valor) -> int | None:
    """Le um ano de um cabecalho, aceitando ``2024``, ``31/12/2024`` ou ``FY2024``."""
    if valor is None:
        return None
    if isinstance(valor, (int, np.integer)) and ANO_MINIMO <= int(valor) <= ANO_MAXIMO:
        return int(valor)
    if isinstance(valor, float) and float(valor).is_integer():
        if ANO_MINIMO <= int(valor) <= ANO_MAXIMO:
            return int(valor)
    if hasattr(valor, "year"):
        ano = int(valor.year)
        return ano if ANO_MINIMO <= ano <= ANO_MAXIMO else None

    achados = _ANO_EM_TEXTO.findall(str(valor))
    if not achados:
        return None
    # findall com grupos devolve so o prefixo; refaz a busca completa.
    achados = re.findall(r"(?:19|20)\d{2}", str(valor))
    anos = [int(a) for a in achados if ANO_MINIMO <= int(a) <= ANO_MAXIMO]
    if not anos:
        return None
    # Em "31/12/2024" ou "2023-2024" o ano relevante e o ultimo mencionado.
    return anos[-1]


_CODIGO_ISOLADO = re.compile(r"^\d+(?:\.\d{2})*$")


@dataclass(frozen=True)
class Grade:
    """Uma planilha ja localizada: onde estao os anos, os rotulos e os codigos."""

    dados: pd.DataFrame
    linha_cabecalho: int
    coluna_rotulos: int
    colunas_por_ano: dict[int, int]
    coluna_codigos: int | None = None
    aba: str = ""

    @property
    def anos(self) -> list[int]:
        return sorted(self.colunas_por_ano)


def _parece_codigo_de_conta(valor) -> bool:
    """A celula e um codigo do plano de contas padronizado (``2.01.04``)?"""
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return False
    return bool(_CODIGO_ISOLADO.match(str(valor).strip()))


def _localizar_coluna_de_codigos(corpo: pd.DataFrame, ocupadas: set[int]) -> int | None:
    """Acha a coluna com os codigos CVM, se houver.

    Exige varios codigos com ponto (``3.01``), e nao apenas inteiros soltos: uma
    coluna de numeracao sequencial (1, 2, 3...) nao pode ser confundida com o
    plano de contas.
    """
    for posicao in range(min(corpo.shape[1], 6)):
        if posicao in ocupadas:
            continue
        coluna = corpo.iloc[:, posicao].dropna()
        if coluna.empty:
            continue
        com_ponto = sum(
            1
            for valor in coluna
            if _parece_codigo_de_conta(valor) and "." in str(valor).strip()
        )
        if com_ponto >= 3:
            return posicao
    return None


def _pontuar_linha_como_cabecalho(linha: pd.Series) -> tuple[int, dict[int, int]]:
    """Conta quantos anos distintos uma linha contem, e em que colunas."""
    colunas_por_ano: dict[int, int] = {}
    for posicao, valor in enumerate(linha):
        ano = extrair_ano(valor)
        if ano is not None and ano not in colunas_por_ano:
            colunas_por_ano[ano] = posicao
    return len(colunas_por_ano), colunas_por_ano


def localizar_grade(dados: pd.DataFrame, aba: str = "") -> Grade | None:
    """Encontra a linha de cabecalho com anos e a coluna com os nomes das contas.

    A linha de cabecalho e a que contem mais anos distintos; a coluna de rotulos
    e a primeira, a partir da esquerda, cujo conteudo abaixo do cabecalho e
    majoritariamente texto. Devolve ``None`` quando a planilha nao tem ao menos
    um ano identificavel.
    """
    if dados.empty:
        return None

    melhor_linha, melhor_qtd, melhor_colunas = -1, 0, {}
    for indice in range(min(len(dados), 40)):
        qtd, colunas = _pontuar_linha_como_cabecalho(dados.iloc[indice])
        if qtd > melhor_qtd:
            melhor_linha, melhor_qtd, melhor_colunas = indice, qtd, colunas

    if melhor_qtd == 0:
        return None

    corpo = dados.iloc[melhor_linha + 1 :]
    ocupadas = set(melhor_colunas.values())
    coluna_codigos = _localizar_coluna_de_codigos(corpo, ocupadas)
    if coluna_codigos is not None:
        ocupadas.add(coluna_codigos)

    coluna_rotulos = 0
    for posicao in range(min(dados.shape[1], 6)):
        if posicao in ocupadas:
            continue
        coluna = corpo.iloc[:, posicao]
        preenchidas = coluna.notna().sum()
        if preenchidas == 0:
            continue
        textos = sum(
            1
            for valor in coluna.dropna()
            if isinstance(valor, str) and np.isnan(para_numero(valor))
        )
        if textos >= max(3, 0.5 * preenchidas):
            coluna_rotulos = posicao
            break

    return Grade(
        dados=dados,
        linha_cabecalho=melhor_linha,
        coluna_rotulos=coluna_rotulos,
        colunas_por_ano=melhor_colunas,
        coluna_codigos=coluna_codigos,
        aba=aba,
    )


def linhas_da_grade(grade: Grade) -> list[tuple[str, str | None, dict[int, float]]]:
    """Extrai ``(rotulo, codigo, {ano: valor})`` de cada linha util da planilha."""
    resultado: list[tuple[str, str | None, dict[int, float]]] = []
    corpo = grade.dados.iloc[grade.linha_cabecalho + 1 :]
    for _, linha in corpo.iterrows():
        rotulo = linha.iloc[grade.coluna_rotulos]
        if rotulo is None or (isinstance(rotulo, float) and pd.isna(rotulo)):
            continue
        rotulo = str(rotulo).strip()
        if not rotulo:
            continue

        codigo = None
        if grade.coluna_codigos is not None and grade.coluna_codigos < len(linha):
            bruto = linha.iloc[grade.coluna_codigos]
            if _parece_codigo_de_conta(bruto):
                codigo = str(bruto).strip()

        valores = {
            ano: para_numero(linha.iloc[posicao])
            for ano, posicao in grade.colunas_por_ano.items()
            if posicao < len(linha)
        }
        if all(np.isnan(v) for v in valores.values()):
            continue
        resultado.append((rotulo, codigo, valores))
    return resultado


def carregar_abas(caminho: str | Path) -> dict[str, pd.DataFrame]:
    """Le todas as abas de um arquivo Excel/CSV sem interpretar cabecalhos.

    Ler com ``header=None`` e proposital: o cabecalho real quase nunca esta na
    primeira linha de uma planilha de demonstracoes, e deixar o pandas adivinhar
    atrapalha a deteccao seguinte.
    """
    caminho = Path(caminho)
    if not caminho.exists():
        raise FileNotFoundError(f"Arquivo nao encontrado: {caminho}")

    if caminho.suffix.lower() in {".csv", ".txt", ".tsv"}:
        separador = "\t" if caminho.suffix.lower() == ".tsv" else None
        dados = pd.read_csv(
            caminho, header=None, sep=separador, engine="python", dtype=object
        )
        return {caminho.stem: dados}

    try:
        return pd.read_excel(caminho, sheet_name=None, header=None, dtype=object)
    except Exception as erro:  # noqa: BLE001 - queremos a mensagem original
        raise ValueError(
            f"Nao foi possivel ler {caminho.name} como planilha: {erro}"
        ) from erro

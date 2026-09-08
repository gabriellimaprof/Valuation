"""Cabecalho de trimestre numa planilha nao vira ano, calado.

`extrair_ano` procura quatro digitos em qualquer lugar do texto -- e assim
``1T2026`` casava com ``2026``. Tres colunas de trimestre viravam **uma** coluna
de exercicio, com o numero de tres meses dentro.

O erro era silencioso e grande: duas colunas somem e a que fica sai quatro vezes
menor, sem aviso nenhum. Era o oposto do que este projeto exige -- faltar e
honesto, estar errado nao e.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from valuation.importacao import importar
from valuation.importacao.leitura import e_cabecalho_de_trimestre, extrair_ano

LINHAS = {
    "Receita líquida": [1000.0, 1030.0, 1060.0],
    "Custo dos produtos vendidos": [600.0, 618.0, 636.0],
    "Lucro líquido": [80.0, 82.0, 85.0],
    "Ativo total": [1500.0, 1545.0, 1590.0],
    "Patrimônio líquido": [700.0, 721.0, 742.0],
}


def _planilha(tmp_path: Path, rotulos: list, nome: str = "p.csv") -> Path:
    caminho = tmp_path / nome
    pd.DataFrame(LINHAS, index=rotulos).T.to_csv(caminho)
    return caminho


@pytest.mark.parametrize(
    "cabecalho",
    ["1T2026", "2T2026", "4T2025", "Q1 2026", "1Q2026", "T3 2025", "1T26", "1 TRI 2026"],
)
def test_trimestre_nao_e_lido_como_ano(cabecalho):
    """As grafias que aparecem numa planilha de analista."""
    assert e_cabecalho_de_trimestre(cabecalho)
    assert extrair_ano(cabecalho) is None


@pytest.mark.parametrize(
    "cabecalho,esperado",
    [
        (2024, 2024),
        ("2024", 2024),
        ("31/12/2024", 2024),
        ("FY2024", 2024),
        ("2023-2024", 2024),
        ("Exercício 2024", 2024),
        # **Os que quase casam, e nao podem casar.** Uma regra larga demais
        # transformaria a planilha anual de todo mundo num erro de importacao,
        # que e muito pior do que o defeito que ela conserta.
        ("Ativo 2026", 2026),
        ("Faturamento 2026", 2026),
        ("2024 (R$ mil)", 2024),
    ],
)
def test_o_cabecalho_anual_continua_sendo_lido(cabecalho, esperado):
    assert not e_cabecalho_de_trimestre(cabecalho)
    assert extrair_ano(cabecalho) == esperado


def test_tres_trimestres_nao_colapsam_numa_coluna(tmp_path):
    """O defeito concreto, e ele perdia dados.

    Medido antes da correção: as três colunas viravam **uma**, `2026`, com a
    receita do primeiro trimestre apresentada como a do exercício inteiro.
    """
    caminho = _planilha(tmp_path, ["1T2026", "2T2026", "3T2026"])
    with pytest.raises(ValueError) as erro:
        importar(caminho, empresa="T", anos_maximos=6)

    # A recusa **diz o motivo e nomeia a saída**, em vez de mandar conferir o que
    # o usuário acha que fez: ele pôs cabeçalho, só que de trimestre.
    mensagem = str(erro.value)
    assert "trimestre" in mensagem
    assert "CVM" in mensagem


def test_o_mesmo_trimestre_em_anos_diferentes_tambem_e_recusado(tmp_path):
    """`1T2024`, `1T2025`, `1T2026` produzia três colunas de aparência correta.

    Elas não colapsavam — e cada uma carregava **um trimestre isolado**
    apresentado como o exercício. Menos visível que o caso acima, e igualmente
    errado.
    """
    caminho = _planilha(tmp_path, ["1T2024", "1T2025", "1T2026"])
    with pytest.raises(ValueError, match="trimestre"):
        importar(caminho, empresa="T", anos_maximos=6)


def test_a_planilha_anual_continua_importando(tmp_path):
    """O controle que impede a correção de virar uma recusa geral."""
    caminho = _planilha(tmp_path, [2023, 2024, 2025])
    dfs = importar(caminho, empresa="T", anos_maximos=6)
    assert list(dfs.valores.columns) == [2023, 2024, 2025]
    assert dfs.periodicidade == "anual"

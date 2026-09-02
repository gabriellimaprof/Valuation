"""Numero no padrao brasileiro, numa peca so.

Seis modulos do motor tinham a propria copia disto, e elas **nao eram iguais**.
Este arquivo trava as duas coisas: o formato, e que a copia nao volte.
"""

from __future__ import annotations

import pathlib
import re

import pytest

from valuation import formato


def test_o_decimal_e_virgula_e_o_milhar_e_ponto():
    assert formato.pct(0.1234) == "12,3%"
    assert formato.pct(0.1234, casas=2) == "12,34%"
    assert formato.num(1234567.89) == "1.234.567,9"
    assert formato.multiplo(8.5) == "8,50x"


def test_a_troca_de_separador_nao_colapsa_os_dois():
    """"1,234.5" tem de virar "1.234,5", e não "1.234.5".

    Trocar `,` por `.` e depois `.` por `,` direto transformaria os dois no mesmo
    caractere. O `@` é passagem, e este teste é o que impede alguém de
    "simplificar" as três substituições em duas.
    """
    assert formato.num(1234.5) == "1.234,5"
    assert formato.num(1_000_000.0, casas=0) == "1.000.000"


def test_ausencia_e_declarada_e_nao_zero():
    """Zero se lê como medida; a ausência tem de dizer que não há número."""
    for vazio in (None, float("nan"), float("inf"), "não é número"):
        assert formato.pct(vazio) == "n/d"
        assert formato.num(vazio) == "n/d"


def test_o_marcador_de_ausencia_e_parametro():
    """Os três em uso querem dizer coisas diferentes no contexto de cada um.

    Num documento impresso o travessão lê melhor que "n/d"; numa tabela de
    terminal "n/d" é mais explícito que um traço que pode passar por hífen. O que
    não pode variar é o **número**.
    """
    assert formato.pct(float("nan"), ausente="—") == "—"
    assert formato.num(float("nan"), ausente="n/a") == "n/a"


@pytest.mark.parametrize(
    "modulo",
    ["relatorio", "apresentacao", "margem", "qualitativo", "diagnostico", "cli"],
)
def test_nenhum_modulo_reimplementa_o_formatador(modulo):
    """A sétima cópia reprova aqui.

    Elas divergiam no marcador de ausência — `n/d`, `n/a`, `—` — e uma divergia
    no que importa: `cli._pct` usava `f"{valor:.2%}"`, que produz **"12.34%" com
    ponto decimal**. Formatação inglesa numa CLI em português, discordando do
    relatório e do app sobre o mesmo número.

    Nenhum teste pegava, porque cada módulo testava a própria cópia.
    """
    fonte = pathlib.Path(f"src/valuation/{modulo}.py").read_text(encoding="utf-8")
    corpos = re.findall(r"def _(?:pct|num)\([^)]*\) -> str:\n(.*?)(?=\ndef |\nclass |\Z)", fonte, re.S)
    for corpo in corpos:
        # O corpo pode ter docstring, mas a conta tem de vir de `formato`.
        codigo = re.sub(r'""".*?"""', "", corpo, flags=re.S)
        assert "formato." in codigo, f"{modulo} reimplementa o formatador"
        assert ".replace(" not in codigo, f"{modulo} refaz a troca de separador"


def test_a_cli_fala_portugues():
    """O defeito concreto que a unificação corrigiu."""
    from valuation.cli import _pct

    assert _pct(0.1234) == "12,34%"
    assert "." not in _pct(0.1234).replace("n/a", "")

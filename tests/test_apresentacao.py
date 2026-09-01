"""O material do comite.

O risco aqui nao e errar uma conta -- elas vem do motor, que ja tem teste. E
**parecer um documento pronto e falhar na sala**: buscar um recurso que a rede
nao entrega, cortar um numero na borda de um grafico, ou dizer uma grandeza
diferente da que o app mostra.
"""

from __future__ import annotations

import re

import numpy as np
import pandas as pd
import pytest

from valuation import avaliar
from valuation.apresentacao import (
    barras_horizontais,
    escala_do_documento,
    linhas_no_tempo,
    montar_html,
)


@pytest.fixture
def pagina(empresa_exemplo):
    return montar_html(avaliar(empresa_exemplo), data="01/09/2026")


def test_a_pagina_nao_busca_nada_de_fora(pagina):
    """Arquivo que precisa de rede para se desenhar falha na sala de reunião.

    Sem CDN, sem fonte remota, sem `<script>`. É o que permite abrir o material
    num notebook sem Wi-Fi e imprimir do jeito que ele aparece.
    """
    assert "<script" not in pagina.lower()
    assert "http://" not in pagina
    # `https` só pode aparecer em texto, nunca num atributo que carregue algo.
    for atributo in ("src=", "href=", "@import", "url("):
        assert atributo not in pagina.replace('href="#"', ""), atributo


def test_os_graficos_sao_svg_e_nao_imagem(pagina):
    """SVG imprime igual em qualquer lugar; PNG embutido borra e pesa."""
    assert "<svg" in pagina
    assert "data:image" not in pagina
    # `viewBox` é o que faz o gráfico escalar na impressão em vez de cortar.
    assert "viewBox=" in pagina


def test_a_unidade_vai_no_rotulo_e_nao_dentro_do_numero(pagina):
    """O defeito que este projeto já corrigiu na tela, e que a primeira versão
    desta página repetiu.

    "63.902.487.991,2 R$" não cabe num cartão e quebra em duas linhas. A unidade
    é convenção de cabeçalho: aparece uma vez, no rótulo.
    """
    # O rotulo do cartao carrega a unidade entre parenteses.
    assert re.search(r"Equity value \([^)]*\)", pagina)
    # E o valor do cartao nao repete "R$" colado no numero.
    valores = re.findall(r'<div class="valor">([^<]*)</div>', pagina)
    assert valores
    assert not any(v.strip().endswith("R$") for v in valores)


def test_a_escala_e_uma_so_para_o_documento():
    """Trocar de escala entre linhas faz comparar bilhão com milhão sem perceber."""
    assert escala_do_documento([63_902_487_991.0, 1_841_890_000.0]) == (1e9, "bi")
    assert escala_do_documento([4_500_000.0, 120_000.0]) == (1e6, "mi")
    assert escala_do_documento([820.0, 91.0]) == (1.0, "")
    # Sem numero mensuravel, nao ha escala a inventar.
    assert escala_do_documento([float("nan"), None]) == (1.0, "")


def test_o_rotulo_do_valor_cabe_dentro_do_grafico():
    """Número cortado na borda é pior que número nenhum: parece um valor e não é.

    A primeira versão reservava 90px para o rótulo e saía "63.196.776.991," —
    truncado no meio. A folga passou para 120px, e a escala do documento encolhe
    o texto que entra ali.
    """
    svg = barras_horizontais(
        [("Uma linha", 63_196_776_991.0), ("Outra", 1_841_890_000.0)],
        unidade="R$ bi",
        divisor=1e9,
    )
    # A barra mais longa termina com folga para o texto do valor.
    fins = [
        float(m.group(1)) + float(m.group(2))
        for m in re.finditer(r'<rect x="(\d+)" y="\d+" width="([\d.]+)"', svg)
    ]
    assert max(fins) <= 760 - 100, "a barra não deixa espaço para o rótulo do valor"
    # E o numero saiu na escala, e nao em reais cheios.
    assert "63,2" in svg


def test_grafico_sem_dado_nao_desenha_eixo_vazio():
    """Eixo sem série é pior que ausência: promete conteúdo e não entrega."""
    assert linhas_no_tempo({}) == ""
    assert linhas_no_tempo({"Só um ponto": pd.Series([0.1], index=[2024])}) == ""
    assert barras_horizontais([]) == ""
    assert barras_horizontais([("Sem número", float("nan"))]) == ""


def test_o_diagnostico_ausente_e_declarado(pagina):
    """"Sem achados" e "não verificado" não são a mesma coisa.

    Sumir com a seção faria o comitê supor que o modelo passou pela crítica e
    estava limpo — que é exatamente a leitura errada.
    """
    assert "Diagnóstico não executado" in pagina


def test_a_pagina_traz_os_avisos_e_nao_os_esconde(empresa_exemplo):
    """Os achados vão no documento, e não num anexo.

    A pergunta que vem da mesa é a que o diagnóstico antecipa; escondê-la não a
    faz sumir, só faz o analista ser pego por ela.
    """
    from valuation.diagnostico import diagnosticar
    from valuation.modelo import substituir_varios

    empresa = substituir_varios(
        empresa_exemplo, {"perpetuidade.roic_perpetuidade": 0.40}
    )
    resultado = avaliar(empresa)
    pagina = montar_html(resultado, diagnostico=diagnosticar(resultado))

    assert "O que pode derrubar a tese" in pagina
    assert 'class="aviso' in pagina


def test_o_numero_da_pagina_e_o_mesmo_do_motor(empresa_exemplo):
    """A página formata; ela não calcula.

    Duas implementações do mesmo número divergem no dia em que uma delas muda, e
    a divergência apareceria entre o que o comitê vê e o que o app mostra.
    """
    resultado = avaliar(empresa_exemplo)
    pagina = montar_html(resultado)

    wacc = resultado.custo_capital.wacc_brl
    esperado = f"{wacc * 100:.1f}%".replace(".", ",")
    assert esperado in pagina


def test_a_pagina_escapa_o_que_vem_de_fora(empresa_exemplo):
    """Nome de empresa é campo livre, e ele vai para dentro do HTML."""
    from dataclasses import replace

    empresa = replace(empresa_exemplo, nome="<script>alert(1)</script> S.A.")
    pagina = montar_html(avaliar(empresa))

    assert "<script>alert" not in pagina
    assert "&lt;script&gt;" in pagina

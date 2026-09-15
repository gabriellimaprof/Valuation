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


def _lucro_residual_de_teste():
    from valuation.lucro_residual import PremissasLucroResidual, avaliar_lucro_residual

    premissas = PremissasLucroResidual(
        patrimonio_inicial=178_900.0,
        roe=[0.121] * 5,
        payout=[0.35] * 5,
        roe_perpetuo=0.1335,
    )
    return avaliar_lucro_residual(premissas, ke=0.1335, ano_base=2025)


def test_o_material_do_banco_nao_monta_um_dcf(empresa_exemplo):
    """Instituição financeira não tem DCF, e o material não pode inventar um.

    Para uma indústria a dívida financia o ativo; para um banco ela **é o
    insumo**. A tela de Valor desvia antes de qualquer número aparecer e o
    relatório markdown também — faltava a página do comitê, que montaria
    Enterprise Value, ponte e WACC que ninguém calculou.

    Contradizer no papel o número que a tela mostrou é o pior lugar possível
    para uma divergência: o material é o que sobra depois que a tela fecha.
    """
    from dataclasses import replace

    pagina = montar_html(
        None,
        lucro_residual=_lucro_residual_de_teste(),
        empresa=replace(empresa_exemplo, nome="Banco Teste"),
        data="01/09/2026",
    )

    assert "Enterprise Value" not in pagina
    assert "Dívida líquida" not in pagina
    assert "perpétuo" not in pagina
    # O que ele traz no lugar.
    assert "P/VP" in pagina
    assert "lucro residual" in pagina.lower()
    # E diz **por que** não é um DCF, em vez de só omiti-lo.
    assert "Por que este modelo, e não um DCF" in pagina


def test_o_material_do_banco_declara_o_que_nao_avaliou(empresa_exemplo):
    """"Não foi verificado" e "verificado e está bem" não são a mesma coisa.

    O universo de comparáveis exclui bancos de propósito, e o diagnóstico roda
    sobre um DCF que não foi usado. Sumir com as duas seções faria o comitê supor
    que elas passaram.
    """
    from dataclasses import replace

    pagina = montar_html(
        None,
        lucro_residual=_lucro_residual_de_teste(),
        empresa=replace(empresa_exemplo, nome="Banco Teste"),
    )
    assert "O que não foi avaliado aqui" in pagina
    assert "exclui bancos e seguradoras" in pagina
    assert "capital regulatório" in pagina


def test_sem_resultado_e_sem_banco_a_pagina_recusa(empresa_exemplo):
    """Página sem DCF e sem lucro residual não tem o que descrever.

    Levantar aqui é melhor que devolver uma página vazia com cara de pronta.
    """
    with pytest.raises(ValueError, match="lucro_residual"):
        montar_html(None)


def test_a_tabela_repete_o_cabecalho_quando_atravessa_a_pagina():
    """Metade de tabela sem cabeçalho chega como coluna de números sem nome.

    Conferido no PDF de verdade: uma tabela de 40 linhas ocupa duas páginas A4 e
    o cabeçalho aparece nas duas.
    """
    from valuation.apresentacao import CSS

    assert "display: table-header-group" in CSS
    assert "page-break-inside: avoid" in CSS


def test_o_material_traz_onde_a_companhia_e_incomum(empresa_exemplo):
    """"Margem de 22%" não diz se é boa; "no percentil 47 de 413" diz.

    É o tipo de âncora que um comitê pede. Não cabem as 22 linhas da tela — num
    material impresso a tabela longa vira página virada —, então entram as
    **mais incomuns**, que são as que a mesa vai perguntar.
    """
    import pandas as pd

    from valuation.historico import analisar
    from valuation.importacao import Demonstracoes

    anos = [2022, 2023, 2024, 2025]
    valores = pd.DataFrame(
        {
            ano: {
                "receita_liquida": 1000.0 + 100 * i,
                "custo_produtos_vendidos": 600.0 + 60 * i,
                "ebit": 200.0 + 20 * i,
                "depreciacao_amortizacao": 50.0,
                "lucro_liquido": 120.0,
                "lucro_antes_impostos": 170.0,
                "impostos": 50.0,
                "ativo_total": 1500.0,
                "patrimonio_liquido": 700.0,
                "capex": 60.0,
                "contas_receber": 200.0,
                "estoques": 150.0,
                "fornecedores": 100.0,
            }
            for i, ano in enumerate(anos)
        }
    )
    analise = analisar(Demonstracoes(empresa="T", valores=valores, unidade="R$ mi"))
    pagina = montar_html(avaliar(empresa_exemplo), analise=analise)

    assert "Onde a companhia cai na base brasileira" in pagina
    assert "Percentil" in pagina
    assert "Mediana da base" in pagina


def test_o_material_recusa_a_tabela_da_base_numa_serie_trimestral(empresa_exemplo):
    """Meia tabela comparável no papel engana mais do que ajuda.

    A base é medida em exercícios, e parte dos indicadores não atravessa a
    frequência — ROIC e dívida sobre EBITDA saem a um quarto num trimestre. Na
    tela há espaço para explicar linha a linha; num material impresso, não.
    """
    import pandas as pd

    from valuation.historico import analisar
    from valuation.importacao import Demonstracoes

    valores = pd.DataFrame(
        {
            rotulo: {
                "receita_liquida": 250.0,
                "custo_produtos_vendidos": 150.0,
                "ebit": 50.0,
                "patrimonio_liquido": 700.0,
            }
            for rotulo in ("1T25", "2T25", "3T25")
        }
    )
    analise = analisar(
        Demonstracoes(
            empresa="T",
            valores=valores,
            unidade="R$ mi",
            periodicidade="trimestral",
        )
    )
    pagina = montar_html(avaliar(empresa_exemplo), analise=analise)

    assert "Onde a companhia cai na base brasileira" in pagina
    assert "Não incluído" in pagina
    assert "trimestral" in pagina


# ---------------------------------------------------------------------------
# As premissas, as contas e a faixa do valor
# ---------------------------------------------------------------------------


def test_o_material_abre_as_premissas_e_as_contas(pagina):
    """O material mostrava o resultado e escondia a conta.

    Quem discorda do valor discorda de uma premissa, e para isso precisa vê-las:
    o custo de capital passo a passo, a perpetuidade com a conta aberta, a ponte
    item a item e a projeção até o FCFF.
    """
    for secao in (
        "Custo de capital",
        "Perpetuidade",
        "Do Enterprise Value ao acionista",
        "As contas, ano a ano",
        "Do fluxo ao valor presente",
    ):
        assert secao in pagina, secao

    # A montagem do WACC, e não só o número final.
    for etapa in ("Beta realavancado", "Beta desalavancado", "Kd após IR", "Peso da dívida"):
        assert etapa in pagina, etapa
    # A projeção inteira, com as linhas que levam ao fluxo.
    for linha in ("NOPAT", "(-) Capex", "FCFF (fluxo para a firma)", "Fator de desconto"):
        assert linha in pagina, linha


def test_os_numeros_das_contas_sao_os_do_motor(empresa_exemplo):
    """A página formata; ela não recalcula."""
    from valuation import avaliar
    from valuation.apresentacao import _num

    resultado = avaliar(empresa_exemplo)
    pagina = montar_html(resultado)
    dcf = resultado.dcf

    assert _num(dcf.valor_terminal) in pagina
    assert _num(dcf.fatores[-1], 4) in pagina
    assert _num(resultado.custo_capital.beta_realavancado, 2) in pagina


def test_a_perpetuidade_mostra_a_conta_e_o_reinvestimento(empresa_exemplo):
    """Maior parcela do valor: no papel, a primeira pergunta da mesa."""
    from valuation import avaliar

    pagina = montar_html(avaliar(empresa_exemplo))
    assert "Reinvestimento normalizado" in pagina
    assert "NOPAT do último ano" in pagina
    assert "Trazido a valor presente" in pagina


def test_a_faixa_do_valor_entra_com_o_caso_base_no_centro(empresa_exemplo):
    """A célula do meio do mapa de calor é o número principal."""
    from valuation import avaliar, pacote_padrao
    from valuation.apresentacao import _num

    resultado = avaliar(empresa_exemplo)
    pacote = pacote_padrao(empresa_exemplo, resultado)
    pagina = montar_html(resultado, sensibilidades=pacote)

    assert "Quanto o valor se mexe" in pagina
    assert "WACC contra crescimento perpétuo" in pagina
    assert "Cenários coerentes" in pagina
    assert "O que mais move o valor" in pagina
    assert _num(resultado.equity_value) in pagina


def test_sem_pacote_a_pagina_nao_inventa_a_faixa(pagina):
    """Faixa sem cálculo seria pior que ausência: pareceria medida."""
    assert "Quanto o valor se mexe" not in pagina


def test_o_monte_carlo_entra_com_o_caso_base_marcado(empresa_exemplo):
    from valuation import Distribuicao, avaliar, monte_carlo

    resultado = avaliar(empresa_exemplo)
    simulacao = monte_carlo(
        empresa_exemplo,
        [
            Distribuicao(
                caminho="operacionais.margem_ebitda",
                tipo="triangular",
                parametros={"minimo": 0.16, "moda": 0.20, "maximo": 0.24},
            )
        ],
        simulacoes=200,
    )
    pagina = montar_html(resultado, simulacao=simulacao)

    assert "Monte Carlo" in pagina
    assert "Percentil" in pagina
    assert "caso base" in pagina


def test_o_material_do_banco_nao_ganha_as_secoes_do_dcf(empresa_exemplo):
    """O caminho do banco continua sem DCF — nem premissas, nem contas, nem faixa."""
    from dataclasses import replace

    pagina = montar_html(
        None,
        lucro_residual=_lucro_residual_de_teste(),
        empresa=replace(empresa_exemplo, nome="Banco Teste"),
    )
    for secao in ("As contas, ano a ano", "Quanto o valor se mexe", "Custo de capital"):
        assert secao not in pagina, secao


def test_o_grafico_de_receita_marca_onde_comeca_a_projecao(empresa_exemplo):
    """Entregue e projetado num gráfico contínuo se leem como uma série só."""
    import pandas as pd

    from valuation import avaliar
    from valuation.historico import analisar
    from valuation.importacao import Demonstracoes

    anos = [2022, 2023, 2024, 2025]
    valores = pd.DataFrame(
        {
            ano: {
                "receita_liquida": 1000.0 + 100 * i,
                "custo_produtos_vendidos": 600.0 + 60 * i,
                "ebit": 200.0 + 20 * i,
                "depreciacao_amortizacao": 50.0,
                "lucro_liquido": 120.0,
                "lucro_antes_impostos": 170.0,
                "impostos": 50.0,
                "ativo_total": 1500.0,
                "patrimonio_liquido": 700.0,
                "capex": 60.0,
            }
            for i, ano in enumerate(anos)
        }
    )
    analise = analisar(Demonstracoes(empresa="T", valores=valores, unidade="R$ mi"))
    pagina = montar_html(avaliar(empresa_exemplo), analise=analise)

    assert "entregue e projetado" in pagina
    assert "projetado" in pagina
    assert "stroke-dasharray" in pagina


def test_o_mapa_de_calor_pinta_o_fundo_e_nao_busca_imagem(empresa_exemplo):
    """Cor de fundo por estilo embutido: nada de imagem, nada de rede."""
    from valuation import avaliar, pacote_padrao

    resultado = avaliar(empresa_exemplo)
    pagina = montar_html(
        resultado, sensibilidades=pacote_padrao(empresa_exemplo, resultado)
    )
    assert 'style="background:#' in pagina
    assert "url(" not in pagina
    assert "<script" not in pagina.lower()


# ---------------------------------------------------------------------------
# O que so apareceu com a pagina renderizada
# ---------------------------------------------------------------------------


def test_a_escala_compoe_com_a_unidade_em_vez_de_colar_nela():
    """"R$ milhões mil" não é rótulo: é o que sobra de colar duas escalas.

    Visto na página da Vivara: equity de R$ 3,5 bilhões escrito como "3,5" sob
    "EQUITY VALUE (R$ MILHÕES MIL)". As escalas somam — milhões com mil dá
    bilhões.
    """
    from valuation.apresentacao import unidade_na_escala

    assert unidade_na_escala("R$ milhões", "mil") == "R$ bilhões"
    assert unidade_na_escala("R$ milhões", "mi") == "R$ trilhões"
    assert unidade_na_escala("R$ mil", "mil") == "R$ milhões"
    assert unidade_na_escala("R$", "bi") == "R$ bilhões"
    # Sem escala no documento, a unidade fica como está.
    assert unidade_na_escala("R$ milhões", "") == "R$ milhões"
    # Unidade livre não ganha composição inventada.
    assert unidade_na_escala("sacas", "mil") == "sacas mil"


def test_a_pagina_nao_escreve_milhoes_mil(empresa_exemplo):
    from dataclasses import replace

    from valuation import avaliar

    grande = replace(
        empresa_exemplo,
        unidade="R$ milhões",
        operacionais=replace(empresa_exemplo.operacionais, receita_base=8_000_000.0),
    )
    pagina = montar_html(avaliar(grande))
    assert "milhões mil" not in pagina
    assert "R$ bilhões" in pagina or "R$ trilhões" in pagina


def test_os_avisos_saem_com_negrito_e_nao_com_asterisco(empresa_exemplo):
    """Os achados são markdown — eles alimentam a tela, o relatório e a página."""
    from valuation.apresentacao import _negrito

    assert _negrito("cresce **para sempre**") == "cresce <strong>para sempre</strong>"
    # E o que vem de fora continua escapado.
    assert _negrito("<script>x</script>") == "&lt;script&gt;x&lt;/script&gt;"

    from valuation.diagnostico import diagnosticar
    from valuation.modelo import substituir_varios
    from valuation import avaliar

    empresa = substituir_varios(
        empresa_exemplo, {"perpetuidade.roic_perpetuidade": 0.40}
    )
    resultado = avaliar(empresa)
    pagina = montar_html(resultado, diagnostico=diagnosticar(resultado))
    # So os blocos de achado: o CSS da pagina tem um comentario com asteriscos,
    # e proibi-los na pagina inteira travaria a documentacao do proprio estilo.
    blocos = re.findall(r'<div class="aviso.*?</div></div>', pagina, re.S)
    assert blocos, "o diagnostico nao produziu achado nenhum"
    assert not any("**" in b for b in blocos), blocos
    assert any("<strong>" in b for b in blocos)


def test_a_tabela_do_ifrs16_usa_o_formato_de_cada_linha():
    """Margem é percentual; dívida é moeda na escala do documento.

    Numa tabela com formato por coluna, 29,4% de margem saía como "0,3" e a
    dívida ficava em milhões num documento em bilhões.
    """
    import pandas as pd

    from valuation.apresentacao import _ifrs16_no_material

    class _Visao:
        aluguel = pd.Series([134.6], index=[2025])
        margem_ebitda_reportada = pd.Series([0.294], index=[2025])
        margem_ebitda = pd.Series([0.249], index=[2025])
        divida_bruta_reportada = pd.Series([1228.5], index=[2025])
        divida_bruta = pd.Series([531.3], index=[2025])

    html_ = _ifrs16_no_material(_Visao(), divisor=1000.0, unidade="R$ bilhões")
    assert "29,4%" in html_ and "24,9%" in html_
    assert "1,2" in html_ and "0,5" in html_
    assert "R$ bilhões" in html_


"""Testes da leitura de qualidade dos lucros.

A regra que estrutura: o veredito e o pior sinal, e nao a media. Boa conversao
nao cancela juro capitalizado -- sao problemas diferentes, e quem le precisa
ver os dois.
"""

from __future__ import annotations

import pathlib

from pathlib import Path

import pandas as pd
import pytest

from valuation.historico import AnaliseHistorica, analisar
from valuation.importacao.cvm import importar_cvm
from valuation.qualidade import (
    ATENCAO,
    BOM,
    RUIM,
    SEM_DADOS,
    avaliar_qualidade,
)

DADOS = Path(__file__).parent / "dados" / "cvm"


def _analise(**medianas) -> AnaliseHistorica:
    """Analise sintetica: cada indicador com o mesmo valor nos dois anos."""
    from valuation.importacao import Demonstracoes

    tabela = pd.DataFrame({2023: dict(medianas), 2024: dict(medianas)})
    vazio = Demonstracoes(
        empresa="Teste",
        valores=pd.DataFrame({2023: {"receita_liquida": 1.0}, 2024: {"receita_liquida": 1.0}}),
    )
    return AnaliseHistorica(demonstracoes=vazio, indicadores=tabela)


def test_conversao_alta_e_boa():
    q = avaliar_qualidade(_analise(**{"Conversao de caixa (FCO / EBITDA)": 1.05}))
    conversao = next(s for s in q.sinais if s.codigo == "conversao")
    assert conversao.veredito == BOM


def test_conversao_baixa_sem_crescimento_e_ruim():
    q = avaliar_qualidade(
        _analise(
            **{
                "Conversao de caixa (FCO / EBITDA)": 0.08,
                "Crescimento da receita": 0.02,
            }
        )
    )
    conversao = next(s for s in q.sinais if s.codigo == "conversao")
    assert conversao.veredito == RUIM
    assert q.veredito == RUIM


def test_conversao_baixa_com_crescimento_e_so_atencao():
    """Empresa que cresce rapido prende caixa no giro; isso nao e defeito."""
    q = avaliar_qualidade(
        _analise(
            **{
                "Conversao de caixa (FCO / EBITDA)": 0.08,
                "Crescimento da receita": 0.30,
            }
        )
    )
    conversao = next(s for s in q.sinais if s.codigo == "conversao")
    assert conversao.veredito == ATENCAO
    assert "crescendo" in conversao.detalhe


def test_juro_que_nao_sai_do_caixa_e_atencao():
    """Descolamento entre o P75 e o P90 da base, com Kd ainda plausivel.

    Os dois cortes se movem entre safras -- o P75 caiu de 16,9 para 10,0 p.p. de
    2020-2024 para 2021-2025 --, entao o caso e montado **a partir deles** e nao
    de um numero fixo. Com 0,22 fixo, este teste virou "ruim" sozinho quando a
    calibracao mudou, sem que nada estivesse errado.
    """
    from valuation.qualidade import JURO_DESCOLADO, JURO_MUITO_DESCOLADO

    entre_os_dois = (JURO_DESCOLADO + JURO_MUITO_DESCOLADO) / 2
    q = avaliar_qualidade(
        _analise(
            **{
                "Conversao de caixa (FCO / EBITDA)": 1.0,
                "Custo da divida efetivo": 0.03 + entre_os_dois,
                "Custo da divida pelo caixa": 0.03,
            }
        )
    )
    juros = next(s for s in q.sinais if s.codigo == "juros")
    assert juros.veredito == ATENCAO
    assert "25% maiores" in juros.detalhe
    # E o veredito geral nao pode ser "bom" so porque a conversao esta boa.
    assert q.veredito == ATENCAO


def test_descolamento_normal_do_mercado_nao_vira_acusacao():
    """A mediana brasileira descola alguns pontos; isso nao pode acusar ninguem.

    O corte original era 2 p.p. e disparava em 82,3% das 368 companhias que
    publicam os dois numeros. Sinal que dispara em quatro de cada cinco nao
    dirige atencao: gasta ela.

    **A mediana se move entre safras**, e o teste nao pode pinar o numero: em
    2020-2024 era 8,2 p.p. e em 2021-2025 e 5,9. O que ele trava e a propriedade
    -- descolamento na mediana da base nao acusa -- e o fato de a frase citar a
    referencia, sem a qual o leitor toma o normal do mercado por irregularidade.
    """
    from valuation.referencias import DESCOLAMENTO_DO_JURO, DESCOLAMENTO_QUANTIS

    mediana = DESCOLAMENTO_DO_JURO[1][DESCOLAMENTO_QUANTIS.index(0.50)]
    q = avaliar_qualidade(
        _analise(
            **{
                "Conversao de caixa (FCO / EBITDA)": 1.0,
                "Custo da divida efetivo": 0.06 + mediana,
                "Custo da divida pelo caixa": 0.06,
            }
        )
    )
    juros = next(s for s in q.sinais if s.codigo == "juros")
    assert juros.veredito == BOM
    assert f"{mediana * 100:.1f}".replace(".", ",") in juros.detalhe
    assert f"{DESCOLAMENTO_DO_JURO[0]} companhias" in juros.detalhe


def test_despesa_financeira_alta_demais_nao_e_medivel():
    """Denominador minusculo faz a razao deixar de ser custo de divida.

    E o caso da WEG: caixa liquido, pouca divida, e uma linha de despesa
    financeira que carrega cambio de todo o passivo. Acusar por artefato de
    denominador e pior do que dizer que nao da para medir.
    """
    q = avaliar_qualidade(
        _analise(
            **{
                "Conversao de caixa (FCO / EBITDA)": 1.0,
                "Custo da divida efetivo": 0.45,
                "Custo da divida pelo caixa": 0.04,
            }
        )
    )
    juros = next(s for s in q.sinais if s.codigo == "juros")
    assert juros.veredito == SEM_DADOS
    assert "não é custo de dívida" in juros.detalhe


def test_o_pior_sinal_manda():
    q = avaliar_qualidade(
        _analise(
            **{
                "Conversao de caixa (FCO / EBITDA)": 0.05,
                "Crescimento da receita": 0.01,
                "Custo da divida efetivo": 0.10,
                "Custo da divida pelo caixa": 0.10,
            }
        )
    )
    assert q.veredito == RUIM
    assert q.por_severidade[0].veredito == RUIM


def test_sem_dfc_nao_finge_veredito():
    q = avaliar_qualidade(_analise(**{"Margem EBIT": 0.20}))
    assert q.veredito == SEM_DADOS
    assert "Faltam dados" in q.resumo


def test_giro_que_libera_caixa_e_bom():
    q = avaliar_qualidade(
        _analise(
            **{
                "Conversao de caixa (FCO / EBITDA)": 1.0,
                "Investimento em giro (DFC) / Receita": -0.03,
            }
        )
    )
    giro = next(s for s in q.sinais if s.codigo == "giro")
    assert giro.veredito == BOM


def test_todo_sinal_tem_icone_e_explicacao():
    q = avaliar_qualidade(_analise(**{"Conversao de caixa (FCO / EBITDA)": 0.95}))
    for sinal in q.sinais:
        assert sinal.icone
        assert sinal.titulo


# ---------------------------------------------------------------------------
# Contra dado real
# ---------------------------------------------------------------------------


def test_weg_tem_lucro_que_vira_caixa():
    """A WEG converte bem e nao tem juro descolado: o veredito nao pode ser ruim."""
    weg = importar_cvm(5410, [2023, 2024], cache=DADOS)
    q = avaliar_qualidade(analisar(weg))

    assert q.veredito in {BOM, ATENCAO}
    assert q.conversao_mediana > 0.7
    codigos = {s.codigo for s in q.sinais}
    assert codigos == {"conversao", "giro", "juros"}


def test_o_corte_de_conversao_fraca_nao_pode_acusar_metade_do_mercado():
    """Calibracao medida: 0,60 acusava 47,3% das 423 companhias da base.

    A mediana brasileira converte 64% do EBITDA em caixa -- nao por falta de
    qualidade, mas porque o FCO e liquido de imposto e, em dois tercos das
    companhias, tambem de juros, enquanto o EBITDA e antes dos dois. Um corte
    que classifica o tipico como fraco gasta a atencao do leitor.
    """
    from valuation.qualidade import CONVERSAO_BOA, CONVERSAO_FRACA
    from valuation import referencias

    mediana_da_base = referencias.BASE["Conversao de caixa (FCO / EBITDA)"][1][3]
    assert CONVERSAO_FRACA < mediana_da_base, "o corte de 'fraca' pegaria a mediana"
    # E "boa" continua sendo uma barra alta: o quartil superior da base.
    assert referencias.posicao("Conversao de caixa (FCO / EBITDA)", CONVERSAO_BOA) > 0.70


def test_a_conversao_explica_que_parte_da_distancia_e_estrutural():
    q = avaliar_qualidade(_analise(**{"Conversao de caixa (FCO / EBITDA)": 0.64}))
    conversao = next(s for s in q.sinais if s.codigo == "conversao")
    assert "líquido de imposto" in conversao.detalhe
    assert "estrutural" in conversao.detalhe


def test_a_reclassificacao_do_juro_aparece_no_sinal():
    """Quem comparar com a demonstracao publicada vai ver diferenca."""
    import pandas as pd

    from valuation.historico import analisar
    from valuation.importacao import Demonstracoes

    valores = pd.DataFrame(
        {
            2023: {
                "receita_liquida": 1000.0, "ebit": 150.0, "depreciacao_amortizacao": 50.0,
                "fluxo_operacional": 180.0, "juros_pagos_no_financiamento": 20.0,
            },
            2024: {
                "receita_liquida": 1100.0, "ebit": 165.0, "depreciacao_amortizacao": 55.0,
                "fluxo_operacional": 200.0, "juros_pagos_no_financiamento": 22.0,
            },
        }
    )
    sinal = next(
        s
        for s in avaliar_qualidade(analisar(Demonstracoes(empresa="X", valores=valores))).sinais
        if s.codigo == "conversao"
    )
    assert "financiamento no período" in sinal.detalhe
    assert "mudou de classificação" not in sinal.detalhe


def test_companhia_que_troca_de_classificacao_e_apontada():
    """A WEG fez isso entre 2022 e 2023: a serie dela nao era comparavel consigo."""
    import pandas as pd

    from valuation.historico import analisar
    from valuation.importacao import Demonstracoes

    valores = pd.DataFrame(
        {
            2023: {
                "receita_liquida": 1000.0, "ebit": 150.0, "depreciacao_amortizacao": 50.0,
                "fluxo_operacional": 180.0, "juros_pagos_no_financiamento": 20.0,
            },
            2024: {
                "receita_liquida": 1100.0, "ebit": 165.0, "depreciacao_amortizacao": 55.0,
                "fluxo_operacional": 200.0,
            },
        }
    )
    sinal = next(
        s
        for s in avaliar_qualidade(analisar(Demonstracoes(empresa="X", valores=valores))).sinais
        if s.codigo == "conversao"
    )
    assert "em 2023" in sinal.detalhe
    assert "nem consigo mesma" in sinal.detalhe


# ---------------------------------------------------------------------------
# EBITDA -> CGO -> FCO: separar a operacao do que vem depois dela
# ---------------------------------------------------------------------------


def _com_dfc(cgo, giro, imposto, juro, ebit=800.0, da=200.0):
    """Demonstracoes minimas com a seccao operacional aberta."""
    import pandas as pd

    from valuation.importacao import Demonstracoes

    fco = cgo + giro - abs(imposto) - abs(juro)
    valores = pd.DataFrame(
        {
            2023: {
                "receita_liquida": 5000.0, "ebit": ebit,
                "depreciacao_amortizacao": da, "lucro_liquido": 500.0,
                "lucro_antes_impostos": 700.0, "impostos": 200.0,
                "patrimonio_liquido": 3000.0, "ativo_total": 6000.0,
                "caixa_das_operacoes": cgo, "fluxo_operacional": fco,
                "variacao_capital_giro": giro, "impostos_pagos": imposto,
                "juros_pagos": juro,
            },
            2024: {
                "receita_liquida": 5200.0, "ebit": ebit,
                "depreciacao_amortizacao": da, "lucro_liquido": 520.0,
                "lucro_antes_impostos": 720.0, "impostos": 200.0,
                "patrimonio_liquido": 3100.0, "ativo_total": 6200.0,
                "caixa_das_operacoes": cgo, "fluxo_operacional": fco,
                "variacao_capital_giro": giro, "impostos_pagos": imposto,
                "juros_pagos": juro,
            },
        }
    )
    return Demonstracoes(empresa="Teste", valores=valores, unidade="R$ milhões")


def test_a_ponte_do_caixa_reconstroi_o_fco():
    """`FCO = CGO + giro + outros - imposto - juro`, a identidade da DFC."""
    from valuation.historico import analisar
    from valuation.qualidade import ponte_do_caixa

    ponte = ponte_do_caixa(analisar(_com_dfc(cgo=1100.0, giro=-100.0, imposto=150.0, juro=250.0)))
    assert ponte is not None
    assert ponte.fecha
    assert ponte.ebitda == pytest.approx(1000.0)
    assert ponte.conversao_operacional == pytest.approx(1.10)
    assert ponte.conversao_final == pytest.approx(0.60)


def test_cgo_bom_com_fco_fraco_nao_acusa_a_operacao():
    """O ponto: FCO fraco por juro e imposto nao e operacao que nao gera caixa.

    Medido no consolidado de 2024, **190 das 371 companhias** com os dois
    numeros tem CGO acima de 78% do EBITDA e FCO abaixo disso -- metade da base.
    Dizer "o EBITDA nao vira caixa" nelas manda o analista procurar receita
    ficticia onde o que ha e divida cara.
    """
    from valuation.historico import analisar
    from valuation.qualidade import avaliar_qualidade

    # Opera bem (CGO = 110% do EBITDA) e paga muito juro (40% do EBITDA).
    dfs = _com_dfc(cgo=1100.0, giro=-50.0, imposto=100.0, juro=400.0)
    sinal = next(
        s for s in avaliar_qualidade(analisar(dfs)).sinais if s.codigo == "conversao"
    )

    assert sinal.valor < 0.78, "o caso montado precisa ter FCO fraco"
    assert "operação gera caixa" in sinal.titulo
    assert "juro" in sinal.detalhe
    # E o culpado vem com o tamanho: "esta no juro" sem numero nao dirige nada.
    assert "40%" in sinal.detalhe


def test_cgo_fraco_continua_acusando_a_operacao():
    """A ressalva nao pode virar desculpa: CGO baixo e a operacao mesmo."""
    from valuation.historico import analisar
    from valuation.qualidade import avaliar_qualidade

    dfs = _com_dfc(cgo=300.0, giro=-100.0, imposto=50.0, juro=50.0)
    sinal = next(
        s for s in avaliar_qualidade(analisar(dfs)).sinais if s.codigo == "conversao"
    )
    assert "operação gera caixa" not in sinal.titulo


def test_cgo_fraco_ganha_o_nome_certo():
    """"Sobra pouco" e "a operacao nao converte" sao diagnosticos diferentes.

    Quando o CGO tambem esta baixo, a distancia aparece **antes** de giro,
    imposto e juro -- entao nao e consumo abaixo da operacao, e o sinal precisa
    dizer isso em vez de mandar procurar nos tres.
    """
    from valuation.historico import analisar
    from valuation.qualidade import CGO_FRACO, avaliar_qualidade

    dfs = _com_dfc(cgo=400.0, giro=-50.0, imposto=50.0, juro=50.0)
    sinal = next(
        s for s in avaliar_qualidade(analisar(dfs)).sinais if s.codigo == "conversao"
    )
    assert sinal.veredito == "ruim"
    assert "caixa das operações" in sinal.titulo
    assert "não se realiza" in sinal.detalhe
    assert 400.0 / 1000.0 < CGO_FRACO


def test_os_cortes_do_cgo_sao_os_percentis_da_safra():
    """Corte calibrado fora da safra vira ruido -- o projeto ja pagou isso duas vezes.

    `CGO_BOM` e o **P25** e nao o P75 como em `CONVERSAO_BOA`, de proposito: ele
    nao pergunta "esta entre as melhores?", pergunta "a operacao converte?".
    """
    from valuation import referencias
    from valuation.qualidade import CGO_BOM, CGO_FRACO

    n, quantis = referencias.BASE["Conversao operacional (CGO / EBITDA)"]
    p10, p25 = quantis[1], quantis[2]

    assert CGO_BOM == pytest.approx(p25, abs=0.01), f"P25 = {p25}"
    assert CGO_FRACO == pytest.approx(p10, abs=0.01), f"P10 = {p10}"
    assert CGO_FRACO < CGO_BOM
    # E a mediana passa de 100%: a conversao operacional nao se le como a final.
    assert quantis[3] > 1.0


def test_o_sinal_cita_o_percentil_da_conversao_operacional():
    """Numa conversao cuja mediana passa de 100%, 90% parece otimo e e quartil inferior.

    O corte absoluto diz o que a conta significa; o percentil diz se o numero e
    incomum aqui. Sem o segundo, o leitor aceita o quarto inferior por ele
    parecer um numero alto.
    """
    from valuation.historico import analisar
    from valuation.qualidade import avaliar_qualidade

    dfs = _com_dfc(cgo=1100.0, giro=-50.0, imposto=100.0, juro=400.0)
    sinal = next(
        s for s in avaliar_qualidade(analisar(dfs)).sinais if s.codigo == "conversao"
    )
    assert "percentil" in sinal.detalhe
    # O **n sai de `referencias.BASE`**, e nao de um literal: pinar "398
    # companhias" faz o teste virar falha sozinho quando a safra e remedida --
    # que e o defeito dos testes que este projeto ja corrigiu duas vezes. O que
    # se trava e a propriedade (o sinal cita a base que usou), nao o tamanho
    # dela naquele dia.
    from valuation import referencias

    n, _ = referencias.BASE["Conversao operacional (CGO / EBITDA)"]
    assert f"{n} companhias" in sinal.detalhe


def _analise_com(periodicidade, colunas):
    import pandas as pd

    from valuation.historico import analisar
    from valuation.importacao import Demonstracoes

    valores = pd.DataFrame(
        {
            c: {
                "receita_liquida": 1000.0,
                "custo_produtos_vendidos": 600.0,
                "ebit": 200.0,
                "depreciacao_amortizacao": 50.0,
                "fluxo_operacional": 200.0,
                "caixa_das_operacoes": 240.0,
                "variacao_capital_giro": -20.0,
                "divida_bruta": 400.0,
                "juros_pagos": 20.0,
                "despesa_financeira": 30.0,
                "ativo_total": 1500.0,
                "patrimonio_liquido": 700.0,
            }
            for c in colunas
        }
    )
    return analisar(
        Demonstracoes(
            empresa="T", valores=valores, unidade="R$", periodicidade=periodicidade
        )
    )


def test_o_veredito_recusa_a_serie_de_trimestres_isolados():
    """Os seis insumos do veredito não atravessam a frequência — os seis.

    Medido em 30 companhias, ano móvel contra trimestres isolados **do mesmo
    período**: o veredito muda em **11 delas (37%)**, e não por pouco — uma vai
    de `ruim` a `bom`.

    Não há subconjunto que se salve, então guardar sinal a sinal produziria um
    veredito montado sobre um insumo só — pior, porque teria a mesma aparência
    de um veredito completo.
    """
    from valuation.qualidade import SEM_DADOS, INSUMOS_DO_VEREDITO, avaliar_qualidade
    from valuation import referencias

    # A premissa da recusa, travada: se algum insumo passar a atravessar a
    # frequência, esta decisão precisa ser reexaminada em vez de sobreviver
    # calada.
    for indicador in INSUMOS_DO_VEREDITO:
        assert not referencias.atravessa_a_frequencia(indicador), indicador

    trimestral = avaliar_qualidade(_analise_com("trimestral", ["1T25", "2T25", "3T25"]))
    assert trimestral.veredito == SEM_DADOS
    assert "trimestres isolados" in trimestral.resumo
    # A causa **não** é falta de DFC: os dados estão lá.
    assert "Faltam dados de fluxo de caixa" not in trimestral.resumo


def test_o_ano_movel_e_a_serie_anual_continuam_recebendo_veredito():
    """O controle: a recusa é da frequência, e não de qualquer série curta.

    O ano móvel tem rótulo de trimestre e conteúdo de doze meses — se a decisão
    fosse pelo rótulo, ele seria recusado junto, e ele é justamente a saída que
    o app oferece.
    """
    from valuation.qualidade import SEM_DADOS, avaliar_qualidade

    movel = avaliar_qualidade(_analise_com("anual", ["1T25", "2T25", "3T25"]))
    anual = avaliar_qualidade(_analise_com("anual", [2023, 2024, 2025]))
    assert movel.veredito != SEM_DADOS
    assert anual.veredito != SEM_DADOS


def test_o_teto_do_juro_pago_e_o_da_despesa_financeira_sao_decisoes_separadas():
    """Um número servia às duas, e elas não se parecem.

    Medido na safra 2021-2025, com o mesmo corte de 25%:

        Custo da dívida pelo caixa    P50  9,3%   acima de 25%:  **2,6%** da base
        Custo da dívida efetivo       P50 18,2%   acima de 25%: **28,2%** da base

    Numa é "implausível"; na outra é o quartil alto. É a mesma forma do defeito
    que este projeto já corrigiu: `ALAVANCAGEM_ALTA` media D/E e dívida/EBITDA
    com o mesmo 3,5, e que os dois calhassem de ser iguais era coincidência.

    Os valores continuam iguais **hoje** — o que muda é que a próxima calibração
    pode mexer num sem mexer no outro, em vez de mover os dois sem perceber.
    Este teste não trava os números: trava que as duas decisões têm nome próprio.
    """
    from valuation import historico, qualidade

    assert hasattr(historico, "KD_MAXIMO_PLAUSIVEL")
    assert hasattr(historico, "DESPESA_FINANCEIRA_SEM_DENOMINADOR")

    # `_juros` julga a **despesa financeira**, e por isso usa a constante dela.
    fonte = pathlib.Path("src/valuation/qualidade.py").read_text(encoding="utf-8")
    assert "DESPESA_FINANCEIRA_SEM_DENOMINADOR" in fonte
    assert "KD_MAXIMO_PLAUSIVEL" not in fonte, (
        "o teto do juro pago não julga despesa financeira"
    )


def test_a_porta_da_despesa_financeira_protege_o_sinal_de_descolamento():
    """Afrouxá-la foi medido e **rejeitado**, e o número é a razão.

    A porta parece mal calibrada — 25% exclui 28,2% da base, acima do P75 da
    própria distribuição. Mas ela não pergunta "esta dívida é cara?", e sim
    "este denominador significa alguma coisa?", e `JURO_DESCOLADO` e
    `JURO_MUITO_DESCOLADO` foram calibrados **com ela no lugar**:

        corte     exclui   o sinal acusaria   grave
        25,0%      25,8%       18,9%           7,7%   <- atual
        57,2%       6,9%       36,4%          23,8%
        100,0%      4,0%       39,3%          26,6%

    Os cortes são o P75 e o P90 do descolamento, então acusar 18,9% e 7,7% é
    perto do que um quartil e um decil devem acusar. Abrir a porta faria o sinal
    disparar em **dois em cada cinco** — o defeito que este projeto já pagou
    quando o descolamento acusava 82,3% da base.
    """
    from valuation.historico import DESPESA_FINANCEIRA_SEM_DENOMINADOR
    from valuation.qualidade import JURO_DESCOLADO, JURO_MUITO_DESCOLADO

    # A propriedade, e nao o valor: a porta tem de ficar **bem acima** do
    # descolamento que ela protege, senao ela deixaria passar justamente as
    # companhias que o sinal existe para acusar.
    assert DESPESA_FINANCEIRA_SEM_DENOMINADOR > JURO_MUITO_DESCOLADO > JURO_DESCOLADO

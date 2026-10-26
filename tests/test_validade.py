"""O registro de validade dos insumos datados.

O que se testa aqui nao e aritmetica de datas: e **quando o app deve calar**.
Listar insumo velho que o modelo nao usa -- a taxa embarcada de quem digitou a
propria, o beta do setor de quem informou o beta -- e ruido sobre campo ja
resolvido, e ruido afasta o leitor do aviso que importa.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date

import pytest

from valuation import validade
from valuation.custo_capital import NTNB_MEDIDA_EM
from valuation.validade import Insumo, insumos, resumo, vencidos

# Bem depois da validade da taxa embarcada (90 dias) e da dos betas (365).
MUITO_DEPOIS = date(NTNB_MEDIDA_EM.year + 2, 1, 15)
LOGO_DEPOIS = date(NTNB_MEDIDA_EM.year, NTNB_MEDIDA_EM.month, NTNB_MEDIDA_EM.day)


def test_insumo_sem_data_nunca_vence():
    """Ausencia de data e ausencia de afirmacao: nao da para dizer que venceu."""
    sem_data = Insumo(
        chave="x", nome="Sem data", medido_em=None, move=validade.MOVE_O_WACC,
        como_atualizar="-", valido_por_dias=30,
    )
    assert sem_data.idade_em_dias(MUITO_DEPOIS) is None
    assert not sem_data.vencido(MUITO_DEPOIS)


def test_insumo_sem_prazo_so_vence_quando_a_fonte_declara():
    """A base de percentis nao vence em N dias: vence quando sai exercicio novo."""
    declarado = Insumo(
        chave="x", nome="Base", medido_em=date(2020, 1, 1),
        move=validade.MOVE_A_REFERENCIA, como_atualizar="-", vencido_declarado=False,
    )
    assert not declarado.vencido(MUITO_DEPOIS), "sem prazo, a idade nao decide"
    assert replace(declarado, vencido_declarado=True).vencido(date(2020, 1, 2))


def test_a_taxa_embarcada_vence_e_a_informada_nao(empresa_exemplo):
    """Quem digitou o proprio rf nao tem insumo velho: o campo ja foi resolvido."""
    from valuation.modelo import substituir_varios

    usando_a_referencia = substituir_varios(
        empresa_exemplo, {"custo_capital.metodo": "local", "custo_capital.rf_brl": None}
    )
    chaves = {i.chave for i in insumos(empresa=usando_a_referencia)}
    assert "rf_brl" in chaves

    velhos = vencidos(empresa=usando_a_referencia, hoje=MUITO_DEPOIS)
    assert "rf_brl" in {i.chave for i in velhos}
    # No dia da medicao ela nao esta velha.
    assert "rf_brl" not in {
        i.chave for i in vencidos(empresa=usando_a_referencia, hoje=LOGO_DEPOIS)
    }

    informou = substituir_varios(usando_a_referencia, {"custo_capital.rf_brl": 0.0782})
    # Sem data gravada -- projeto antigo, ou numero digitado a mao --, nao da
    # para dizer a idade, e o modulo nao inventa uma.
    assert "rf_brl" not in {i.chave for i in insumos(empresa=informou)}


def test_a_taxa_informada_tambem_envelhece(empresa_exemplo):
    """"Quem informou ja resolveu o campo" -- resolveu **naquele dia**.

    O desenho inicial calava com `rf_brl` preenchido, e com isso parava de
    avisar justamente no caso em que o numero veio do mercado: a curva de agosto
    continuava decidindo o WACC em marco, calada.
    """
    from valuation.modelo import substituir_varios

    informou = substituir_varios(
        empresa_exemplo, {"custo_capital.metodo": "local", "custo_capital.rf_brl": 0.0782}
    )
    com_data = insumos(empresa=informou, rf_em=date(2026, 1, 15))
    insumo = next(i for i in com_data if i.chave == "rf_brl")
    assert "informada" in insumo.nome
    assert insumo.medido_em == date(2026, 1, 15)
    assert insumo.vencido(date(2026, 8, 1))
    assert not insumo.vencido(date(2026, 2, 1))


def test_o_caminho_em_dolar_nao_lista_a_ntnb(empresa_exemplo):
    """A taxa real brasileira nao entra na conta: listar sua idade seria falso."""
    from valuation.modelo import substituir_varios

    em_dolar = substituir_varios(empresa_exemplo, {"custo_capital.metodo": "usd"})
    assert "rf_brl" not in {i.chave for i in insumos(empresa=em_dolar)}


def test_o_beta_so_envelhece_quando_veio_da_tabela(empresa_exemplo):
    """A planilha do Damodaran sai uma vez por ano, em janeiro.

    **A premissa sozinha nao distingue** o beta trazido da tabela do digitado a
    mao: os dois ocupam o mesmo campo. Quem sabe e a tela, que guarda o setor --
    e sem setor declarado o app nao afirma a origem nem a validade.
    """
    from valuation.modelo import substituir_varios

    do_setor = substituir_varios(
        empresa_exemplo,
        {"custo_capital.beta_desalavancado": 0.86, "custo_capital.beta_alavancado_setor": None},
    )
    com_setor = insumos(empresa=do_setor, setor="Bens de capital")
    assert "betas_setoriais" in {i.chave for i in com_setor}
    assert "Bens de capital" in next(
        i.detalhe for i in com_setor if i.chave == "betas_setoriais"
    )
    assert "betas_setoriais" in {
        i.chave for i in vencidos(empresa=do_setor, hoje=MUITO_DEPOIS, setor="Bens de capital")
    }

    # Mesmo beta, sem setor declarado: pode ter sido digitado, e o app cala.
    assert "betas_setoriais" not in {i.chave for i in insumos(empresa=do_setor)}


def test_as_demonstracoes_vencem_por_exercicio_novo_e_nao_por_idade():
    """Uma DFP de 2025 nao fica velha em marco de 2026; fica quando sai a de 2026."""
    import pandas as pd

    from valuation.importacao import Demonstracoes

    dfs = Demonstracoes(
        empresa="Teste",
        valores=pd.DataFrame({2024: {"receita_liquida": 1000.0}, 2025: {"receita_liquida": 1100.0}}),
    )
    # Sem cache para comparar, o app nao afirma que envelheceu.
    insumo = next(i for i in insumos(demonstracoes=dfs, cache="/nao/existe") if i.chave == "demonstracoes")
    assert not insumo.vencido(MUITO_DEPOIS)
    assert "2025" in insumo.detalhe


def test_o_preco_vence_em_um_mes():
    """O que envelhece nao e o numero: e a conclusao que o material carrega."""
    preco = next(i for i in insumos(preco_em=date(2026, 9, 1)) if i.chave == "preco")
    assert not preco.vencido(date(2026, 9, 20))
    assert preco.vencido(date(2026, 10, 20))
    # Sem preco informado, nao ha linha nenhuma.
    assert not [i for i in insumos() if i.chave == "preco"]


def test_a_lista_vem_do_que_mais_move_o_valor(empresa_exemplo):
    """WACC antes de fluxo, fluxo antes de preço, preço antes de referência."""
    from valuation.modelo import substituir_varios

    empresa = substituir_varios(
        empresa_exemplo,
        {
            "custo_capital.metodo": "local",
            "custo_capital.rf_brl": None,
            "custo_capital.beta_desalavancado": 0.86,
        },
    )
    ordem = [i.move for i in insumos(empresa=empresa, preco_em=date(2026, 9, 1))]
    assert ordem == sorted(ordem, key=lambda m: validade._PESO_DO_QUE_MOVE[m])


def test_o_resumo_diz_quantos_e_quais(empresa_exemplo):
    from valuation.modelo import substituir_varios

    empresa = substituir_varios(
        empresa_exemplo, {"custo_capital.metodo": "local", "custo_capital.rf_brl": None}
    )
    texto = resumo(empresa=empresa, hoje=MUITO_DEPOIS)
    assert "pedem atualização" in texto
    assert "taxa livre de risco" in texto

    limpo = resumo(empresa=empresa, hoje=LOGO_DEPOIS)
    assert "dentro da validade" in limpo


def test_modelo_sem_nada_datado_nao_inventa_lista():
    """Sem empresa, sem historico, sem preco e sem cache, nao ha o que envelhecer.

    O `cache` aponta para um caminho que nao existe de proposito: a base de
    percentis so vira linha quando ha DFP local com que comparar, e um teste que
    dependesse do cache da maquina passaria aqui e falharia na CI.
    """
    assert insumos(cache="/nao/existe") == []
    assert resumo(cache="/nao/existe") == ""


def test_serie_trimestral_le_o_ano_do_rotulo():
    """Coluna de ano movel e `3T25`, e nao inteiro.

    Exigir numero fazia a lista estourar com `max() arg is an empty sequence` --
    pego pelo teste de omissao do diagnostico, que roda sobre serie trimestral.
    """
    import pandas as pd

    from valuation.importacao import Demonstracoes

    dfs = Demonstracoes(
        empresa="Teste",
        valores=pd.DataFrame({"2T25": {"receita_liquida": 500.0}, "3T25": {"receita_liquida": 520.0}}),
        periodicidade="anual",
    )
    insumo = next(
        i
        for i in insumos(demonstracoes=dfs, cache="/nao/existe", hoje=date(2025, 11, 20))
        if i.chave == "demonstracoes"
    )
    assert "3T25" in insumo.detalhe
    assert insumo.medido_em == date(2025, 9, 30)


def test_coluna_que_ninguem_entende_nao_vira_palpite():
    """Rotulo ilegivel e ausencia de resposta, e nao um ano inventado."""
    import pandas as pd

    from valuation.importacao import Demonstracoes

    dfs = Demonstracoes(
        empresa="Teste",
        valores=pd.DataFrame({"base": {"receita_liquida": 1.0}, "cenário": {"receita_liquida": 2.0}}),
    )
    assert not [
        i for i in insumos(demonstracoes=dfs, cache="/nao/existe") if i.chave == "demonstracoes"
    ]


# ---------------------------------------------------------------------------
# O diagnostico pergunta o que envelheceu
# ---------------------------------------------------------------------------


def test_o_diagnostico_acusa_insumo_vencido(empresa_exemplo, monkeypatch):
    """Coerente e atual sao coisas diferentes, e so a primeira tinha quem perguntasse.

    A data da referencia e envelhecida no teste em vez de se contar com o
    calendario: hoje ela tem 64 dias e **nao** venceu, e um teste que dependesse
    disso passaria agora e falharia sozinho em dezembro.
    """
    from valuation import avaliar, custo_capital
    from valuation.diagnostico import ALERTA, diagnosticar
    from valuation.modelo import substituir_varios

    monkeypatch.setattr(custo_capital, "NTNB_MEDIDA_EM", date(2020, 1, 1))
    empresa = substituir_varios(
        empresa_exemplo, {"custo_capital.metodo": "local", "custo_capital.rf_brl": None}
    )
    achados = diagnosticar(avaliar(empresa), cache="/nao/existe").achados
    achado = next((a for a in achados if a.codigo == "insumo_vencido_rf_brl"), None)

    assert achado is not None, [a.codigo for a in achados]
    assert achado.severidade == ALERTA, "o que mexe no WACC nao e informacao"
    assert "WACC" in achado.detalhe
    assert "Custo de capital" in achado.acao


def test_o_preco_velho_e_informacao_e_nao_alerta(empresa_exemplo):
    """O preco nao muda o valor da empresa: muda a conclusao sobre o preco."""
    from valuation import avaliar
    from valuation.diagnostico import INFORMACAO, diagnosticar

    achados = diagnosticar(
        avaliar(empresa_exemplo), preco_em=date(2020, 1, 1), cache="/nao/existe"
    ).achados
    achado = next(a for a in achados if a.codigo == "insumo_vencido_preco")
    assert achado.severidade == INFORMACAO


def test_sem_insumo_vencido_o_diagnostico_cala(empresa_exemplo):
    """Aviso que aparece sempre deixa de ser aviso."""
    from valuation import avaliar
    from valuation.diagnostico import diagnosticar
    from valuation.modelo import substituir_varios

    # rf informado e nenhum setor declarado: nada datado de que o app saiba.
    empresa = substituir_varios(
        empresa_exemplo, {"custo_capital.metodo": "local", "custo_capital.rf_brl": 0.0782}
    )
    achados = diagnosticar(avaliar(empresa), cache="/nao/existe").achados
    assert not [a for a in achados if a.codigo.startswith("insumo_vencido")]


# ---------------------------------------------------------------------------
# A serie trimestral envelhece por trimestre
# ---------------------------------------------------------------------------


def test_o_prazo_do_itr_e_45_dias_apos_o_trimestre():
    """O 4T nao tem ITR: ele vira a DFP, com prazo proprio."""
    from valuation.validade import trimestre_com_prazo_vencido

    # 20/11/2025: o 3T (fim 30/09) venceu em 14/11.
    assert trimestre_com_prazo_vencido(date(2025, 11, 20)) == (2025, 3)
    # 01/11/2025: ainda nao.
    assert trimestre_com_prazo_vencido(date(2025, 11, 1)) == (2025, 2)
    # Em janeiro, o mais recente vencido e o 3T do ano anterior -- e nao um 4T.
    assert trimestre_com_prazo_vencido(date(2026, 1, 10)) == (2025, 3)


def test_quem_importou_no_primeiro_trimestre_e_volta_em_outubro_e_avisado():
    """A comparacao por exercicio nao enxerga isto: os dois sao "2026".

    Era o caso que faltava -- resultado trimestral novo nao era detectado.
    """
    import pandas as pd

    from valuation.importacao import Demonstracoes

    dfs = Demonstracoes(
        empresa="Teste",
        valores=pd.DataFrame({"4T25": {"receita_liquida": 1.0}, "1T26": {"receita_liquida": 1.1}}),
    )
    insumo = next(
        i
        for i in insumos(demonstracoes=dfs, cache="/nao/existe", hoje=date(2026, 10, 26))
        if i.chave == "demonstracoes"
    )
    assert insumo.vencido(date(2026, 10, 26))
    assert "2T26" in insumo.detalhe
    assert "14/08/2026" in insumo.detalhe
    # O texto diz **prazo**, e nao que o arquivo existe: a companhia pode atrasar.
    assert "confira" in insumo.detalhe


def test_serie_trimestral_em_dia_nao_vira_aviso():
    import pandas as pd

    from valuation.importacao import Demonstracoes

    dfs = Demonstracoes(
        empresa="Teste",
        valores=pd.DataFrame({"1T26": {"receita_liquida": 1.0}, "2T26": {"receita_liquida": 1.1}}),
    )
    insumo = next(
        i
        for i in insumos(demonstracoes=dfs, cache="/nao/existe", hoje=date(2026, 10, 26))
        if i.chave == "demonstracoes"
    )
    assert not insumo.vencido(date(2026, 10, 26))


# ---------------------------------------------------------------------------
# Os entregaveis dizem de quando e cada numero
# ---------------------------------------------------------------------------


def _insumo_vencido():
    return Insumo(
        chave="rf_brl",
        nome="Taxa livre de risco (NTN-B de referência)",
        medido_em=date(2020, 1, 1),
        move=validade.MOVE_O_WACC,
        valido_por_dias=90,
        como_atualizar="Busque a curva do Tesouro em Custo de capital.",
        detalhe="O modelo usa a taxa embarcada.",
    )


def test_o_material_do_comite_diz_de_quando_e_cada_numero(empresa_exemplo):
    """Quem abre o PDF em dezembro nao sabe que a curva dentro dele e de agosto."""
    from valuation import avaliar
    from valuation.apresentacao import montar_html

    pagina = montar_html(avaliar(empresa_exemplo), insumos=[_insumo_vencido()])

    assert "Fontes e datas" in pagina
    assert "01/01/2020" in pagina
    assert "pede atualização" in pagina
    assert "Busque a curva do Tesouro" in pagina


def test_o_relatorio_traz_a_secao_para_o_diff(empresa_exemplo):
    """O relatorio existe para ser rodado de novo e diffado tres meses depois."""
    from valuation import avaliar
    from valuation.relatorio import montar

    texto = montar(avaliar(empresa_exemplo), insumos=[_insumo_vencido()])

    assert "## De quando é cada número" in texto
    assert "01/01/2020" in texto
    assert "pede atualização" in texto


def test_sem_insumos_os_entregaveis_nao_ganham_secao_vazia(empresa_exemplo):
    """Secao que promete conteudo e nao entrega e pior que ausencia."""
    from valuation import avaliar
    from valuation.apresentacao import montar_html
    from valuation.relatorio import montar

    resultado = avaliar(empresa_exemplo)
    assert "Fontes e datas" not in montar_html(resultado)
    assert "De quando é cada número" not in montar(resultado)


def test_o_diagnostico_aceita_tudo_que_o_app_manda():
    """A tela passa cinco argumentos de contexto; o motor tem de aceitar os cinco.

    Faltou `rf_em` na assinatura e **24 testes de tela quebraram de uma vez**,
    todos com o mesmo `TypeError` -- porque o motor tem teste proprio e a tela
    tem o dela, e ninguem conferia o contrato entre os dois. Este teste e o
    contrato: se a chamada do app ganhar um argumento novo, ele falha aqui.
    """
    import inspect

    from valuation.diagnostico import diagnosticar

    parametros = set(inspect.signature(diagnosticar).parameters)
    # O que `app/estado.py: diagnostico()` passa hoje.
    do_app = {"analise", "retorno", "preco_em", "setor", "rf_em"}
    assert do_app <= parametros, sorted(do_app - parametros)


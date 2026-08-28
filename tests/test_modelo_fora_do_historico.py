"""O nome já é o da companhia; os números ainda podem não ser.

Importar as demonstrações adota o nome e o histórico, mas **derivar as premissas
é um clique separado** — e continua sendo, porque aplicar sozinho sobrescreveria
o que o analista já tivesse montado.

O que não pode é o intervalo entre as duas coisas ficar calado. Com a WEG
importada e as premissas ainda as de partida, a barra lateral e o Início
anunciavam *"WEG SA — Equity Value 698,8"* e *"R$ 6,99 por ação"*: os números da
empresa-exemplo (receita de 1.000, cem milhões de ações) com o nome da WEG em
cima. É o mesmo defeito que o nome padrão já tinha causado, pelo lado oposto —
e este é pior, porque o número é plausível.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from valuation.diagnostico import (
    FATOR_DE_OUTRA_COMPANHIA,
    premissas_descrevem_o_historico,
)
from valuation.historico import analisar, sugerir_premissas
from valuation.importacao.cvm import importar_cvm

RAIZ = Path(__file__).resolve().parent.parent
DADOS = RAIZ / "tests" / "dados" / "cvm"
WEG = 5410


@pytest.fixture(scope="module")
def weg():
    return importar_cvm(WEG, [2023, 2024], cache=DADOS).escalar(1e6, "R$ milhões")


@pytest.fixture()
def de_partida():
    """A mesma empresa com que o app abre, montada pelo próprio app."""
    import sys

    if str(RAIZ) not in sys.path:
        sys.path.insert(0, str(RAIZ))
    from app.estado import _empresa_inicial

    return _empresa_inicial()


def test_o_exemplo_com_a_companhia_importada_e_acusado(weg, de_partida):
    """Receita de 1.000 contra 40.804, e 100 milhões de ações contra 4.195,7."""
    motivo = premissas_descrevem_o_historico(de_partida, weg)
    assert motivo is not None
    assert "receita-base" in motivo
    assert "ações" in motivo
    # Os dois lados de cada comparação têm de estar na frase: "as premissas são
    # outras" sem os números não deixa ninguém conferir se o aviso está certo.
    # Vêm da própria base, e não pinados — o fixture pode ganhar outro exercício.
    from valuation.diagnostico import _num

    assert _num(de_partida.operacionais.receita_base) in motivo
    assert _num(float(weg.valor("receita_liquida"))) in motivo
    assert _num(de_partida.ponte.acoes_em_circulacao) in motivo
    assert _num(float(weg.valor("acoes_em_circulacao"))) in motivo


def test_o_motivo_vai_para_a_tela_e_por_isso_vem_acentuado(weg, de_partida):
    """Texto de usuário é acentuado — o resto do módulo é ASCII por ser código.

    O aviso saiu ao navegador escrito "a receita-base do modelo e 1.000,0 e a do
    ultimo exercicio importado", que é a convenção do código vazando para a
    tela. Não é detalhe: é a mesma frase lida por quem trabalha em português.
    """
    motivo = premissas_descrevem_o_historico(de_partida, weg)
    assert "é" in motivo
    assert "último exercício" in motivo
    for sem_acento in ("ultimo", "exercicio", "acoes"):
        assert sem_acento not in motivo, motivo


def test_premissas_derivadas_do_historico_nao_sao_acusadas(weg, de_partida):
    """Depois do clique, o modelo descreve a companhia — e o aviso some.

    Este é o lado que importa: um aviso que não desliga vira ruído, e ruído
    ensina o usuário a ignorá-lo.
    """
    sugestao = sugerir_premissas(analisar(weg), horizonte=5)
    derivada = replace(
        de_partida,
        operacionais=sugestao.operacionais,
        ponte=sugestao.ponte,
        custo_capital=sugestao.custo_capital,
    )
    assert premissas_descrevem_o_historico(derivada, weg) is None


def test_sem_historico_nao_ha_o_que_acusar(de_partida):
    """Quem ainda não importou nada está usando o exemplo de propósito."""
    assert premissas_descrevem_o_historico(de_partida, None) is None


def test_normalizar_a_receita_nao_dispara_o_aviso(weg, de_partida):
    """O corte pega troca de companhia, e não escolha de ano-base.

    Quem projeta a partir de uma receita normalizada — cíclica, ano atípico —
    continua descrevendo a mesma empresa. Um aviso que dispara aí obrigaria o
    analista a conviver com ele ligado, que é o mesmo que desligá-lo.
    """
    sugestao = sugerir_premissas(analisar(weg), horizonte=5)
    dentro = FATOR_DE_OUTRA_COMPANHIA * 0.9
    normalizada = replace(
        de_partida,
        operacionais=replace(
            sugestao.operacionais,
            receita_base=sugestao.operacionais.receita_base / dentro,
        ),
        ponte=sugestao.ponte,
        custo_capital=sugestao.custo_capital,
    )
    assert premissas_descrevem_o_historico(normalizada, weg) is None


def test_o_aviso_sobrevive_ao_projeto_salvo(weg, de_partida, tmp_path):
    """Retomar um valuation não pode ligar nem desligar o aviso sozinho.

    O risco tem dois lados. Se as demonstrações não viajassem no projeto, o
    aviso sumiria por **falta de histórico** e não por coerência — apagando
    justamente o caso em que ele importa. E se a escala se perdesse no
    round-trip, ele passaria a disparar num modelo que descreve a companhia,
    que é o falso positivo que o torna ruído.
    """
    from dataclasses import replace

    from valuation.projeto import Projeto, carregar, salvar

    sugestao = sugerir_premissas(analisar(weg), horizonte=5)
    derivada = replace(
        de_partida,
        nome="WEG SA",
        operacionais=sugestao.operacionais,
        ponte=sugestao.ponte,
        custo_capital=sugestao.custo_capital,
    )

    for empresa, deve_acusar in ((derivada, False), (replace(de_partida, nome="WEG SA"), True)):
        caminho = salvar(
            Projeto(empresa=empresa, demonstracoes=weg),
            tmp_path / f"{'derivada' if not deve_acusar else 'exemplo'}.json",
        )
        de_volta = carregar(caminho)
        assert de_volta.demonstracoes is not None, "o histórico não viajou no projeto"
        motivo = premissas_descrevem_o_historico(
            de_volta.empresa, de_volta.demonstracoes
        )
        assert (motivo is not None) == deve_acusar, motivo
        # A escala tem de atravessar intacta: e dela que o corte depende.
        assert (
            de_volta.empresa.operacionais.receita_base
            == empresa.operacionais.receita_base
        )


def test_as_respostas_qualitativas_sobrevivem_ao_projeto_salvo(weg, de_partida, tmp_path):
    """É a única parte do valuation que o app não sabe recalcular.

    Premissa perdida se redigita em segundos; o parágrafo sobre de onde vem a
    vantagem competitiva foi pensado uma vez. Sem persistir, a seção qualitativa
    seria leitura e não trabalho.
    """
    from valuation.projeto import Projeto, carregar, salvar

    respostas = {
        "VRIO — Raridade": "ROIC no percentil 93 vem da marca e da rede.",
        "Fosso (vantagem competitiva)": "Assistência técnica capilarizada.",
    }
    caminho = salvar(
        Projeto(
            empresa=de_partida,
            demonstracoes=weg,
            config={"respostas_qualitativas": respostas},
        ),
        tmp_path / "p.json",
    )
    de_volta = carregar(caminho)
    assert de_volta.config.get("respostas_qualitativas") == respostas


def test_o_diagnostico_precifica_o_fosso_perpetuo():
    """ROIC perpétuo acima do WACC diz que a vantagem nunca erode.

    A tela de Qualitativo pergunta "por quanto tempo o retorno excedente
    resiste?" e o modelo já respondeu: para sempre. O achado converte a hipótese
    em preço — recalcula o terminal com `ROIC = WACC`, o mundo em que a vantagem
    se dissipa, e mostra quanto do equity depende da diferença.
    """
    import sys
    from pathlib import Path

    raiz = Path(__file__).resolve().parent.parent
    if str(raiz) not in sys.path:
        sys.path.insert(0, str(raiz))
    from app.estado import _empresa_inicial

    from valuation.diagnostico import _checar_fosso_perpetuo
    from valuation.modelo import avaliar, substituir_varios

    base = _empresa_inicial()

    # Folga pequena nao acusa: o corte existe para o achado nao virar ruido.
    perto = substituir_varios(base, {"perpetuidade.roic_perpetuidade": 0.14})
    assert _checar_fosso_perpetuo(avaliar(perto), None) == []

    # Folga grande acusa, e o detalhe traz o preco da hipotese.
    longe = avaliar(substituir_varios(base, {"perpetuidade.roic_perpetuidade": 0.30}))
    achados = _checar_fosso_perpetuo(longe, None)
    assert len(achados) == 1
    achado = achados[0]
    assert achado.codigo == "fosso_perpetuo"
    assert "do equity value" in achado.detalhe
    # E manda para a tela onde a pergunta se responde.
    assert "Qualitativo" in achado.acao

"""A base medida, e o que ela serve para dizer.

O modulo existe por causa de uma pergunta do dono do projeto: os cortes de
leitura sao absolutos ou contra pares? A resposta e os dois, e estes testes
guardam a parte que da para verificar -- que o percentil sai certo nas pontas,
no meio e fora da tabela, e que ele nunca extrapola.
"""

from __future__ import annotations

import numpy as np
import pytest

from valuation import referencias


def test_a_mediana_da_base_cai_no_percentil_50():
    _, valores = referencias.BASE["Conversao de caixa (FCO / EBITDA)"]
    mediana = valores[referencias.QUANTIS.index(0.50)]
    assert referencias.posicao("Conversao de caixa (FCO / EBITDA)", mediana) == pytest.approx(0.50)


def test_o_percentil_cresce_com_o_valor():
    indicador = "Margem EBITDA"
    anterior = -1.0
    for valor in (-0.5, 0.0, 0.10, 0.20, 0.50, 2.0):
        p = referencias.posicao(indicador, valor)
        assert p >= anterior
        anterior = p


def test_fora_da_tabela_nao_extrapola():
    """Cauda de distribuicao com margem de 300% nao se aproxima por reta."""
    assert referencias.posicao("Margem EBITDA", -50.0) == pytest.approx(0.05)
    assert referencias.posicao("Margem EBITDA", 50.0) == pytest.approx(0.95)


def test_indicador_desconhecido_e_valor_invalido_devolvem_ausencia():
    assert np.isnan(referencias.posicao("Indicador Inventado", 0.5))
    assert np.isnan(referencias.posicao("Margem EBITDA", float("nan")))
    assert referencias.descrever("Indicador Inventado", 0.5) == ""


def test_a_descricao_nomeia_as_pontas_em_vez_de_dar_percentil():
    assert "5% menores" in referencias.descrever("Margem EBITDA", -10.0)
    assert "5% maiores" in referencias.descrever("Margem EBITDA", 10.0)
    assert "percentil" in referencias.descrever("Margem EBITDA", 0.143)


def test_a_tabela_traz_o_n_de_cada_indicador():
    tabela = referencias.tabela()
    assert "n" in tabela.columns
    assert (tabela["n"] > 300).all(), "amostra pequena demais para servir de referencia"
    assert set(tabela.index) == set(referencias.BASE)


def test_gerar_referencias_reproduz_o_formato_do_modulo():
    """Refazer a medicao tem que ser um comando, nao trabalho manual."""
    import pandas as pd

    perfis = pd.DataFrame({"Margem EBITDA": np.linspace(0.0, 1.0, 101)})
    codigo = referencias.gerar_referencias(perfis)

    assert codigo.startswith("BASE: dict[str, tuple[int, tuple[float, ...]]] = {")
    assert '"Margem EBITDA": (101, (' in codigo
    # O bloco gerado tem que ser Python valido.
    ambiente: dict = {}
    exec(codigo.replace("BASE: dict[str, tuple[int, tuple[float, ...]]]", "BASE"), ambiente)
    assert ambiente["BASE"]["Margem EBITDA"][0] == 101


def test_a_qualidade_cita_a_posicao_na_base():
    """O sinal de conversao passa a dizer onde o numero cai no mercado."""
    from pathlib import Path

    from valuation.historico import analisar
    from valuation.importacao.cvm import importar_cvm
    from valuation.qualidade import avaliar_qualidade

    dados = Path(__file__).parent / "dados" / "cvm"
    analise = analisar(importar_cvm(5410, [2023, 2024], cache=dados))
    conversao = next(s for s in avaliar_qualidade(analise).sinais if s.codigo == "conversao")

    assert "percentil" in conversao.detalhe or "5%" in conversao.detalhe
    assert "companhias brasileiras" in conversao.detalhe


# ---------------------------------------------------------------------------
# A safra da medicao
# ---------------------------------------------------------------------------


def test_a_safra_acusa_quando_a_base_publicada_avancou():
    """``BASE`` é um instantâneo colado: não se atualiza quando sai DFP nova.

    Sem o aviso, o app cita percentis de uma safra antiga **com a mesma aparência
    de atual** — o pior tipo de número desatualizado é o que não se anuncia.
    """
    from valuation.referencias import SafraDaMedicao

    atrasada = SafraDaMedicao(ano_medido=2024, ano_mais_novo=2025, companhias=447)
    assert atrasada.desatualizada
    assert atrasada.exercicios_atras == 1
    assert "1 exercício atrás" in atrasada.resumo

    dois = SafraDaMedicao(ano_medido=2023, ano_mais_novo=2025, companhias=447)
    assert "2 exercícios atrás" in dois.resumo


def test_safra_em_dia_nao_vira_alarme():
    """Alarme que dispara sem motivo treina o leitor a ignorar."""
    from valuation.referencias import SafraDaMedicao

    em_dia = SafraDaMedicao(ano_medido=2025, ano_mais_novo=2025, companhias=447)
    assert not em_dia.desatualizada
    assert em_dia.exercicios_atras == 0
    assert "mais nova publicada" in em_dia.resumo


def test_sem_dfp_no_cache_nao_ha_o_que_afirmar(tmp_path):
    """Sem base local não dá para dizer que a medição envelheceu.

    Afirmar assim mesmo seria inventar — e quem nunca baixou nada também não tem
    com o que comparar.
    """
    from valuation.referencias import safra

    assert safra(cache=tmp_path) is None


def _cache_de_dfp(tmp_path, tamanhos: dict[int, int]):
    """Um cache com um zip por exercício, do tamanho pedido."""
    import zipfile

    for ano, tamanho in tamanhos.items():
        caminho = tmp_path / f"dfp_cia_aberta_{ano}.zip"
        with zipfile.ZipFile(caminho, "w") as zf:
            # `writestr` comprime; o que a guarda le e `file_size`, que e o
            # tamanho **descomprimido** -- entao o conteudo pode ser repetitivo.
            zf.writestr(f"dfp_cia_aberta_DRE_con_{ano}.csv", "x" * tamanho)
    return tmp_path


def test_zip_vazio_nao_conta_como_exercicio_publicado(tmp_path):
    """Em janeiro o arquivo do exercício já existe e não tem companhia nenhuma.

    Contá-lo faria a tela anunciar atraso por um exercício que ainda não saiu —
    é a mesma armadilha de ``_itr_vazio``, e o custo de errar é o mesmo.
    """
    from valuation.pares import _anos_de_dfp_no_cache

    cache = _cache_de_dfp(tmp_path, {2024: 6_000_000, 2025: 20})
    assert _anos_de_dfp_no_cache(cache) == [2024]


def test_exercicio_pela_metade_tambem_nao_conta(tmp_path):
    """**O caso que a guarda anterior não alcançava**, e ele estava disparando.

    Em setembro de 2026 o arquivo do exercício de 2026 não está vazio: ele tem
    as companhias de **exercício deslocado**, as que fecham em março ou junho.
    Medido no cache: **7 companhias e 95 KB**, contra 340 a 476 companhias e
    5,1 a 7,1 MB nos dezesseis exercícios publicados.

    O corte era de 2.000 bytes — calibrado para o arquivo vazio de janeiro —, e
    95 KB passava. A tela anunciava "**os percentis estão 1 exercício atrás**" e
    continuaria anunciando até 2027, por um exercício com 1,6% da base.

    Alarme que dispara sem motivo treina o leitor a ignorar, inclusive quando
    ele estiver certo. É o defeito que este projeto já pagou duas vezes, nos dois
    sentidos.
    """
    from valuation.pares import _anos_de_dfp_no_cache

    # As duas populacoes medidas, e a distancia entre elas: mais de uma ordem de
    # grandeza. O corte de 1 MB fica na terra de ninguem.
    cache = _cache_de_dfp(tmp_path, {2024: 6_800_000, 2025: 6_400_000, 2026: 95_000})
    assert _anos_de_dfp_no_cache(cache) == [2024, 2025]


def test_a_safra_nao_se_declara_atrasada_por_exercicio_parcial(tmp_path):
    """A consequência do corte, na frase que o usuário lê."""
    from valuation.referencias import ANO_MAIS_RECENTE_MEDIDO, safra

    cache = _cache_de_dfp(
        tmp_path,
        {ANO_MAIS_RECENTE_MEDIDO: 6_400_000, ANO_MAIS_RECENTE_MEDIDO + 1: 95_000},
    )
    medida = safra(cache=cache)
    assert medida is not None
    assert not medida.desatualizada
    assert "atrás" not in medida.resumo

    # **E ela volta a acusar quando o exercicio sai de verdade.** Sem este lado
    # o teste passaria com uma guarda que nunca deixa nada contar -- que e o
    # mesmo defeito pelo lado oposto.
    outro = tmp_path / "exercicio_publicado"
    outro.mkdir()
    _cache_de_dfp(
        outro,
        {ANO_MAIS_RECENTE_MEDIDO: 6_400_000, ANO_MAIS_RECENTE_MEDIDO + 1: 6_100_000},
    )
    assert safra(cache=outro).desatualizada


def test_todo_indicador_publicado_declara_a_unidade():
    """`BASE` mistura três unidades, e uma tabela que as junta não se lê.

    "Margem EBITDA 0,208" ao lado de "Ciclo 42,505" e de "Dívida líquida /
    EBITDA 2,024" pede que o leitor saiba de cabeça qual coluna é fração, qual é
    dia e qual é múltiplo — e quem sabe disso não precisa da tabela.

    A unidade é **declarada e não inferida do nome**. Inferir funcionaria hoje e
    quebraria calado no dia em que um indicador novo não seguisse a convenção;
    aqui ele entra sem unidade e este teste reprova.
    """
    from valuation import referencias

    faltando = sorted(i for i in referencias.BASE if i not in referencias.UNIDADES)
    assert not faltando, f"indicadores sem unidade declarada: {faltando}"

    orfas = sorted(i for i in referencias.UNIDADES if i not in referencias.BASE)
    assert not orfas, f"unidade declarada para indicador que BASE não publica: {orfas}"


def test_cada_unidade_se_escreve_do_seu_jeito():
    """Fração vira percentual, dia vira dia, razão vira múltiplo."""
    from valuation import referencias

    assert referencias.formatar("Margem EBITDA", 0.208) == "20,8%"
    assert referencias.formatar("Ciclo de conversao de caixa (dias)", 42.6) == "43 d"
    assert referencias.formatar("Divida liquida / EBITDA", 2.024) == "2,02x"
    # Indicador desconhecido nao inventa unidade: cai no multiplo, que e o
    # formato mais neutro dos tres.
    assert referencias.formatar("Coisa nova", 1.5) == "1,50x"


def test_as_duas_safras_se_chamam_do_mesmo_jeito():
    """`SafraDaMedicao.resumo` era método e `SafraDoUniverso.resumo`, propriedade.

    As duas dizem a mesma coisa sobre a mesma safra, e chamá-las de formas
    diferentes rendeu exatamente o defeito que rendeu: `safra.resumo` sem
    parênteses imprimiu `<bound method ...>` na tela, e não um aviso.
    """
    from valuation.pares import SafraDoUniverso
    from valuation.referencias import SafraDaMedicao

    for classe in (SafraDaMedicao, SafraDoUniverso):
        assert isinstance(
            classe.__dict__.get("resumo"), property
        ), f"{classe.__name__}.resumo precisa ser propriedade, como a irmã"


def test_nem_todo_indicador_atravessa_a_frequencia():
    """A base é medida em exercícios, e comparar um trimestre contra ela
    depende do indicador.

    Um indicador atravessa quando é **fluxo sobre fluxo do mesmo período**
    (margem, conversão) ou **estoque sobre estoque** (liquidez, dívida/PL). Não
    atravessa quando mistura fluxo do período com estoque — o denominador anual
    encolhe a um quarto e a razão quadruplica —, quando é variação de um período
    contra outro, ou quando o numerador é irregular dentro do ano.

    A separação foi medida três vezes, e **só a terceira mede o que diz medir**:

    | Medição | Grupos (desvio mediano do percentil) |
    |---|---|
    | 3 companhias, anual × trimestral | vale limpo — artefato do tamanho |
    | 79 companhias, anual × trimestral | 20p × 5p, com sobreposição em 15-18 |
    | **80 companhias, ano móvel × trimestre isolado do mesmo período** | **18,5p × 1,9p** |

    A terceira elimina o confundidor: as duas leituras cobrem **os mesmos
    meses**, então o que sobra é frequência e não mudança da companhia. A
    sobreposição de 15-18 pontos era em boa parte esse confundidor, e as três
    razões estoque-sobre-estoque medem **0,0 pontos** — não "quase zero": zero,
    que é a previsão estrutural exata.

    A classificação é **por estrutura e não pelo desvio**: o desvio confirma, e
    usá-lo como critério faria a lista mudar com a amostra.
    """
    from valuation import referencias

    for estrutural in ("ROIC", "ROE", "Crescimento da receita", "Divida liquida / EBITDA"):
        assert not referencias.atravessa_a_frequencia(estrutural), estrutural

    # **As duas conversoes ficaram fora, e pelo mesmo criterio.** O FCO de um
    # trimestre carrega imposto e juro pagos; o CGO carrega provisao e
    # impairment. Os dois numeradores sao irregulares dentro do ano, e os dois
    # se concentram no fechamento do exercicio.
    assert not referencias.atravessa_a_frequencia("Conversao de caixa (FCO / EBITDA)")

    for atravessa in (
        "Margem EBITDA",
        "Margem liquida",
        "Liquidez corrente",
        "Capex / Receita",
        "Ciclo de conversao de caixa (dias)",
        "Divida bruta / Patrimonio liquido",
    ):
        assert referencias.atravessa_a_frequencia(atravessa), atravessa

    # **A invariante não é mais "está em `BASE`", e ela era o que mantinha o Kd
    # fora de alcance.** `BASE` é o conjunto dos indicadores com distribuição
    # medida, e a lista responde uma segunda pergunta que não depende disso: a
    # mediana da companhia se compara com uma premissa anual? `Custo da dívida
    # efetivo` sai a 0,26x numa série trimestral e nunca esteve em `BASE`.
    #
    # A checagem que substitui é mais forte: o nome tem de ser um indicador que
    # `analisar` de fato produz. Isso pega o erro de digitação que a anterior
    # pegava, e alcança os nomes fora de `BASE`.
    from pathlib import Path

    from valuation.historico import analisar
    from valuation.importacao.cvm import importar_cvm

    recorte = Path(__file__).parent / "dados" / "cvm"
    produzidos = set(analisar(importar_cvm(5410, [2024], cache=recorte)).indicadores.index)
    orfaos = sorted(i for i in referencias.SO_NO_EXERCICIO if i not in produzidos)
    assert not orfaos, f"indicador listado que a análise não produz: {orfaos}"


def test_a_conversao_operacional_nao_atravessa_a_frequencia():
    """O CGO é antes do imposto e do juro — e isso é metade do argumento.

    Ele é lucro **mais os ajustes não-caixa**, e provisão, impairment e baixa de
    ativo são tão irregulares dentro do ano quanto o imposto pago: concentram-se
    no fechamento do exercício. É o mesmo critério que tirou `Conversão de
    caixa` da lista, aplicado um degrau adiante.

    Medido em 80 companhias, ano móvel contra trimestre isolado **do mesmo
    período** — sem o confundidor de mudança real: 17,9 pontos de desvio de
    percentil, o pior do grupo que atravessa por 7,8 pontos de folga, e acima de
    quatro dos oito que não atravessam.

    Confirmado em **três rodadas, duas populações e duas metodologias**, e o que
    fecha o argumento é a comparação com a irmã: a `Conversão de caixa` já tinha
    saído da lista por carregar imposto e juro pagos, e a `Conversão
    operacional` mede **pior que ela nas três** (20,3 × 17,7; 18,3 × 13,5;
    17,9 × 14,3). Não havia leitura em que a que ficou fosse a mais regular.
    """
    from valuation import referencias

    assert not referencias.atravessa_a_frequencia("Conversao operacional (CGO / EBITDA)")
    assert not referencias.atravessa_a_frequencia("Conversao de caixa (FCO / EBITDA)")


def test_estoque_sobre_estoque_atravessa_a_frequencia():
    """A previsão estrutural que a medição controlada confirmou exatamente.

    Razão entre dois saldos não depende de quanto tempo a coluna cobre, e as
    três da base medem **0,0 pontos** de desvio entre a leitura anual e a
    trimestral do mesmo período — não "quase zero": zero.
    """
    from valuation import referencias

    for indicador in (
        "Liquidez corrente",
        "Divida bruta / Patrimonio liquido",
        "Arrendamento / Divida bruta",
    ):
        assert referencias.atravessa_a_frequencia(indicador), indicador


def test_fluxo_sobre_estoque_nao_atravessa_ainda_que_fora_da_base():
    """A lista servia só ao percentil, e por isso o Kd ficava sem guarda.

    Percentil só existe para indicador medido, então nome fora de `BASE` nunca
    entrava — mas a lista responde uma **segunda** pergunta, que não depende de
    haver distribuição: a mediana da companhia se compara com uma premissa
    anual?

    Medida a razão entre as duas leituras do **mesmo período** (ano móvel de
    2025 contra trimestres isolados de 2025) em 60 companhias, o grupo aparece
    sozinho: giro do ativo 0,25x, giro do capital investido 0,26x, custo da
    dívida efetivo 0,26x — o numerador encolhe com a coluna e o denominador, que
    é saldo, não.
    """
    from valuation import referencias

    for indicador in (
        "Giro do ativo",
        "Giro do capital investido",
        "Custo da divida efetivo",
        "Custo da divida pelo caixa",
        "FCO / Passivo circulante",
        "Reinvestimento",
        "Fluxo de caixa livre (FCO - capex)",
        "Crescimento fundamentado (reinvest. x ROIC)",
    ):
        assert not referencias.atravessa_a_frequencia(indicador), indicador


def test_fluxo_sobre_fluxo_do_mesmo_periodo_continua_atravessando():
    """O controle, e ele importa porque a medição tentou puxar dois para fora.

    `Capex / Receita` move 1,42x e `Depreciacao / Receita` 1,51x entre as duas
    leituras — mas os dois são fluxo sobre fluxo do mesmo período, e o que os
    move é lumpiness dentro do ano: capex se concentra em trimestres. O desvio
    de percentil deles é de 9,1 e 10,1 pontos, dentro da faixa do grupo que
    atravessa.

    A classificação é **por estrutura e não pelo desvio**. Este teste é o que
    impede que a próxima medição os arraste para fora.
    """
    from valuation import referencias

    for indicador in ("Capex / Receita", "Depreciacao / Receita", "Aluguel / EBITDA"):
        assert referencias.atravessa_a_frequencia(indicador), indicador


def test_as_duas_medicoes_de_frequencia_ordenam_diferente():
    """Por que a classificação é **por estrutura**, com dois números medidos.

    Há duas formas de medir quanto um indicador sofre com a troca de
    frequência, e elas não são a mesma coisa:

    * **desvio de percentil** — quantos pontos o indicador anda na distribuição
      da base entre as duas leituras. Mede o efeito sobre a *comparação*.
    * **razão de nível** — quanto o próprio número encolhe ou cresce. Mede o
      efeito sobre o *valor*.

    Medidas no mesmo par de leituras (ano móvel contra trimestres isolados do
    mesmo período), elas **ordenam diferente**:

    | | desvio | razão |
    |---|---|---|
    | Taxa de reinvestimento | 6,6p — 6º de 7 | **1,64x — 3º de 7** |
    | Conversão operacional | **17,9p — 2º de 7** | 1,30x — 6º de 7 |
    | Investimento em giro | 17,0p | 2,77x |
    | Liquidez corrente | 0,0p | 1,00x |

    Um indicador pode ficar quieto no percentil e mover 64% no nível — basta que
    a distribuição da base seja larga o bastante para absorver a diferença. E
    pode mover pouco no nível e muito no percentil, se a base for apertada ali.

    **Classificar por qualquer uma das duas sozinha erraria**, e em direções
    opostas: pelo percentil, `Taxa de reinvestimento` passaria (6,6p está na
    faixa do grupo que atravessa); pela razão, `Conversão operacional` passaria
    (1,30x é menos que `Capex / Receita`, que atravessa).

    É por isso que a regra deste projeto é classificar pela **estrutura** — os
    dois misturam fluxo do período com termo irregular dentro do ano — e usar as
    medições para confirmar, nunca para decidir.
    """
    from valuation import referencias

    # Os dois que cada metodo deixaria passar sozinho, e que a estrutura pega.
    assert not referencias.atravessa_a_frequencia("Taxa de reinvestimento")
    assert not referencias.atravessa_a_frequencia("Conversao operacional (CGO / EBITDA)")
    assert not referencias.atravessa_a_frequencia("Investimento em giro (DFC) / Receita")

    # E o controle nos dois metodos ao mesmo tempo: estoque sobre estoque nao se
    # move nem no percentil (0,0p) nem no nivel (1,00x).
    assert referencias.atravessa_a_frequencia("Liquidez corrente")

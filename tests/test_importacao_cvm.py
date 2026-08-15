"""Testes do leitor dos Dados Abertos da CVM.

Os fixtures em ``tests/dados/cvm`` nao foram escritos a mao: sao recortes em
bytes dos arquivos publicados em dados.cvm.gov.br -- o zip da DFP de 2023 e
2024 e o cadastro de companhias --, filtrados para quatro companhias e com o
latin-1, o ``;`` e o CRLF originais preservados. Testar contra planilha
inventada foi exatamente o que deixou passar os bugs que este projeto ja pagou
para descobrir.

As quatro companhias do recorte cobrem, cada uma, um comportamento diferente do
arquivo real:

======================  =====  ==========================================
Companhia               CVM    Por que esta aqui
======================  =====  ==========================================
WEG S.A.                 5410  ESCALA_MOEDA = MIL; publica con e ind
Vivara Participacoes    24805  ESCALA_MOEDA = UNIDADE (a pegadinha)
Sao Martinho            20516  exercicio social fecha em 31/03
Elektro Redes           17485  so publica demonstracao individual
======================  =====  ==========================================
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from valuation.historico import analisar, sugerir_premissas
from valuation.importacao import (
    Demonstracoes,
    aplicar_mapeamento_manual,
    carregar_abas,
)
from valuation.importacao.cvm import (
    ENCODING,
    SEPARADOR,
    Companhia,
    ErroCVM,
    _apenas_da_companhia,
    _fator_escala,
    baixar_dfp,
    buscar_companhias,
    carregar_cadastro,
    importar_cvm,
)

DADOS = Path(__file__).parent / "dados" / "cvm"

WEG, VIVARA, SAO_MARTINHO, ELEKTRO = 5410, 24805, 20516, 17485


@pytest.fixture(scope="module")
def catalogo() -> list[Companhia]:
    return carregar_cadastro(DADOS / "cad_cia_aberta.csv")


@pytest.fixture(scope="module")
def weg() -> Demonstracoes:
    return importar_cvm(WEG, [2023, 2024], cache=DADOS)


# ---------------------------------------------------------------------------
# O contrato do arquivo: o que foi conferido no portal, virado teste
# ---------------------------------------------------------------------------


def test_arquivo_da_cvm_e_latin1_e_nao_utf8():
    """O encoding e latin-1. Ler como UTF-8 estoura na primeira acentuacao.

    Fixa a descoberta para que ninguem "padronize" o modulo para UTF-8 por
    parecer o certo: o arquivo da CVM nao e UTF-8, e a excecao abaixo prova.
    """
    with zipfile.ZipFile(DADOS / "dfp_cia_aberta_2024.zip") as arquivo:
        bruto = arquivo.read("dfp_cia_aberta_DRE_con_2024.csv")

    with pytest.raises(UnicodeDecodeError):
        bruto.decode("utf-8")

    texto = bruto.decode(ENCODING)
    assert "Demonstração do Resultado" in texto
    assert "PENÚLTIMO" in texto


def test_layout_das_colunas_da_dfp():
    """As colunas que o leitor consome existem, com o separador esperado."""
    esperado_bp = [
        "CNPJ_CIA", "DT_REFER", "VERSAO", "DENOM_CIA", "CD_CVM", "GRUPO_DFP",
        "MOEDA", "ESCALA_MOEDA", "ORDEM_EXERC", "DT_FIM_EXERC", "CD_CONTA",
        "DS_CONTA", "VL_CONTA", "ST_CONTA_FIXA",
    ]
    with zipfile.ZipFile(DADOS / "dfp_cia_aberta_2024.zip") as arquivo:
        cabecalho_bp = (
            arquivo.read("dfp_cia_aberta_BPA_con_2024.csv")
            .split(b"\r\n")[0].decode(ENCODING).split(SEPARADOR)
        )
        cabecalho_dre = (
            arquivo.read("dfp_cia_aberta_DRE_con_2024.csv")
            .split(b"\r\n")[0].decode(ENCODING).split(SEPARADOR)
        )

    assert cabecalho_bp == esperado_bp
    # A DRE e a DFC descrevem um periodo, nao uma data: tem DT_INI_EXERC a mais.
    assert cabecalho_dre == esperado_bp[:9] + ["DT_INI_EXERC"] + esperado_bp[9:]


def test_nenhum_campo_contem_o_separador():
    """O recorte em bytes depende disso: CD_CVM sempre na mesma posicao.

    Se a CVM passar a citar campos com ';' dentro, a contagem de campos varia e
    o filtro rapido silenciosamente deixaria de achar a empresa. Melhor descobrir
    aqui do que numa importacao vazia.
    """
    with zipfile.ZipFile(DADOS / "dfp_cia_aberta_2024.zip") as arquivo:
        for nome in arquivo.namelist():
            linhas = [l for l in arquivo.read(nome).split(b"\r\n") if l]
            campos = {l.count(b";") for l in linhas}
            assert len(campos) == 1, f"{nome} tem linhas com contagem de campos diferente"


def test_recorte_em_bytes_pega_so_a_companhia():
    with zipfile.ZipFile(DADOS / "dfp_cia_aberta_2024.zip") as arquivo:
        bruto = arquivo.read("dfp_cia_aberta_DRE_con_2024.csv")

    recorte = _apenas_da_companhia(bruto, WEG)
    assert recorte is not None
    linhas = [l for l in recorte.split(b"\r\n") if l]

    assert linhas[0] == bruto.split(b"\r\n")[0], "o cabecalho tem que sobreviver"
    assert len(linhas) > 1
    for linha in linhas[1:]:
        assert linha.split(b";")[4].lstrip(b"0") == str(WEG).encode()
    # O fixture tem quatro companhias; o recorte tem que ser menor que o todo.
    assert len(linhas) < len([l for l in bruto.split(b"\r\n") if l])


def test_recorte_em_bytes_de_companhia_ausente():
    with zipfile.ZipFile(DADOS / "dfp_cia_aberta_2024.zip") as arquivo:
        bruto = arquivo.read("dfp_cia_aberta_DRE_con_2024.csv")
    assert _apenas_da_companhia(bruto, 999_999) is None


def test_recorte_em_bytes_nao_muda_o_resultado():
    """A otimizacao e invisivel: os numeros tem que ser os mesmos de antes."""
    dfs = importar_cvm(WEG, [2024], cache=DADOS)
    assert dfs.valor("receita_liquida", 2024) == pytest.approx(37_986_941_000.0)
    assert dfs.valor("ativo_total", 2024) == dfs.valor("passivo_total", 2024)


@pytest.mark.parametrize(
    "escala,fator",
    [("MIL", 1_000.0), ("UNIDADE", 1.0), ("mil", 1_000.0), ("MILHAO", 1_000_000.0)],
)
def test_fator_de_escala(escala, fator):
    assert _fator_escala(escala, []) == fator


def test_escala_desconhecida_avisa_em_vez_de_adivinhar():
    avisos: list[str] = []
    assert _fator_escala("BILHAO", avisos) == 1.0
    assert avisos and "ESCALA_MOEDA desconhecida" in avisos[0]


# ---------------------------------------------------------------------------
# Pegadinha 1: ESCALA_MOEDA
# ---------------------------------------------------------------------------


def test_escala_mil_vira_reais(weg):
    """WEG publica em MIL: 37.986.941 no arquivo sao R$ 38 bilhoes."""
    assert weg.valor("receita_liquida", 2024) == pytest.approx(37_986_941_000.0)
    assert weg.valor("lucro_liquido", 2024) == pytest.approx(6_318_763_000.0)


def test_escala_unidade_nao_e_multiplicada(catalogo):
    """Vivara publica em UNIDADE: 2.577.113.417 ja sao R$ 2,6 bilhoes.

    O numero bruto e maior que o da WEG, que vale dez vezes mais. Quem ignora
    ESCALA_MOEDA erra nas duas empresas, e em direcoes opostas.
    """
    vivara = importar_cvm(VIVARA, [2024], cache=DADOS, catalogo=catalogo)
    receita = vivara.valor("receita_liquida", 2024)

    assert receita == pytest.approx(2_577_113_417.0)
    # A armadilha concreta: multiplicar por mil daria R$ 2,6 trilhoes.
    assert receita < 1e12


def test_duas_empresas_de_escalas_diferentes_ficam_comparaveis(weg, catalogo):
    """Depois da conversao, comparar as duas empresas passa a fazer sentido."""
    vivara = importar_cvm(VIVARA, [2024], cache=DADOS, catalogo=catalogo)
    razao = weg.valor("receita_liquida", 2024) / vivara.valor("receita_liquida", 2024)
    assert 10 < razao < 20  # WEG fatura cerca de 15x a Vivara


# ---------------------------------------------------------------------------
# Pegadinha 2: ORDEM_EXERC
# ---------------------------------------------------------------------------


def test_arquivo_anual_contem_o_ano_anterior_como_penultimo():
    """A premissa da pegadinha: o zip de 2024 ja traz 2023 dentro dele."""
    with zipfile.ZipFile(DADOS / "dfp_cia_aberta_2024.zip") as arquivo:
        linhas = arquivo.read("dfp_cia_aberta_DRE_con_2024.csv").decode(ENCODING).splitlines()

    fins = {
        campos[10]
        for linha in linhas[1:]
        if (campos := linha.split(SEPARADOR)) and campos[8] == "PENÚLTIMO"
    }
    assert fins == {"2023-12-31", "2023-03-31"}


def test_anos_nao_duplicam_ao_empilhar_arquivos(weg):
    """Dois zips, dois anos -- nao tres nem quatro."""
    assert weg.anos == [2023, 2024]
    assert len(weg.anos) == len(set(weg.anos))


def test_usa_o_exercicio_ultimo_de_cada_arquivo(catalogo):
    """2023 vem do arquivo de 2023, nao do PENULTIMO do arquivo de 2024.

    Os dois costumam bater, mas so o ULTIMO e o numero como a companhia o
    publicou naquele exercicio; o PENULTIMO ja pode vir reapresentado.
    """
    with zipfile.ZipFile(DADOS / "dfp_cia_aberta_2023.zip") as arquivo:
        linhas = arquivo.read("dfp_cia_aberta_DRE_con_2023.csv").decode(ENCODING).splitlines()

    esperado = next(
        float(campos[13])
        for linha in linhas[1:]
        if (campos := linha.split(SEPARADOR))
        and campos[4].lstrip("0") == str(WEG)
        and campos[11] == "3.01"
        and campos[8] == "ÚLTIMO"
    )

    so_2023 = importar_cvm(WEG, [2023], cache=DADOS, catalogo=catalogo)
    assert so_2023.valor("receita_liquida", 2023) == pytest.approx(esperado * 1_000)


# ---------------------------------------------------------------------------
# Longo -> colunas por ano
# ---------------------------------------------------------------------------


def test_pivo_produz_contas_canonicas_x_anos(weg):
    assert list(weg.valores.columns) == [2023, 2024]
    for chave in ("receita_liquida", "ebit", "lucro_liquido", "ativo_total",
                  "patrimonio_liquido", "caixa_equivalentes"):
        assert weg.tem(chave), f"{chave} deveria ter vindo da CVM"


def test_codigo_cvm_vira_conta_canonica(weg):
    """O reconhecimento vem do plano de contas, nao do texto do rotulo."""
    assert weg.mapeamento["receita_liquida"].startswith("3.01")
    assert weg.mapeamento["patrimonio_liquido"].startswith("2.03")
    assert weg.mapeamento["caixa_equivalentes"].startswith("1.01.01")
    assert weg.mapeamento["ativo_total"].startswith("1 -")


def test_identidade_do_balanco_fecha(weg):
    """Ativo = passivo, exatamente, nos dois anos."""
    for ano in weg.anos:
        assert weg.valor("ativo_total", ano) == weg.valor("passivo_total", ano)
    assert not weg.avisos, f"a WEG nao deveria gerar aviso: {weg.avisos}"


def test_custos_viram_magnitude_positiva(weg):
    """A CVM publica CPV negativo; o motor subtrai a conta, entao guarda o modulo."""
    assert weg.valor("custo_produtos_vendidos", 2024) > 0
    assert weg.valor("impostos", 2024) > 0
    # E o resultado bruto continua fechando com receita - CPV.
    assert weg.valor("lucro_bruto", 2024) == pytest.approx(
        weg.valor("receita_liquida", 2024) - weg.valor("custo_produtos_vendidos", 2024)
    )


def test_linha_da_dfc_nao_invade_conta_do_balanco(weg):
    """A DFC da WEG tem uma linha chamada so "Imobilizado" -- que e capex.

    Sem amarrar o reconhecimento a demonstracao de origem, esse fluxo de caixa
    sobrescreveria o saldo de imobilizado do balanco.
    """
    assert weg.mapeamento["imobilizado"].startswith("1.02.03")
    assert weg.valor("imobilizado", 2024) == pytest.approx(9_933_659_000.0)


def test_nada_e_descartado_em_silencio(weg):
    """As contas analiticas que o modelo nao usa saem listadas, nao sumidas."""
    assert len(weg.nao_reconhecidas) > 50
    rotulos = [linha.rotulo for linha in weg.nao_reconhecidas]
    assert any(r.startswith("1.01.06") for r in rotulos)  # tributos a recuperar
    assert all(linha.aba in {"DRE", "Balanço", "DFC"} for linha in weg.nao_reconhecidas)


# ---------------------------------------------------------------------------
# Casos reais que quebram a suposicao ingenua
# ---------------------------------------------------------------------------


def test_exercicio_social_que_nao_fecha_em_dezembro(catalogo):
    """Sao Martinho fecha em 31/03. O ano e o do encerramento, nao o do arquivo."""
    dfs = importar_cvm(SAO_MARTINHO, [2023, 2024], cache=DADOS, catalogo=catalogo)
    assert dfs.anos == [2023, 2024]
    assert dfs.valor("receita_liquida", 2024) == pytest.approx(6_891_738_000.0)


def test_companhia_sem_consolidado_cai_para_o_individual(catalogo):
    """Elektro Redes so publica individual -- e o app precisa dizer isso."""
    dfs = importar_cvm(ELEKTRO, [2024], cache=DADOS, catalogo=catalogo)
    assert dfs.valor("receita_liquida", 2024) == pytest.approx(9_328_000_000.0)
    assert any("individual" in aviso for aviso in dfs.avisos)


def test_companhia_inexistente_explica_o_que_houve(catalogo):
    with pytest.raises(ErroCVM, match="nao tem DFP desta companhia"):
        importar_cvm(999_999, [2024], cache=DADOS, catalogo=catalogo)


def test_ano_sem_arquivo_no_cache_nao_inventa_numero():
    with pytest.raises(ErroCVM):
        importar_cvm(WEG, [1998], cache=DADOS)


def test_lista_de_anos_vazia_e_erro():
    with pytest.raises(ErroCVM, match="ao menos um ano"):
        importar_cvm(WEG, [], cache=DADOS)


# ---------------------------------------------------------------------------
# Cadastro e busca
# ---------------------------------------------------------------------------


def test_cadastro_carrega_companhias(catalogo):
    assert len(catalogo) == 4
    codigos = {c.codigo_cvm for c in catalogo}
    assert codigos == {WEG, VIVARA, SAO_MARTINHO, ELEKTRO}
    assert all(c.ativa for c in catalogo)


def test_busca_por_nome(catalogo):
    achados = buscar_companhias("weg", catalogo)
    assert [c.codigo_cvm for c in achados] == [WEG]


def test_busca_ignora_acento_e_caixa(catalogo):
    assert buscar_companhias("sao martinho", catalogo)[0].codigo_cvm == SAO_MARTINHO
    assert buscar_companhias("SÃO MARTINHO", catalogo)[0].codigo_cvm == SAO_MARTINHO


@pytest.mark.parametrize("termo", ["84.429.695/0001-11", "84429695000111"])
def test_busca_por_cnpj_com_ou_sem_pontuacao(catalogo, termo):
    assert buscar_companhias(termo, catalogo)[0].codigo_cvm == WEG


def test_busca_vazia_nao_devolve_o_catalogo_inteiro(catalogo):
    assert buscar_companhias("", catalogo) == []
    assert buscar_companhias("   ", catalogo) == []


def test_busca_sem_resultado(catalogo):
    assert buscar_companhias("empresa que nao existe", catalogo) == []


def test_quem_comeca_com_o_termo_vem_antes(catalogo):
    """Buscar "vivara" tem que trazer a Vivara, nao quem so a menciona."""
    achados = buscar_companhias("vivara", catalogo)
    assert achados[0].codigo_cvm == VIVARA


def test_cadastro_traz_cnpj_e_setor(catalogo):
    weg = next(c for c in catalogo if c.codigo_cvm == WEG)
    assert weg.cnpj == "84.429.695/0001-11"
    assert weg.setor
    assert "WEG" in str(weg)


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


def test_arquivo_em_cache_nao_e_rebaixado(monkeypatch):
    """Com o zip em disco, nenhuma conexao e aberta."""
    def explodir(*args, **kwargs):
        raise AssertionError("tentou baixar um arquivo que ja estava em cache")

    monkeypatch.setattr("urllib.request.urlopen", explodir)
    caminho = baixar_dfp(2024, cache=DADOS)
    assert caminho.exists()
    assert caminho.name == "dfp_cia_aberta_2024.zip"


def test_download_grava_e_reaproveita(monkeypatch, tmp_path):
    chamadas: list[str] = []

    class RespostaFalsa:
        def __init__(self, dado):
            self._dado = dado

        def read(self):
            return self._dado

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def falsa(url, timeout=None):
        chamadas.append(url)
        return RespostaFalsa(b"conteudo-zip")

    monkeypatch.setattr("urllib.request.urlopen", falsa)

    primeiro = baixar_dfp(2019, cache=tmp_path)
    assert primeiro.read_bytes() == b"conteudo-zip"
    assert len(chamadas) == 1

    baixar_dfp(2019, cache=tmp_path)
    assert len(chamadas) == 1, "o segundo pedido deveria sair do cache"


def test_download_interrompido_nao_deixa_arquivo_truncado(monkeypatch, tmp_path):
    """Meio arquivo em disco seria lido como valido na proxima execucao."""
    import urllib.error

    def falhar(url, timeout=None):
        raise urllib.error.URLError("conexao caiu")

    monkeypatch.setattr("urllib.request.urlopen", falhar)

    with pytest.raises(ErroCVM, match="tentativas"):
        baixar_dfp(2019, cache=tmp_path)

    assert list(tmp_path.iterdir()) == []


def test_conexao_cortada_no_meio_vira_mensagem_e_nao_crash(monkeypatch, tmp_path):
    """``IncompleteRead`` nao e ``URLError`` -- e o portal corta zips de 13 MB.

    Sem tratar esta excecao especifica, o corte no meio do download subia como
    erro nao tratado ate a tela do usuario. Aconteceu de verdade baixando o
    arquivo de 2024.
    """
    import http.client

    def cortar(url, timeout=None):
        raise http.client.IncompleteRead(b"come" * 10, 2_952_985)

    monkeypatch.setattr("urllib.request.urlopen", cortar)

    with pytest.raises(ErroCVM, match="corta a conexao"):
        baixar_dfp(2024, cache=tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_download_tenta_de_novo_antes_de_desistir(monkeypatch, tmp_path):
    """Falha transitoria nao pode custar um clique ao usuario."""
    import http.client

    chamadas = []

    class Resposta:
        def read(self):
            return b"zip-de-verdade"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def instavel(url, timeout=None):
        chamadas.append(url)
        if len(chamadas) == 1:
            raise http.client.IncompleteRead(b"", 100)
        return Resposta()

    monkeypatch.setattr("urllib.request.urlopen", instavel)

    caminho = baixar_dfp(2019, cache=tmp_path)
    assert caminho.read_bytes() == b"zip-de-verdade"
    assert len(chamadas) == 2, "deveria ter tentado duas vezes"
    assert not list(tmp_path.glob("*.parcial"))


def test_zip_corrompido_sugere_limpar_o_cache(tmp_path):
    (tmp_path / "dfp_cia_aberta_2024.zip").write_bytes(b"isto nao e um zip")
    with pytest.raises(ErroCVM, match="cache"):
        importar_cvm(WEG, [2024], cache=tmp_path)


# ---------------------------------------------------------------------------
# Integracao com o resto do motor
# ---------------------------------------------------------------------------


def test_demonstracoes_da_cvm_alimentam_a_analise_historica(weg):
    analise = analisar(weg)
    assert not analise.indicadores.empty

    sugestao = sugerir_premissas(analise, horizonte=5)
    assert sugestao.operacionais.receita_base == pytest.approx(37_986_941_000.0)
    assert sugestao.operacionais.ano_base == 2024
    # Divida bruta = curto + longo prazo, direto do balanco da CVM.
    assert sugestao.ponte.divida_bruta == pytest.approx(
        weg.valor("divida_curto_prazo", 2024) + weg.valor("divida_longo_prazo", 2024)
    )


def test_valores_saem_em_reais_e_a_escala_e_do_app(weg):
    assert weg.unidade == "R$"
    assert weg.moeda == "BRL"

    milhoes = weg.escalar(1_000_000, "R$ milhões")
    assert milhoes.valor("receita_liquida", 2024) == pytest.approx(37_986.941)
    assert milhoes.unidade == "R$ milhões"


def test_origem_identifica_a_fonte(weg):
    assert "CVM" in weg.origem and "2023" in weg.origem and "2024" in weg.origem


def test_fonte_guarda_como_rebuscar(weg):
    """``origem`` e frase para ler; ``fonte`` e o suficiente para repetir a busca."""
    assert weg.fonte == {"tipo": "cvm", "codigo_cvm": WEG, "anos": [2023, 2024]}

    # Refazer a busca a partir da fonte tem que devolver os mesmos numeros.
    de_novo = importar_cvm(
        weg.fonte["codigo_cvm"], weg.fonte["anos"], cache=DADOS
    )
    assert de_novo.valores.equals(weg.valores)


def test_fonte_sobrevive_a_troca_de_unidade(weg):
    """``escalar`` cria outro objeto; perder a fonte ali quebraria o botao de atualizar."""
    assert weg.escalar(1_000_000, "R$ milhões").fonte == weg.fonte


def test_fonte_sobrevive_a_correcao_manual(tmp_path):
    destino = tmp_path / "weg.xlsx"
    dfs = importar_cvm(WEG, [2024], cache=DADOS, planilha=destino)
    alvo = next(
        l.rotulo for l in dfs.nao_reconhecidas if l.rotulo.startswith("1.02.01")
    )
    corrigido = aplicar_mapeamento_manual(dfs, destino, {alvo: "aplicacoes_financeiras"})
    assert corrigido.fonte == dfs.fonte


# ---------------------------------------------------------------------------
# A planilha de conferencia, que e o que liga a CVM a tela de correcao manual
# ---------------------------------------------------------------------------


def test_planilha_gerada_tem_uma_aba_por_demonstracao(tmp_path):
    destino = tmp_path / "weg.xlsx"
    importar_cvm(WEG, [2023, 2024], cache=DADOS, planilha=destino)

    abas = carregar_abas(destino)
    assert set(abas) == {"DRE", "Balanço", "DFC"}

    dre = abas["DRE"]
    assert list(dre.iloc[0]) == ["Código", "Conta", 2023, 2024]
    assert (dre.iloc[:, 1] == "3.01 - Receita de Venda de Bens e/ou Serviços").any()


def test_planilha_permite_corrigir_um_mapeamento_a_mao(tmp_path):
    """E o caminho que a tela de conferencia usa quando o usuario remapeia.

    Sem um arquivo em disco com os rotulos originais, a correcao manual --
    que ja existe para as outras origens -- ficaria indisponivel justamente
    na origem com mais linhas nao reconhecidas.
    """
    destino = tmp_path / "weg.xlsx"
    dfs = importar_cvm(WEG, [2023, 2024], cache=DADOS, planilha=destino)

    alvo = next(
        linha.rotulo
        for linha in dfs.nao_reconhecidas
        if linha.rotulo.startswith("1.02.01")
    )
    corrigido = aplicar_mapeamento_manual(dfs, destino, {alvo: "aplicacoes_financeiras"})

    assert corrigido.valor("aplicacoes_financeiras", 2024) == pytest.approx(1_442_220_000.0)
    assert "[manual]" in corrigido.mapeamento["aplicacoes_financeiras"]
    assert len(corrigido.nao_reconhecidas) == len(dfs.nao_reconhecidas) - 1


def test_planilha_traz_os_valores_ja_em_reais(tmp_path):
    """A escala e resolvida antes de escrever: a planilha nao herda a pegadinha."""
    destino = tmp_path / "vivara.xlsx"
    importar_cvm(VIVARA, [2024], cache=DADOS, planilha=destino)

    dre = carregar_abas(destino)["DRE"]
    linha = dre[dre.iloc[:, 0] == "3.01"]
    assert float(linha.iloc[0, 2]) == pytest.approx(2_577_113_417.0)

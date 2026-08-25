"""Importacao direta dos Dados Abertos da CVM (dados.cvm.gov.br).

As outras origens partem de um arquivo que o usuario ja tem na maquina. Esta
parte de um identificador -- empresa e ano -- e vai buscar o arquivo. O que muda
nao e o vocabulario, que continua sendo o de ``esquema.py``, e sim duas camadas
novas: o **download com cache** e a conversao do **formato longo** da CVM (uma
linha por conta, por exercicio) para o formato de colunas por ano que o resto do
projeto usa.

O que foi confirmado nos arquivos reais, e nao suposto
------------------------------------------------------

Baixados e inspecionados em 15/08/2026 (DFP 2024 e cadastro):

* **Encoding ``latin-1``**, nao UTF-8. ``Demonstra\\xe7\\xe3o`` e ``PEN\\xdaLTIMO``
  aparecem como bytes soltos; decodificar como UTF-8 levanta excecao logo na
  primeira acentuacao. Nenhum byte na faixa 0x80-0x9F, entao ``cp1252`` leria
  igual -- ``latin-1`` e a escolha segura por nunca falhar.
* **Separador ``;``** e quebra de linha CRLF.
* **Colunas** (DRE e DFC tem ``DT_INI_EXERC`` a mais que BPA e BPP)::

      CNPJ_CIA;DT_REFER;VERSAO;DENOM_CIA;CD_CVM;GRUPO_DFP;MOEDA;ESCALA_MOEDA;
      ORDEM_EXERC;[DT_INI_EXERC;]DT_FIM_EXERC;CD_CONTA;DS_CONTA;VL_CONTA;ST_CONTA_FIXA

* **O zip anual** traz um CSV por demonstracao e por escopo (``_con``
  consolidado, ``_ind`` individual), mais a DFC separada por metodo
  (``DFC_MI`` indireto, ``DFC_MD`` direto).

As duas pegadinhas, medidas
---------------------------

**``ORDEM_EXERC``** vem com ``ULTIMO`` e ``PENULTIMO`` no mesmo arquivo, metade
das linhas cada. No arquivo de 2024, ``PENULTIMO`` e o exercicio de 2023 -- que
tambem aparece como ``ULTIMO`` no arquivo de 2023. Empilhar dois anos sem
filtrar duplica o ano do meio. Este modulo le **so ``ULTIMO``** e baixa um zip
por ano pedido: cada ano entra uma vez so, e sempre na versao publicada no
proprio exercicio, sem misturar numeros originais com numeros reapresentados.

**``ESCALA_MOEDA``** diz se ``VL_CONTA`` esta em ``MIL`` ou em ``UNIDADE``, e
varia entre empresas do mesmo arquivo: em 2024, 459 companhias publicaram em
milhares e 8 em unidades. A receita da WEG aparece como ``37.986.941`` (MIL, ou
R$ 38 bi) e a da Vivara como ``2.577.113.417`` (UNIDADE, ou R$ 2,6 bi). Ignorar
o campo erra por mil vezes, para mais ou para menos, dependendo da empresa.
Aqui tudo e convertido para **unidades de real** na leitura, e a escala de
apresentacao fica com o app.
"""

from __future__ import annotations

import http.client
import io
import re
import unicodedata
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from .esquema import CONTAS, POR_CHAVE, Conta, normalizar, reconhecer
from .importador import (
    CONFIANCA_MINIMA,
    Demonstracoes,
    LinhaNaoReconhecida,
    _ajustar_sinal,
    _conferir,
    _derivar,
)

BASE = "https://dados.cvm.gov.br/dados/CIA_ABERTA"
URL_DFP = BASE + "/DOC/DFP/DADOS/dfp_cia_aberta_{ano}.zip"
URL_ITR = BASE + "/DOC/ITR/DADOS/itr_cia_aberta_{ano}.zip"
URL_CADASTRO = BASE + "/CAD/DADOS/cad_cia_aberta.csv"

ENCODING = "latin-1"
SEPARADOR = ";"

# Identifica, no campo ``fonte`` de Demonstracoes, que aquela serie veio daqui e
# pode ser rebuscada.
FONTE_CVM = "cvm"

# O portal publica de 2010 em diante. O limite superior nao e fixo: o arquivo do
# ano corrente ja existe, quase vazio, desde janeiro.
ANO_MINIMO = 2010

# VL_CONTA esta sempre em reais depois de multiplicado por este fator.
FATORES_ESCALA = {"UNIDADE": 1.0, "MIL": 1_000.0, "MILHAO": 1_000_000.0}

TEMPO_LIMITE = 120

# Ordem de preferencia dentro do zip. Consolidado antes de individual porque o
# valuation olha o grupo economico; 242 das 709 companhias de 2024 so publicam
# individual, entao a queda para ``_ind`` nao e excecao rara.
ESCOPOS = ("con", "ind")

# A DFC vem separada por metodo e os dois conjuntos sao disjuntos: em 2024, 451
# companhias no indireto e 16 no direto, nenhuma nos dois.
# Todas as demonstracoes que o zip traz, e nao so as quatro do modelo. A regra
# e simples: **o app le tudo, e quem escolhe o nivel de abertura e quem usa**.
# O vocabulario canonico nomeia umas dezenas de contas porque e delas que o
# motor precisa; o resto fica na arvore publicada, disponivel.
#
# Medido na WEG de 2024: o zip traz 574 linhas consolidadas. DRE, BP e DFC somam
# 276 -- as outras 298 estavam em DMPL, DVA e DRA, que nao eram abertas. Mais da
# metade do que a companhia publica.
#
# A DVA e a que mais devolve: ``7.01.01`` e a **receita bruta** (contra a
# liquida do 3.01, a diferenca sao impostos sobre vendas e devolucoes),
# ``7.08.03.02`` e o **aluguel** pago, ``7.08.01`` a folha e ``7.08.02`` o total
# de impostos. Nada disso aparece na DRE padronizada.
GRUPOS = {
    "dre": ("DRE",),
    "bp": ("BPA", "BPP"),
    "dfc": ("DFC_MI", "DFC_MD"),
    "dva": ("DVA",),
    "dra": ("DRA",),
    "dmpl": ("DMPL",),
}

# A DMPL tem uma dimensao a mais -- ``COLUNA_DF``, o componente do patrimonio --
# entao a mesma conta aparece uma vez por coluna. Na arvore ela entra somada,
# porque o que interessa ali e o movimento total; quem precisa da abertura por
# componente vai ao arquivo.
_DEMONSTRACOES_COM_COLUNA = ("dmpl",)


class ErroCVM(Exception):
    """Falha ao obter ou interpretar um arquivo do portal de dados abertos."""


# ---------------------------------------------------------------------------
# Cache de download
# ---------------------------------------------------------------------------


def diretorio_cache() -> Path:
    """Onde os arquivos baixados ficam entre execucoes.

    Um zip anual tem cerca de 13 MB e nao muda depois que o exercicio fecha;
    rebaixar a cada consulta seria desperdicio de banda do usuario e do portal.
    """
    return Path.home() / ".cache" / "valuation" / "cvm"


# Um zip anual tem 13 MB e o portal corta a conexao no meio com alguma
# frequencia. A segunda tentativa custa poucos segundos e evita mandar o usuario
# clicar de novo por um erro que costuma passar sozinho.
TENTATIVAS = 2


def tamanho_do_cache(cache: Path | None = None) -> int:
    """Bytes ocupados pelos arquivos ja baixados.

    O cache so cresce: um zip por ano, por download, sem nada que o limpe. Doze
    anos de DFP passam de 150 MB numa pasta que o usuario nunca abriu. Saber o
    tamanho e o minimo para ele poder decidir.
    """
    pasta = Path(cache) if cache else diretorio_cache()
    if not pasta.is_dir():
        return 0
    return sum(a.stat().st_size for a in pasta.iterdir() if a.is_file())


def limpar_cache(cache: Path | None = None, manter_cadastro: bool = True) -> int:
    """Apaga os zips baixados e devolve quantos arquivos foram removidos.

    O cadastro de companhias e pequeno e usado em toda busca; por padrao fica,
    para que limpar o cache nao custe um download a mais na proxima tela.
    """
    pasta = Path(cache) if cache else diretorio_cache()
    if not pasta.is_dir():
        return 0
    removidos = 0
    for arquivo in pasta.iterdir():
        if not arquivo.is_file():
            continue
        if manter_cadastro and arquivo.name == "cad_cia_aberta.csv":
            continue
        arquivo.unlink()
        removidos += 1
    return removidos


def _baixar(url: str, destino: Path, forcar: bool = False) -> Path:
    """Baixa ``url`` para ``destino``, reaproveitando o que ja esta em disco.

    A gravacao passa por um arquivo temporario e so entao e renomeada: download
    interrompido no meio nao deixa um arquivo truncado no lugar do bom, que
    seria lido como valido na proxima execucao.
    """
    if destino.exists() and destino.stat().st_size > 0 and not forcar:
        return destino

    destino.parent.mkdir(parents=True, exist_ok=True)
    parcial = destino.with_suffix(destino.suffix + ".parcial")
    ultimo_erro: Exception | None = None

    for tentativa in range(TENTATIVAS):
        try:
            with urllib.request.urlopen(url, timeout=TEMPO_LIMITE) as resposta:
                parcial.write_bytes(resposta.read())
            parcial.replace(destino)
            return destino
        except urllib.error.HTTPError as erro:
            parcial.unlink(missing_ok=True)
            if erro.code == 404:
                raise ErroCVM(
                    f"A CVM nao tem esse arquivo ({url}). Confira o ano escolhido."
                ) from erro
            raise ErroCVM(
                f"O portal da CVM respondeu {erro.code} para {url}."
            ) from erro
        # IncompleteRead nao e URLError -- e HTTPException, e tambem ValueError.
        # Deixar de trata-la fazia a conexao cortada no meio de um zip de 13 MB
        # subir como erro nao tratado ate a tela, em vez da mensagem explicando
        # o que houve.
        except (
            urllib.error.URLError,
            http.client.HTTPException,
            TimeoutError,
            OSError,
        ) as erro:
            parcial.unlink(missing_ok=True)
            ultimo_erro = erro

    raise ErroCVM(
        f"Nao consegui baixar {url} depois de {TENTATIVAS} tentativas: "
        f"{ultimo_erro}. O portal da CVM as vezes corta a conexao em arquivos "
        "grandes -- tente de novo em alguns minutos."
    ) from ultimo_erro


def baixar_dfp(ano: int, cache: Path | None = None, forcar: bool = False) -> Path:
    """Garante o zip da DFP do exercicio ``ano`` em disco e devolve o caminho."""
    cache = Path(cache) if cache else diretorio_cache()
    return _baixar(URL_DFP.format(ano=ano), cache / f"dfp_cia_aberta_{ano}.zip", forcar)


def baixar_itr(ano: int, cache: Path | None = None, forcar: bool = False) -> Path:
    """Garante o zip do ITR do ano em disco e devolve o caminho.

    O ITR de um ano corrente **muda**: cada trimestre entregue acrescenta linhas
    ao mesmo arquivo. Diferente do DFP, que fecha, este vale rebaixar com
    ``forcar=True`` quando se quer o trimestre recem-publicado.
    """
    cache = Path(cache) if cache else diretorio_cache()
    return _baixar(URL_ITR.format(ano=ano), cache / f"itr_cia_aberta_{ano}.zip", forcar)


def baixar_cadastro(cache: Path | None = None, forcar: bool = False) -> Path:
    """Garante o cadastro de companhias abertas em disco e devolve o caminho.

    Diferente dos zips anuais, este arquivo e reescrito todo dia: quem quiser a
    situacao cadastral do dia precisa passar ``forcar=True``.
    """
    cache = Path(cache) if cache else diretorio_cache()
    return _baixar(URL_CADASTRO, cache / "cad_cia_aberta.csv", forcar)


# ---------------------------------------------------------------------------
# Cadastro de companhias: a busca por nome ou CNPJ
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Companhia:
    """Uma companhia aberta registrada na CVM."""

    codigo_cvm: int
    cnpj: str
    nome: str
    nome_comercial: str = ""
    setor: str = ""
    situacao: str = ""
    mercado: str = ""

    @property
    def ativa(self) -> bool:
        return self.situacao.upper().startswith("ATIVO")

    def __str__(self) -> str:
        return f"{self.nome} ({self.cnpj})"


def _so_digitos(texto: str) -> str:
    return re.sub(r"\D", "", str(texto or ""))


def _texto(valor) -> str:
    """Celula do CSV como texto limpo; vazio quando ausente."""
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return ""
    return str(valor).strip()


def carregar_cadastro(
    caminho: str | Path | None = None,
    cache: Path | None = None,
    somente_ativas: bool = True,
) -> list[Companhia]:
    """Le o cadastro de companhias abertas, baixando-o se preciso.

    O arquivo tem uma linha por endereco, nao por companhia -- 2.677 linhas para
    2.566 companhias em agosto de 2026 --, entao a deduplicacao por codigo CVM
    nao e zelo: sem ela a mesma empresa apareceria repetida na busca.
    """
    caminho = Path(caminho) if caminho else baixar_cadastro(cache)
    dados = pd.read_csv(
        caminho, sep=SEPARADOR, encoding=ENCODING, dtype=str, keep_default_na=False
    )

    companhias: dict[int, Companhia] = {}
    for _, linha in dados.iterrows():
        codigo = _so_digitos(linha.get("CD_CVM", ""))
        if not codigo:
            continue
        situacao = _texto(linha.get("SIT"))
        if somente_ativas and not situacao.upper().startswith("ATIVO"):
            continue
        chave = int(codigo)
        if chave in companhias:
            continue
        companhias[chave] = Companhia(
            codigo_cvm=chave,
            cnpj=_texto(linha.get("CNPJ_CIA")),
            nome=_texto(linha.get("DENOM_SOCIAL")),
            nome_comercial=_texto(linha.get("DENOM_COMERC")),
            setor=_texto(linha.get("SETOR_ATIV")),
            situacao=situacao,
            mercado=_texto(linha.get("TP_MERC")),
        )
    return sorted(companhias.values(), key=lambda c: c.nome)


def listar_companhias_do_ano(
    ano: int, cache: Path | None = None, escopo: str = "con"
) -> list[int]:
    """Codigos CVM que publicaram DFP no exercicio, lidos do proprio zip.

    O cadastro lista 2.566 companhias abertas; **quem de fato publicou** DFP
    consolidada de 2024 sao 467. Percorrer o cadastro para montar um universo
    seria gastar cinco vezes mais tempo em companhias que nao tem o que ler.
    """
    caminho = baixar_dfp(ano, cache)
    with zipfile.ZipFile(caminho) as arquivo:
        bruto = arquivo.read(_nome_no_zip("DRE", escopo, ano))

    codigos: set[int] = set()
    for linha in bruto.split(b"\r\n")[1:]:
        campos = linha.split(SEPARADOR.encode(), COLUNA_CD_CVM + 1)
        if len(campos) <= COLUNA_CD_CVM:
            continue
        valor = campos[COLUNA_CD_CVM].lstrip(b"0")
        if valor.isdigit():
            codigos.add(int(valor))
    return sorted(codigos)


def buscar_companhias(
    termo: str, catalogo: list[Companhia], limite: int = 30
) -> list[Companhia]:
    """Busca por nome, nome comercial ou CNPJ.

    O CNPJ e comparado so pelos digitos, entao tanto faz o usuario colar
    ``84.429.695/0001-11`` ou digitar ``84429695000111``. No nome, quem comeca
    com o termo vem antes de quem apenas o contem: procurando por "vale", a
    Vale S.A. interessa mais que a Hidrovias do Brasil -- Vale do Tiete.
    """
    termo = (termo or "").strip()
    if not termo:
        return []

    digitos = _so_digitos(termo)
    if len(digitos) >= 8:
        achados = [c for c in catalogo if digitos in _so_digitos(c.cnpj)]
        if achados:
            return achados[:limite]

    alvo = normalizar(termo)
    if not alvo:
        return []

    comecam, contem = [], []
    for companhia in catalogo:
        nomes = (normalizar(companhia.nome), normalizar(companhia.nome_comercial))
        if any(n.startswith(alvo) for n in nomes):
            comecam.append(companhia)
        elif any(alvo in n for n in nomes):
            contem.append(companhia)
    return (comecam + contem)[:limite]


def anos_disponiveis(cache: Path | None = None, forcar: bool = False) -> list[int]:
    """Anos com arquivo de DFP publicado, lidos do indice do portal.

    Ler o indice em vez de fixar um intervalo evita duas falhas simetricas:
    oferecer um ano que ainda nao existe e esconder o ano que acabou de sair.
    Se o indice nao responder, cai para um intervalo conservador -- e melhor
    oferecer uma lista aproximada que travar a tela.
    """
    try:
        with urllib.request.urlopen(
            URL_DFP.rsplit("/", 1)[0] + "/", timeout=TEMPO_LIMITE
        ) as resposta:
            pagina = resposta.read().decode(ENCODING, errors="replace")
        anos = sorted(
            {int(a) for a in re.findall(r"dfp_cia_aberta_(\d{4})\.zip", pagina)}
        )
        if anos:
            return anos
    except (urllib.error.URLError, TimeoutError, ValueError):
        pass
    return list(range(ANO_MINIMO, date.today().year + 1))


# ---------------------------------------------------------------------------
# Leitura do zip anual
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LinhaCVM:
    """Uma linha do arquivo longo da CVM, ja convertida para reais."""

    codigo: str
    descricao: str
    valor: float
    ano: int
    demonstracao: str
    escala: str
    escopo: str
    # De qual arquivo do zip a linha veio. Existe por causa da DFC: a CVM
    # publica o metodo direto e o indireto em arquivos separados (``DFC_MD`` e
    # ``DFC_MI``) e os dois entram no mesmo grupo ``dfc``, mas os codigos de
    # 6.01 significam coisas diferentes em cada um. O rotulo nao serve para
    # separar -- so 9 das 16 companhias do metodo direto abrem com "Recebimento
    # de Consumidores" --, e o arquivo e a declaracao da propria companhia.
    grupo: str = ""


def _sem_linhas_repetidas(recorte: pd.DataFrame, demonstracao: str) -> pd.DataFrame:
    """Descarta linhas **identicas em todos os campos** do arquivo da CVM.

    Nao e versao do documento nem periodo diferente: e a mesma linha publicada
    duas vezes, byte a byte -- mesma ``VERSAO``, mesmas datas, mesmo valor.
    Medido no DFP consolidado de 2024, sao **2 companhias das 467**, o Grupo
    Salta e a CPX Distribuidora, com 662 e 626 linhas repetidas cada, espalhadas
    por todas as demonstracoes.

    O estrago e seletivo, e por isso passou tanto tempo despercebido: conta
    reconhecida por codigo unico nao muda (a segunda leitura sobrescreve a
    primeira com o mesmo numero), mas **regra somada conta as duas** -- o juro
    pago do Grupo Salta virava R$ 414,6 mi contra os R$ 207,3 mi publicados, e a
    D&A dobrava junto. Nenhuma identidade denuncia, porque as secoes da DFC
    dobram todas na mesma proporcao.

    A DMPL fica de fora: nela a mesma conta aparece legitimamente uma vez por
    componente do patrimonio, e a soma por ``COLUNA_DF`` logo adiante e que
    resolve.
    """
    if demonstracao in _DEMONSTRACOES_COM_COLUNA:
        return recorte
    return recorte.drop_duplicates()


def _nome_no_zip(grupo: str, escopo: str, ano: int, documento: str = "dfp") -> str:
    return f"{documento}_cia_aberta_{grupo}_{escopo}_{ano}.csv"


# Posicao de CD_CVM na linha: CNPJ_CIA;DT_REFER;VERSAO;DENOM_CIA;CD_CVM;...
# A contagem de campos nao varia em nenhum arquivo do portal -- nenhum ';'
# dentro de campo --, entao a posicao e confiavel.
COLUNA_CD_CVM = 4


def _codigo_da_linha(linha: bytes) -> bytes:
    campos = linha.split(SEPARADOR.encode(), COLUNA_CD_CVM + 1)
    if len(campos) <= COLUNA_CD_CVM:
        return b""
    return campos[COLUNA_CD_CVM].strip().strip(b'"').lstrip(b"0") or b"0"


def _apenas_da_companhia(bruto: bytes, codigo_cvm: int) -> bytes | None:
    """Recorta as linhas de uma companhia antes de qualquer parse.

    Um zip anual tem cerca de 129 MB de CSV descompactado e o que interessa sao
    algumas centenas de linhas. Entregar o arquivo inteiro ao pandas para
    descartar 99,9% depois custava mais de um segundo por ano; filtrar em bytes
    troca isso por uma varredura linear e mantem o parse do tamanho do recorte.
    """
    quebra = b"\r\n" if b"\r\n" in bruto else b"\n"
    linhas = bruto.split(quebra)
    if not linhas:
        return None

    alvo = str(codigo_cvm).encode()
    mantidas = [l for l in linhas[1:] if l and _codigo_da_linha(l) == alvo]
    if not mantidas:
        return None
    return quebra.join([linhas[0], *mantidas]) + quebra


def _ler_csv_do_zip(
    zip_path: Path, nome: str, codigo_cvm: int | None = None
) -> pd.DataFrame | None:
    try:
        with zipfile.ZipFile(zip_path) as arquivo:
            if nome not in arquivo.namelist():
                return None
            with arquivo.open(nome) as fluxo:
                bruto = fluxo.read()
    except (zipfile.BadZipFile, OSError) as erro:
        raise ErroCVM(
            f"O arquivo {zip_path.name} nao abriu como zip ({erro}). "
            "Ele pode ter sido baixado pela metade -- apague-o do cache e tente de novo."
        ) from erro

    if codigo_cvm is not None:
        bruto = _apenas_da_companhia(bruto, codigo_cvm)
        if bruto is None:
            return None

    return pd.read_csv(
        io.BytesIO(bruto),
        sep=SEPARADOR,
        encoding=ENCODING,
        dtype=str,
        keep_default_na=False,
    )


# O bloco ``3.99`` da DRE e **por acao**, e nao carrega a escala do arquivo. A
# CVM declara ``ESCALA_MOEDA = MIL`` para a demonstracao inteira e escreve o
# lucro por acao em reais na mesma linha -- o proprio rotulo diz, "Lucro por
# Acao - (Reais / Acao)". Multiplicar por mil transformava o R$ 1,44 da WEG em
# R$ 1.440,26.
#
# Medido no DRE consolidado de 2024: 889 linhas de **384 companhias**, com
# mediana de |valor| bruto em 1,31 e 99% abaixo de 1.000 -- a ordem de grandeza
# de reais por acao, nao de milhares deles. No ITR de 2025, 3.858 linhas de 388.
CODIGO_POR_ACAO = "3.99"


def e_conta_por_acao(codigo: str) -> bool:
    """A conta e cotada por acao, e nao na moeda escalada do arquivo?"""
    codigo = str(codigo or "")
    return codigo == CODIGO_POR_ACAO or codigo.startswith(CODIGO_POR_ACAO + ".")


def _fator_da_linha(codigo: str, escala, avisos: list[str]) -> float:
    """Multiplicador que leva ``VL_CONTA`` a reais, respeitando o por acao."""
    if e_conta_por_acao(codigo):
        return 1.0
    return _fator_escala(escala, avisos)


def _fator_escala(escala: str, avisos: list[str]) -> float:
    """Converte ``ESCALA_MOEDA`` no multiplicador que leva ``VL_CONTA`` a reais."""
    chave = unicodedata.normalize("NFKD", str(escala or "").strip().upper())
    chave = "".join(c for c in chave if not unicodedata.combining(c))
    if chave in FATORES_ESCALA:
        return FATORES_ESCALA[chave]
    aviso = (
        f"ESCALA_MOEDA desconhecida ('{escala}'); tratei os valores como unidades. "
        "Confira a ordem de grandeza antes de modelar."
    )
    if aviso not in avisos:
        avisos.append(aviso)
    return 1.0


def _filtrar_empresa(
    dados: pd.DataFrame, codigo_cvm: int, ordem: str = "ultimo"
) -> pd.DataFrame:
    """Linhas da companhia, num exercicio so e na versao mais recente.

    O filtro de ``ORDEM_EXERC`` e o que impede o ano do meio de entrar duas
    vezes quando se pede uma serie de varios anos (ver o cabecalho do modulo).

    ``ordem`` existe para o ITR: la o ``PENULTIMO`` **e** o dado que interessa,
    porque e o mesmo periodo do exercicio anterior -- a metade que falta para
    montar o ano movel. No DFP ele continua sendo lixo a descartar.
    """
    if dados is None or dados.empty:
        return pd.DataFrame()

    codigos = dados["CD_CVM"].map(lambda v: _so_digitos(v) or "0").astype(int)
    recorte = dados[codigos == codigo_cvm]
    if recorte.empty:
        return recorte

    ordens = recorte["ORDEM_EXERC"].map(lambda v: normalizar(v))
    recorte = recorte[ordens == normalizar(ordem)]
    if recorte.empty:
        return recorte

    # Uma companhia que reapresenta a DFP ganha VERSAO nova. Nos arquivos de 2024
    # a CVM ja publica so a ultima, mas quem depende disso quebra em silencio no
    # dia em que publicar as duas -- e somar duas versoes dobraria as contas.
    versoes = pd.to_numeric(recorte["VERSAO"], errors="coerce")
    if versoes.notna().any():
        recorte = recorte[versoes == versoes.max()]
    return recorte


def _cnpj_da_companhia(zip_path: Path, ano: int, codigo_cvm: int) -> str | None:
    """CNPJ a partir do codigo CVM, lido das proprias demonstracoes."""
    for escopo in ESCOPOS:
        dados = _ler_csv_do_zip(
            zip_path, _nome_no_zip("DRE", escopo, ano), codigo_cvm
        )
        if dados is not None and not dados.empty:
            return _texto(dados["CNPJ_CIA"].iloc[0])
    return None


def acoes_em_circulacao(zip_path: Path, ano: int, codigo_cvm: int) -> float | None:
    """Acoes emitidas menos as em tesouraria, do arquivo de composicao de capital.

    A CVM publica a quantidade junto da DFP, o que evita pedir ao usuario um
    numero que ele teria de procurar em outro lugar -- e que, digitado errado,
    erra o preco por acao sem errar o valor da empresa, que e o tipo de engano
    que passa despercebido numa revisao.

    Este arquivo e identificado por CNPJ e nao tem coluna CD_CVM, entao o
    recorte rapido em bytes -- que depende da posicao de CD_CVM na linha -- nao
    serve aqui. Ele tem uma linha por companhia, e pequeno o bastante para ler
    inteiro.
    """
    cnpj = _cnpj_da_companhia(zip_path, ano, codigo_cvm)
    if cnpj is None:
        return None

    nome = f"dfp_cia_aberta_composicao_capital_{ano}.csv"
    dados = _ler_csv_do_zip(zip_path, nome)
    if dados is None or dados.empty:
        return None
    dados = dados[dados["CNPJ_CIA"].map(_so_digitos) == _so_digitos(cnpj)]
    if dados.empty:
        return None

    versoes = pd.to_numeric(dados["VERSAO"], errors="coerce")
    if versoes.notna().any():
        dados = dados[versoes == versoes.max()]

    total = pd.to_numeric(dados["QT_ACAO_TOTAL_CAP_INTEGR"], errors="coerce").max()
    tesouraria = pd.to_numeric(dados["QT_ACAO_TOTAL_TESOURO"], errors="coerce").max()
    if not np.isfinite(total) or total <= 0:
        return None
    if not np.isfinite(tesouraria):
        tesouraria = 0.0
    return float(total - tesouraria)


def escopo_da_companhia(
    zip_path: Path, ano: int, codigo_cvm: int, documento: str = "dfp"
) -> str | None:
    """Consolidado ou individual, decidido uma vez para a companhia inteira.

    Escolher por demonstracao permitiria ler a DRE do grupo economico junto com
    a DFC da empresa isolada -- duas entidades diferentes na mesma tabela, sem
    nada indicando qual foi qual. Conferido nos arquivos de 2024: das 467
    companhias com consolidado, nenhuma deixa de publicar alguma demonstracao
    nesse escopo, entao travar aqui nao custa dado.

    **O escopo precisa ter numero, e nao so ter linha.** A regra era "existe
    alguma linha da companhia neste escopo", e ha companhia que entrega o
    consolidado com o plano de contas inteiro **zerado** -- linha existe, dado
    nao. O app lia zeros e montava uma companhia vazia, sem cair no individual,
    porque a queda so acontecia quando o consolidado faltava.

    A TIM S.A. e o caso que mostrou: a DFP consolidada dela e zero desde o
    exercicio de 2024 (era R$ 23.833,9 mi em 2023), enquanto a individual traz
    R$ 25.447,9 mi em 2024 e R$ 26.624,7 mi em 2025 -- e o ITR consolidado
    continua cheio. A demonstracao publicada pela companhia tem o consolidado;
    o que vem zerado e o extrato estruturado desse escopo.

    Medido nos arquivos: **2 companhias em 2024** (TIM S.A. e Rio Paranapanema)
    e **3 em 2025** (as duas mais CLI Sul) entregam consolidado todo zero tendo
    individual com dado.

    ``documento`` existe porque o ITR tem os proprios nomes de arquivo. Sem ele
    esta funcao montava nome de DFP dentro do zip trimestral, nao achava nada e
    devolvia ``None`` para **toda** companhia -- e os dois chamadores do ITR
    escreviam ``or ESCOPOS[0]``, entao o ITR inteiro era lido como consolidado
    na marra. Funcionava por coincidencia em quem publica consolidado, e so.
    """
    for escopo in ESCOPOS:
        if _escopo_tem_numero(zip_path, ano, codigo_cvm, escopo, documento):
            return escopo

    # Nenhum escopo tem numero: cai na regra antiga, "existe alguma linha".
    # Companhia que so publicou zeros em todo lugar continua sendo lida como
    # antes -- devolver ``None`` aqui a transformaria em "sem DFP", que e outra
    # afirmacao e nao a verdadeira.
    for escopo in ESCOPOS:
        if _escopo_existe(zip_path, ano, codigo_cvm, escopo, documento):
            return escopo
    return None


def _onde_fica_a_costura(anos_por_escopo: dict[str, list[int]]) -> str:
    """Quais anos vieram de cada escopo, quando a serie mistura os dois.

    Uma serie que troca de escopo no meio junta duas entidades numa tabela so, e
    "usei a individual em ao menos um dos anos" nao diz **onde**. Sem isso o
    analista nao consegue nem olhar o degrau: ele vira crescimento na leitura.

    Devolve texto vazio quando ha um escopo so -- ai nao ha costura, e a frase
    seria ruido.
    """
    if len(anos_por_escopo) < 2:
        return ""
    nomes = {"con": "consolidado", "ind": "individual"}
    partes = [
        f"**{nomes.get(escopo, escopo)}** em "
        + ", ".join(str(a) for a in sorted(anos))
        for escopo, anos in sorted(anos_por_escopo.items())
    ]
    return (
        " **A série mistura os dois escopos**: "
        + "; ".join(partes)
        + ". O degrau entre eles não é crescimento."
    )


def _escopo_existe(
    zip_path: Path, ano: int, codigo_cvm: int, escopo: str, documento: str = "dfp"
) -> bool:
    """A companhia publicou **alguma linha** neste escopo, com valor ou sem?

    E a pergunta antiga de ``escopo_da_companhia``, que agora sozinha nao basta
    para escolher -- mas continua sendo a que separa "o consolidado veio zerado"
    de "a companhia nao publica consolidado".
    """
    for grupos in GRUPOS.values():
        for grupo in grupos:
            dados = _ler_csv_do_zip(
                zip_path, _nome_no_zip(grupo, escopo, ano, documento), codigo_cvm
            )
            if dados is not None and not _filtrar_empresa(dados, codigo_cvm).empty:
                return True
    return False


def _escopo_tem_numero(
    zip_path: Path, ano: int, codigo_cvm: int, escopo: str, documento: str = "dfp"
) -> bool:
    """Ha ao menos um valor diferente de zero da companhia neste escopo?

    Sai no primeiro numero que encontra, entao no caso comum le um arquivo so --
    a DRE consolidada de quem tem receita responde na primeira linha.
    """
    for grupos in GRUPOS.values():
        for grupo in grupos:
            dados = _ler_csv_do_zip(
                zip_path, _nome_no_zip(grupo, escopo, ano, documento), codigo_cvm
            )
            recorte = _filtrar_empresa(dados, codigo_cvm)
            if recorte.empty:
                continue
            valores = pd.to_numeric(recorte["VL_CONTA"], errors="coerce")
            if bool((valores.fillna(0) != 0).any()):
                return True
    return False


def _linhas_da_demonstracao(
    zip_path: Path,
    ano: int,
    demonstracao: str,
    codigo_cvm: int,
    avisos: list[str],
    escopo: str,
) -> list[LinhaCVM]:
    """Le uma demonstracao do zip, no escopo ja decidido para a companhia."""
    coletadas: list[LinhaCVM] = []

    for grupo in GRUPOS[demonstracao]:
        dados = _ler_csv_do_zip(zip_path, _nome_no_zip(grupo, escopo, ano), codigo_cvm)
        recorte = _filtrar_empresa(dados, codigo_cvm)
        if recorte.empty:
            continue
        recorte = _sem_linhas_repetidas(recorte, demonstracao)
        if demonstracao in _DEMONSTRACOES_COM_COLUNA and "COLUNA_DF" in recorte.columns:
            # A mesma conta aparece uma vez por componente do patrimonio. Somar
            # devolve o movimento total, que e o que a arvore mostra; manter as
            # linhas separadas encheria a arvore de repeticoes do mesmo codigo.
            recorte = recorte.assign(
                VL_CONTA=pd.to_numeric(recorte["VL_CONTA"], errors="coerce")
            )
            recorte = (
                recorte.groupby(
                    ["CD_CONTA", "DS_CONTA", "DT_FIM_EXERC", "ESCALA_MOEDA"],
                    as_index=False,
                )["VL_CONTA"]
                .sum()
            )
        for _, linha in recorte.iterrows():
            valor = pd.to_numeric(linha.get("VL_CONTA"), errors="coerce")
            if not np.isfinite(valor):
                continue
            fim = _texto(linha.get("DT_FIM_EXERC"))
            # O exercicio social nem sempre fecha em 31/12 -- Raizen e Sao
            # Martinho fecham em marco, Camil em fevereiro. O ano do valuation
            # e o do encerramento, nao o do nome do arquivo.
            ano_exercicio = int(fim[:4]) if fim[:4].isdigit() else ano
            coletadas.append(
                LinhaCVM(
                    codigo=_texto(linha.get("CD_CONTA")),
                    descricao=_texto(linha.get("DS_CONTA")),
                    valor=float(valor)
                    * _fator_da_linha(
                        linha.get("CD_CONTA"), linha.get("ESCALA_MOEDA"), avisos
                    ),
                    ano=ano_exercicio,
                    demonstracao=demonstracao,
                    escala=_texto(linha.get("ESCALA_MOEDA")),
                    escopo=escopo,
                    grupo=grupo,
                )
            )

    return coletadas


# ---------------------------------------------------------------------------
# Longo -> colunas por ano
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Contas somadas: reconstruidas pela estrutura, nao pelo rotulo
# ---------------------------------------------------------------------------

# Tres contas que o analista pede sempre -- capex, juros pagos e dividendos
# pagos -- nao existem como linha unica na DFC. A CVM padroniza so os totais de
# secao (6.01, 6.02, 6.03, 100% de cobertura); tudo abaixo e conta livre, com
# codigo e nome a criterio da companhia. Entao cada uma chega partida em varias
# rubricas ("Aquisicao de imobilizado" + "Aquisicao de intangivel", "Juros
# pagos sobre emprestimos" + "Juros pagos sobre arrendamentos"), e a disputa por
# confianca que resolve o resto do vocabulario aqui escolheria uma e jogaria o
# resto fora, subestimando o numero.
#
# O que separa uma da outra nao e o assunto, e a **direcao**: "Dividendos
# recebidos" aparece em 80 companhias e nao e dividendo pago; venda de
# imobilizado fala de imobilizado e nao e capex. Por isso cada regra declara o
# que exclui, e nao so o que inclui.


@dataclass(frozen=True)
class RegraSomada:
    """Uma conta canonica montada somando varias linhas da DFC."""

    chave: str
    inclui: re.Pattern
    exclui: re.Pattern
    confirma: re.Pattern
    prefixo: str = ""
    secao_dispensa_verbo: str = ""
    rotulo_curto_basta: bool = False

    def casa(self, linha: LinhaCVM) -> bool:
        if linha.demonstracao != "dfc":
            return False
        codigo = linha.codigo
        if self.prefixo and not codigo.startswith(self.prefixo):
            return False
        # O total da secao nao e a conta: e a soma dela com todo o resto.
        if codigo in {self.prefixo.rstrip("."), self.secao_dispensa_verbo}:
            return False
        texto = linha.descricao
        if not self.inclui.search(texto) or self.exclui.search(texto):
            return False
        if self.confirma.search(texto):
            return True
        # Na secao de financiamento, a linha ja e movimento de caixa: "Juros
        # sobre emprestimos" ali e juro pago, mesmo sem o verbo.
        if self.secao_dispensa_verbo and codigo.startswith(self.secao_dispensa_verbo):
            return True
        # "Imobilizado" e "Intangivel" sozinhos, sem verbo, sao capex na secao de
        # investimento -- e como a WEG e boa parte das companhias rotulam.
        return self.rotulo_curto_basta and len(texto.split()) <= 3


# O plano da CVM reserva 2.01.04.03 e 2.02.01.03 para "Financiamento por
# Arrendamento", dentro da subarvore de emprestimos. Boa parte das companhias
# nao usa esse lugar: coloca o passivo de arrendamento do IFRS 16 em "Outras
# Obrigacoes" (2.01.05, 2.02.02), que fica **fora** da divida.
#
# Medido na DFP consolidada de 2024: 190 das 467 companhias fazem isso, num
# total de R$ 194,9 bilhoes. Em TIM sao 62,6% do que deveria ser a divida bruta;
# em Claro, 55,8%; na GOL, R$ 13,2 bilhoes. Ler so o codigo fixo devolve divida
# menor do que a real, e divida menor vira equity value maior -- em silencio,
# porque a arvore publicada continua fechando.
_MARCA_ARRENDAMENTO = re.compile(r"arrendament|direito de uso|leasing", re.I)
_SUBARVORE_DA_DIVIDA = ("2.01.04", "2.02.01")


def arrendamento_no_passivo(linhas: list[LinhaCVM]) -> dict[str, dict[int, float]]:
    """Todo o passivo de arrendamento, separado por prazo e por onde foi parar.

    Devolve quatro series::

        {"curto": ..., "longo": ..., "curto_fora": ..., "longo_fora": ...}

    As duas primeiras sao o arrendamento **total**; as duas ultimas, a parte que
    ficou fora da subarvore de emprestimos e que por isso precisa ser devolvida
    a divida bruta.

    So entram as linhas **mais externas** que casam: quando a companhia abre
    "Arrendamentos" e, abaixo, "Arrendamentos a pagar", somar as duas contaria o
    mesmo passivo duas vezes. Esta funcao e a **unica** fonte do arrendamento no
    balanco, e e assim de proposito: o reconhecimento por rotulo tambem alcanca
    algumas dessas linhas, e duas fontes somando na mesma conta e a receita para
    contar o passivo em dobro sem que nada acuse.
    """
    candidatas = [
        linha
        for linha in linhas
        if linha.demonstracao == "bp"
        and linha.codigo.startswith(("2.01", "2.02"))
        and _MARCA_ARRENDAMENTO.search(linha.descricao)
        and linha.valor
    ]

    series: dict[str, dict[int, float]] = {
        "curto": {}, "longo": {}, "curto_fora": {}, "longo_fora": {}
    }
    por_ano: dict[int, list[LinhaCVM]] = {}
    for linha in candidatas:
        por_ano.setdefault(linha.ano, []).append(linha)

    for ano, do_ano in por_ano.items():
        codigos = {linha.codigo for linha in do_ano}
        for linha in do_ano:
            tem_pai = any(
                linha.codigo != outro and linha.codigo.startswith(outro + ".")
                for outro in codigos
            )
            if tem_pai:
                continue
            prazo = "curto" if linha.codigo.startswith("2.01") else "longo"
            series[prazo][ano] = series[prazo].get(ano, 0.0) + linha.valor
            if not linha.codigo.startswith(_SUBARVORE_DA_DIVIDA):
                chave = f"{prazo}_fora"
                series[chave][ano] = series[chave].get(ano, 0.0) + linha.valor
    return series


_DA_NO_ROTULO = re.compile(r"deprecia|amortiza", re.IGNORECASE)

# A subarvore que alimenta `itens_nao_recorrentes`: impairment, outras receitas
# e outras despesas operacionais.
_BLOCOS_NAO_RECORRENTES = ("3.04.03.", "3.04.04.", "3.04.05.")


def _avisar_da_dentro_do_nao_recorrente(
    linhas: list[LinhaCVM], avisos: list[str]
) -> None:
    """A companhia lancou depreciacao ou amortizacao em "outras despesas"?

    `itens_nao_recorrentes` e ``3.04.03 + 3.04.04 + 3.04.05`` com o sinal
    publicado, e a **margem EBITDA recorrente e a base que `sugerir_premissas`
    projeta**. Amortizacao de intangivel e a coisa mais recorrente que existe:
    onde a companhia a lanca nesse bloco, a margem recorrente sai inflada e a
    projecao parte dela.

    Medido no DFP consolidado de 2024: **43 linhas em 41 companhias**, e nao sao
    pequenas -- Companhia Brasileira de Distribuicao com R$ 1.045,0 mi (239,7%
    do EBIT), Casas Bahia com R$ 864,0 mi (169,4%), Marisa com R$ 166,4 mi
    (382,2%) e Allpark com R$ 164,3 mi (77,9%).

    **O app avisa e nao corrige**, e a escolha e deliberada: excluir a linha do
    ajuste mudaria a base de projecao de 41 companhias em silencio, e ha caso
    legitimamente discutivel no meio -- amortizacao de mais-valia de combinacao
    de negocios e excluida por muito analista. Quem decide precisa do numero, e
    e o numero que este aviso entrega.
    """
    achadas = [
        linha
        for linha in linhas
        if linha.demonstracao == "dre"
        and any(linha.codigo.startswith(b) for b in _BLOCOS_NAO_RECORRENTES)
        and _DA_NO_ROTULO.search(linha.descricao)
    ]
    if not achadas:
        return

    total = sum(abs(linha.valor) for linha in achadas)
    # Milhar com ponto e decimal com virgula: o aviso e lido em portugues.
    em_milhoes = f"{total / 1e6:,.1f}".replace(",", "@").replace(".", ",").replace("@", ".")
    quais = ", ".join(
        f"{linha.descricao.strip()} ({linha.codigo})" for linha in achadas[:3]
    )
    avisos.append(
        "**Esta companhia lança depreciação ou amortização dentro de "
        "\"outras receitas/despesas operacionais\"** — o bloco que o app trata "
        f"como **itens não recorrentes**. São {len(achadas)} linha(s), somando "
        f"{em_milhoes} milhões: {quais}. "
        "Amortização de intangível é recorrente, então a **margem recorrente "
        "sai inflada** — e ela é a base que a sugestão de premissas projeta. "
        "Não corrigi: excluí-la seria decidir por você, e amortização de "
        "mais-valia é caso discutível. Medido na base de 2024, são 43 linhas em "
        "41 companhias."
    )


def _somar_arrendamento_fora_da_divida(
    linhas: list[LinhaCVM],
    tabela: dict[str, dict[int, float]],
    mapeamento: dict[str, str],
    avisos: list[str],
) -> None:
    """Devolve a divida bruta o arrendamento que ficou fora dela.

    Entra na divida **e** na conta de arrendamento, porque as duas leituras
    precisam do mesmo numero: a ponte EV -> equity subtrai a divida, e o
    indicador de arrendamento sobre divida diz quanto dela e aluguel.
    """
    series = arrendamento_no_passivo(linhas)

    # O arrendamento e **substituido**, nao somado: esta e a fonte unica. E
    # quando esta leitura encontra alguma linha, ela passa a mandar nas duas
    # contas -- inclusive para **apagar** a que nao tem valor. Sem isso, a
    # companhia que so publica arrendamento longo ficava com o reconhecimento
    # por rotulo enchendo a conta de curto prazo com o numero do longo: a
    # auditoria achou dois casos assim em 2023, e nenhuma identidade os pegaria.
    encontrou = any(series[prazo] for prazo in ("curto", "longo"))
    for prazo, chave in (
        ("curto", "arrendamento_curto_prazo"),
        ("longo", "arrendamento_longo_prazo"),
    ):
        if series[prazo]:
            tabela[chave] = dict(series[prazo])
            mapeamento[chave] = "linhas de arrendamento do balanço"
        elif encontrou:
            tabela.pop(chave, None)
            mapeamento.pop(chave, None)

    # A divida, ao contrario, **recebe** o que estava fora dela: o que ja estava
    # dentro entrou por 2.01.04 / 2.02.01 e nao pode entrar de novo.
    fora = {"curto": series["curto_fora"], "longo": series["longo_fora"]}
    if not fora["curto"] and not fora["longo"]:
        return

    destinos = {"curto": "divida_curto_prazo", "longo": "divida_longo_prazo"}
    for prazo, valores in fora.items():
        if not valores:
            continue
        chave = destinos[prazo]
        alvo = tabela.setdefault(chave, {})
        for ano, valor in valores.items():
            alvo[ano] = alvo.get(ano, 0.0) + valor
        nota = "+ arrendamento reportado fora da divida"
        if nota not in mapeamento.get(chave, ""):
            mapeamento[chave] = f"{mapeamento.get(chave, '')} {nota}".strip()

    avisos.append(
        "Esta companhia reporta parte do passivo de arrendamento fora da subárvore "
        "de empréstimos (2.01.04 / 2.02.01). Somei essas linhas à dívida bruta e ao "
        "arrendamento — sem isso a dívida sairia menor do que é, e o equity value, "
        "maior. Confira na árvore publicada."
    )


# O que a companhia desembolsou de arrendamento no ano. Depois do IFRS 16 o
# aluguel sumiu da DRE -- virou depreciacao de direito de uso mais juros --, e o
# unico lugar onde ele reaparece como caixa e a DFC.
#
# Medido na DFP consolidada de 2024, sobre 467 companhias: 258 (55%) publicam o
# principal, 184 (39%) publicam os juros em linha propria, e so 46 (10%) abrem a
# depreciacao do direito de uso. A depreciacao e esparsa demais para sustentar
# conta nenhuma; o desembolso, nao.
#
# Estas contas **nao entram** em REGRAS_SOMADAS de proposito. La cada linha
# alimenta uma regra so, e o juro de arrendamento precisa continuar contando
# para ``juros_pagos`` -- ele e juro. Aqui ele e lido de novo, para outro fim.
_MARCA_PRINCIPAL_ARRENDAMENTO = re.compile(
    r"(pagament|amortiza|liquida|desembols|quita)", re.I
)
_MARCA_JUROS_ARRENDAMENTO = re.compile(r"juro", re.I)
# Linhas que falam de arrendamento sem ser desembolso do arrendatario.
_NAO_E_DESEMBOLSO_DE_ARRENDAMENTO = re.compile(
    r"receb|a receber|aliena|venda|baixa|subarrend|sublocac|adi[çc][ãa]o|novo|"
    r"deprecia|amortiza[çc][ãa]o d[eo] direito|valor residual",
    re.I,
)


def arrendamento_no_caixa(linhas: list[LinhaCVM]) -> dict[str, dict[int, float]]:
    """Principal e juros de arrendamento desembolsados, lidos da DFC.

    Juntos, os dois aproximam o **aluguel** que existia antes do IFRS 16 -- e e
    dele que precisa quem quer olhar EBITDA e margem em base comparavel com o
    historico anterior a 2019 ou com par que reporta em US GAAP.

    Devolve valores positivos: sao saidas, e o modulo trata saida como
    magnitude, como faz com custo e imposto.
    """
    componentes: dict[str, dict[int, float]] = {"principal": {}, "juros": {}}
    for linha in linhas:
        if linha.demonstracao != "dfc":
            continue
        texto = linha.descricao
        if not _MARCA_ARRENDAMENTO.search(texto):
            continue
        if _NAO_E_DESEMBOLSO_DE_ARRENDAMENTO.search(texto):
            continue

        if _MARCA_JUROS_ARRENDAMENTO.search(texto):
            chave = "juros"
        elif _MARCA_PRINCIPAL_ARRENDAMENTO.search(texto) and linha.codigo.startswith("6.03"):
            # So na secao de financiamento: "pagamento" na secao operacional
            # costuma ser reclassificacao, nao desembolso de contrato.
            chave = "principal"
        else:
            continue

        valores = componentes[chave]
        valores[linha.ano] = valores.get(linha.ano, 0.0) + abs(linha.valor)
    return componentes


def _somar_arrendamento_no_caixa(
    linhas: list[LinhaCVM], tabela: dict[str, dict[int, float]], mapeamento: dict[str, str]
) -> None:
    componentes = arrendamento_no_caixa(linhas)
    destinos = {
        "principal": "arrendamento_principal_pago",
        "juros": "arrendamento_juros_pagos",
    }
    for chave, valores in componentes.items():
        if not valores:
            continue
        tabela[destinos[chave]] = valores
        mapeamento[destinos[chave]] = "linhas de arrendamento da DFC"


_MARCA_JUROS_PAGOS = re.compile(r"juros", re.I)

# O que **parece** juro pago e nao e. Cada item saiu de uma linha real da base:
#
# * ``exceto juros`` -- "Pagamento de emprestimos e arrendamentos (exceto
#   juros)" e amortizacao de principal. Contava R$ 2,2 bi na Porto Seguro e
#   R$ 2,7 bi na Ambev como se fosse juro.
# * ``principal e juros`` -- linha que mistura os dois nao da para separar, e
#   conta-la inteira infla o Kd. Sao 18 linhas e R$ 21,5 bi na base, com
#   R$ 12,4 bi so na Motiva.
# * JCP com grafia variante -- "Juros sobre capital prorio" (sem o segundo p)
#   escapava do padrao antigo. Agora o casamento e por "juros sobre ... capital"
#   e nao pela grafia de "proprio" -- de proposito, para nao excluir "Juros de
#   instrumento elegivel a capital principal", que e juro de verdade.
_NAO_E_JURO_PAGO = re.compile(
    r"recebid|exceto juros|sem juros|excluindo juros|"
    r"principal e juros|juros e principal|"
    r"juros sobre.{0,8}capital|capital pr[óo]prio|\bjcp\b|"
    r"receita|capitaliz|a pagar|n[aã]o realizad|provis[aã]o",
    re.I,
)


REGRAS_SOMADAS: tuple[RegraSomada, ...] = (
    RegraSomada(
        chave="capex",
        prefixo="6.02.",
        inclui=re.compile(r"imobiliz|intang[ií]|ativo fixo|capex|permanente", re.I),
        exclui=re.compile(
            r"venda|aliena|baixa|recebiment|resgate|receb\.|desinvestiment|"
            # Aporte em controlada nao e capex: e investimento em participacao,
            # que sai do capital operacional em vez de repor ativo fixo.
            r"aumento de capital|futuro aumento",
            re.I,
        ),
        confirma=re.compile(
            r"aquisi|adi[cç][aã]o|adi[cç][oõ]es|compra|dispêndio|desembolso|"
            # "Aplicacoes no ativo imobilizado" e "Acrescimo de imobilizado" sao
            # como boa parte das companhias rotulam o mesmo desembolso.
            r"investiment|aplica[cç]|acr[eé]scim|^no\s|^em\s",
            re.I,
        ),
        rotulo_curto_basta=True,
    ),
    RegraSomada(
        # D&A somada, e nao escolhida. Auditada a base de 2024, a leitura por
        # rotulo deixava **R$ 121 bilhoes de fora em 106 companhias** -- a cauda
        # de rotulos e longa ("Depreciacoes, amortizacoes e desvalorizacoes",
        # "Amortizacao e Depreciacao", "Depreciacao/Amortizacao") e listar
        # sinonimo a sinonimo nao termina. E onde a companhia abria a linha em
        # duas ou tres, a disputa por confianca ficava com uma so e jogava o
        # resto fora: mais R$ 4 bilhoes, em 127 companhias.
        #
        # A secao 6.01.01 e a dos ajustes ao lucro; linha que fala de
        # depreciacao ali **e** depreciacao, sem precisar de verbo.
        chave="depreciacao_dfc",
        prefixo="6.01.01.",
        inclui=re.compile(r"deprecia|amortiza|exaust|deple", re.I),
        # Amortizacao de custo de captacao e despesa financeira diferida, nao
        # D&A de ativo fixo -- somada aqui, inflaria o EBITDA.
        exclui=re.compile(
            r"custo de transa|capta[cç][aã]o|deb[êe]ntur|empr[ée]stim|financiament|"
            r"[áa]gio na|mais.valia na",
            re.I,
        ),
        confirma=re.compile(r"deprecia|amortiza|exaust", re.I),
        secao_dispensa_verbo="6.01.01",
    ),
    RegraSomada(
        chave="juros_pagos",
        inclui=_MARCA_JUROS_PAGOS,
        # Mesmo padrao que a reclassificacao usa, e de proposito: as duas
        # leituras do juro pago precisam concordar sobre o que e juro.
        exclui=_NAO_E_JURO_PAGO,
        confirma=re.compile(r"pag|liquida[cç]", re.I),
        secao_dispensa_verbo="6.03",
    ),
    RegraSomada(
        chave="dividendos_pagos",
        inclui=re.compile(r"dividendo|capital pr[óo]prio|\bjcp\b", re.I),
        exclui=re.compile(r"recebid|a receber|a pagar|receita|declarad", re.I),
        confirma=re.compile(r"pag|distribu", re.I),
        # Na secao de financiamento, "Dividendos" sem verbo e saida de caixa: o
        # dividendo recebido entra em investimento, e o exclui ja o barra.
        secao_dispensa_verbo="6.03",
    ),
)


def _e_capex(linha: LinhaCVM) -> bool:
    """A linha e desembolso de capital sob a secao de investimento da DFC?"""
    return REGRAS_SOMADAS[0].casa(linha)


# ---------------------------------------------------------------------------
# Qual plano de contas a companhia usa
# ---------------------------------------------------------------------------

PLANO_INDUSTRIAL = "industrial"
PLANO_FINANCEIRO = "financeiro"

# A CVM publica planos de contas diferentes para industria, bancos e
# seguradoras, e o mesmo codigo muda de significado entre eles. Em 2024, 3.06 e
# "Resultado Financeiro" em 450 companhias e "Imposto de Renda e Contribuicao
# Social" em 17; 3.08 e "IR e CSLL" nas primeiras e "Resultado Liquido das
# Operacoes Descontinuadas" nas segundas. Ler o codigo sem saber o plano poe o
# numero errado na conta certa, calado.
#
# A escolha do plano e da companhia, nao da linha: basta identifica-lo uma vez.
# O topo da DRE e a assinatura mais confiavel para isso.
_MARCA_FINANCEIRA = re.compile(
    r"intermedia[cç][aã]o financeira|atividades? seguradora|resseguradora", re.I
)
_CODIGOS_ASSINATURA = ("3.01", "3.02", "3.03")


def detectar_plano(linhas: list[LinhaCVM]) -> str:
    """Descobre se a companhia publica no plano industrial ou no financeiro."""
    for linha in linhas:
        if linha.demonstracao == "dre" and linha.codigo in _CODIGOS_ASSINATURA:
            if _MARCA_FINANCEIRA.search(linha.descricao):
                return PLANO_FINANCEIRO
    return PLANO_INDUSTRIAL


# Na DFC pelo **metodo direto** os codigos de 6.01 significam outra coisa. E o
# mesmo problema do plano financeiro, num lugar em que ninguem espera: a CVM
# publica os dois metodos em arquivos separados (``DFC_MI`` e ``DFC_MD``) e o
# app le os dois no mesmo grupo, mas so a numeracao do indireto foi mapeada.
#
#   indireto  6.01.01  Caixa Gerado pelas Operacoes
#             6.01.02  Variacoes nos Ativos e Passivos
#             6.01.03  Outros
#
#   direto    6.01.01  Recebimento de Consumidores
#             6.01.02  Fornecedores - Materiais e Servicos
#             6.01.03  Fornecedores - Energia Eletrica
#
# Sao 16 das 467 companhias de 2024, e nelas o app punha "recebimento de
# consumidores" em ``caixa_das_operacoes`` e "fornecedores" em
# ``variacao_capital_giro``. **As 5 unicas companhias em que a decomposicao do
# FCO nao fechava eram todas do metodo direto** -- a auditoria estava apontando
# para isto sem que ninguem tivesse ligado a causa.
# O texto do aviso, num lugar so: a deteccao de troca de metodo no ano
# movel procura por ele, e duas grafias divergiriam em silencio.
MARCA_METODO_DIRETO = "metodo direto"

_MARCA_METODO_DIRETO = re.compile(
    r"recebimento[s]? de (consumidor|client)|recebido[s]? de (consumidor|client)",
    re.I,
)


def detectar_metodo_da_dfc(linhas: list[LinhaCVM]) -> str:
    """``direto`` ou ``indireto``, pelo arquivo em que a companhia declarou.

    Vem do arquivo e nao do rotulo porque o rotulo nao separa: das 16 companhias
    de 2024 que publicam pelo metodo direto, **so 9 abrem com "Recebimento de
    Consumidores"**; as outras usam rotulo proprio, e uma regra por nome as
    perderia. O arquivo (``DFC_MD`` contra ``DFC_MI``) e a declaracao da propria
    companhia, e nao admite duvida.

    O rotulo entra so como rede para origens que nao sao o zip da CVM -- uma
    planilha importada nao tem arquivo de origem para consultar. **Onde ha
    arquivo, ele decide sozinho**, e a rede nao roda: ela estava sobrepondo a
    declaracao da companhia e errando.

    Medido em 2024, tres companhias publicam so no ``DFC_MI`` -- ou seja,
    declararam metodo indireto -- e tinham uma linha de giro que o padrao lia
    como recebimento de clientes:

    ======================  ==========================================
    Americanas              "Adiantamentos recebidos de clientes"
    Vamos Locacao           "Juros recebidos de clientes"
    Bioma Educacao          "Perdas nos recebimentos de clientes"
    ======================  ==========================================

    Nas tres o app anunciava "publica pela DFC direta" -- falso -- e descartava
    as quatro contas de ``_SO_NO_METODO_INDIRETO``, entre elas a D&A: R$ 1.010,0
    mi na Americanas e R$ 750,6 mi na Vamos, que estavam no arquivo e nao eram
    lidas. Sem D&A o EBITDA delas era o proprio EBIT.
    """
    do_arquivo = [
        linha
        for linha in linhas
        if linha.demonstracao == "dfc" and linha.grupo in ("DFC_MI", "DFC_MD")
    ]
    if do_arquivo:
        return (
            "direto"
            if any(linha.grupo == "DFC_MD" for linha in do_arquivo)
            else "indireto"
        )

    for linha in linhas:
        if linha.demonstracao != "dfc":
            continue
        if linha.codigo.startswith("6.01.") and _MARCA_METODO_DIRETO.search(
            linha.descricao
        ):
            return "direto"
    return "indireto"


# Contas que so existem no metodo indireto. Elas descrevem a **reconciliacao**
# do lucro com o caixa, e a DFC direta nao reconcilia nada: ela lista os
# recebimentos e os pagamentos. Nao ha equivalente, e inventar um seria pior que
# a ausencia -- e a mesma decisao tomada para bancos.
_SO_NO_METODO_INDIRETO = (
    "caixa_das_operacoes",
    "variacao_capital_giro",
    "outros_operacionais",
    "depreciacao_dfc",
)


# O plano financeiro nao e uma variacao do industrial: e outra numeracao. 2.07 e
# patrimonio liquido, e nao 2.03; 1.01 e caixa, e nao ativo circulante; 3.06 e o
# imposto, e nao o resultado financeiro. Por isso o mapa e proprio, e nao um
# conjunto de excecoes sobre o outro.
#
# Medido nas 19 companhias de 2024 que usam este plano. So o que tem significado
# equivalente no vocabulario canonico entra: um banco nao tem EBIT nem capital de
# giro operacional, e inventar equivalencia para eles seria pior que a ausencia.
CODIGOS_PLANO_FINANCEIRO: dict[str, str] = {
    "1": "ativo_total",
    "1.01": "caixa_equivalentes",
    "1.02": "aplicacoes_financeiras",
    "1.05": "investimentos",
    "1.06": "imobilizado",
    "1.07": "intangivel",
    "2": "passivo_total",
    "2.07": "patrimonio_liquido",
    "3.01": "receita_liquida",
    "3.02": "custo_produtos_vendidos",
    "3.03": "lucro_bruto",
    "3.05": "lucro_antes_impostos",
    "3.06": "impostos",
    "3.11": "lucro_liquido",
}


def _reconhecer_na_demonstracao(
    linha: LinhaCVM,
    plano: str = PLANO_INDUSTRIAL,
    metodo_dfc: str = "indireto",
):
    """Reconhece a conta canonica de uma linha da CVM.

    **A demonstracao de origem limita as contas possiveis.** A DFC da WEG tem
    uma linha chamada apenas ``Imobilizado`` (o capex), e o vocabulario tem
    ``imobilizado`` como sinonimo exato da conta de balanco. Sem a restricao, um
    numero de fluxo de caixa entra no lugar de um saldo patrimonial.

    **O codigo so vale no plano em que foi escrito.** Os codigos do vocabulario
    descrevem o plano industrial; num banco eles apontam para outra coisa. Fora
    do plano industrial, o reconhecimento passa a ser so pelo rotulo -- que
    acerta menos, mas erra de forma visivel, deixando a linha na lista de nao
    reconhecidas em vez de preencher a conta com o numero de outra.
    """
    # No metodo direto os codigos de 6.01 nomeiam recebimentos e pagamentos, e
    # nao a reconciliacao do lucro. Reconhecer por rotulo ali erra de forma
    # visivel -- a linha sobra como nao reconhecida --, enquanto reconhecer por
    # codigo erra calado, pondo "Recebimento de Consumidores" em
    # ``caixa_das_operacoes``.
    codigo_vale = not (
        metodo_dfc == "direto"
        and linha.demonstracao == "dfc"
        and linha.codigo.startswith("6.01.")
    )

    if plano == PLANO_INDUSTRIAL:
        resultado = reconhecer(
            linha.descricao, linha.codigo if codigo_vale else None, linha.demonstracao
        )
    elif linha.codigo in CODIGOS_PLANO_FINANCEIRO:
        from .esquema import Reconhecimento

        # **O plano financeiro tambem nao e um so.** Ha ao menos dois layouts:
        # num deles ``2.07`` e o patrimonio liquido, no outro -- o de Itau, BTG e
        # Pine, com passivos abertos por criterio de mensuracao IFRS 9 -- ``2.07``
        # e "Passivos sobre Ativos Nao Correntes a Venda" e o patrimonio esta em
        # ``2.08``. Confiar so no codigo punha **zero** no patrimonio liquido do
        # maior banco do pais, calado.
        #
        # Entao o codigo vale, mas o rotulo tem **direito de veto**: quando ele
        # reconhece outra conta, e o rotulo que ganha. Codigo e convencao de
        # arquivo; rotulo e o que a companhia diz que a linha e.
        chave = CODIGOS_PLANO_FINANCEIRO[linha.codigo]
        por_rotulo = reconhecer(linha.descricao, None, linha.demonstracao)
        if por_rotulo.chave == chave:
            resultado = Reconhecimento(
                chave, 1.0, f"codigo {linha.codigo} do plano financeiro"
            )
        else:
            # O codigo **so vale com o aval do rotulo**. Medido nas 20
            # companhias do plano em 2024: ``2.07`` e "Patrimonio Liquido
            # Consolidado" em 10 delas e "Passivos sobre Ativos Nao Correntes a
            # Venda" nas outras 7 -- estas ultimas poem o patrimonio em
            # ``2.08``. Sem o aval, o app punha **zero** no patrimonio liquido
            # do Itau, do BTG e do Pine, e nenhuma identidade denunciava.
            #
            # Quando o rotulo diz outra coisa, ele ganha; quando nao diz nada, a
            # linha fica sem conta, que e o erro visivel -- ela aparece na lista
            # de nao reconhecidas em vez de preencher a conta errada calada.
            resultado = por_rotulo
    else:
        resultado = reconhecer(linha.descricao, None, linha.demonstracao)

    if resultado.chave is None:
        return resultado
    if POR_CHAVE[resultado.chave].demonstracao != linha.demonstracao:
        return type(resultado)(
            None, 0.0, f"'{resultado.chave}' nao pertence a {linha.demonstracao}"
        )
    if metodo_dfc == "direto" and resultado.chave in _SO_NO_METODO_INDIRETO:
        return type(resultado)(
            None, 0.0, f"'{resultado.chave}' nao existe na DFC pelo metodo direto"
        )
    return resultado


def _ordem_do_codigo(codigo: str) -> tuple[int, ...]:
    """Chave que ordena codigo como hierarquia, e nao como texto.

    Em ordem alfabetica ``1.01.10`` vem antes de ``1.01.02``, o que embaralha a
    demonstracao justamente onde ela tem mais linhas.
    """
    partes = []
    for parte in str(codigo).split("."):
        partes.append(int(parte) if parte.isdigit() else 0)
    return tuple(partes)


def montar_detalhe(linhas: list[LinhaCVM]) -> pd.DataFrame:
    """A demonstracao publicada inteira, uma linha por conta, anos em colunas.

    Diferente do vocabulario canonico, aqui nada e escolhido: toda linha que a
    companhia publicou entra, com o nivel que o codigo declara. Quando a mesma
    conta aparece com grafias diferentes entre anos -- e aparece, "Receita
    Liquida" e "Receita liquida" no mesmo codigo --, vale a grafia mais recente,
    para nao duplicar a linha na tela.
    """
    if not linhas:
        return pd.DataFrame()

    por_codigo: dict[tuple[str, str], dict] = {}
    for linha in sorted(linhas, key=lambda l: l.ano):
        chave = (linha.demonstracao, linha.codigo)
        registro = por_codigo.setdefault(
            chave,
            {
                "codigo": linha.codigo,
                "demonstracao": linha.demonstracao,
                "nivel": linha.codigo.count(".") + 1,
                "ordem": _ordem_do_codigo(linha.codigo),
            },
        )
        # O rotulo do ano mais recente prevalece: a iteracao vai do mais antigo
        # para o mais novo e sobrescreve.
        registro["rotulo"] = linha.descricao
        registro[linha.ano] = linha.valor

    return pd.DataFrame(list(por_codigo.values()))


def montar_demonstracoes(
    linhas: list[LinhaCVM],
    empresa: str,
    origem: str,
    avisos: list[str] | None = None,
    fonte: dict | None = None,
) -> Demonstracoes:
    """Converte o formato longo da CVM em contas canonicas x anos.

    Reaproveita inteiro o reconhecimento de ``esquema.py`` e a padronizacao de
    sinais, as derivacoes e as conferencias de ``importador.py``: o que este
    modulo acrescenta e o pivo de longo para largo, nao um vocabulario novo.
    """
    avisos = list(avisos or [])
    tabela: dict[str, dict[int, float]] = {}
    mapeamento: dict[str, str] = {}
    confiancas: dict[tuple[str, int], float] = {}
    nao_reconhecidas: dict[str, LinhaNaoReconhecida] = {}

    rotulo_da_aba = {
        "dre": "DRE",
        "bp": "Balanço",
        "dfc": "DFC",
        "dva": "DVA",
        "dra": "Resultado abrangente",
        "dmpl": "Mutações do PL",
        "capital": "Capital",
    }

    plano = detectar_plano(linhas)
    if plano == PLANO_FINANCEIRO:
        avisos.append(
            "Esta companhia publica no plano de contas de instituicao financeira "
            "ou seguradora, em que os mesmos codigos significam outras contas. "
            "Reconheci as linhas apenas pelo nome, e o modelo de FCFF/WACC nao se "
            "aplica a bancos e seguradoras -- confira conta por conta antes de usar."
        )

    metodo_dfc = detectar_metodo_da_dfc(linhas)
    if metodo_dfc == "direto":
        avisos.append(
            f"Esta companhia publica a DFC pelo **{MARCA_METODO_DIRETO}**, em que os codigos "
            "de 6.01 nomeiam recebimentos e pagamentos em vez da reconciliacao do "
            "lucro: 6.01.01 e 'Recebimento de Consumidores' e nao 'Caixa Gerado "
            "pelas Operacoes'. Deixei em branco caixa gerado, variacao de capital "
            "de giro e D&A da DFC, que nao existem nessa forma -- o total do "
            "operacional, o investimento e o financiamento continuam validos."
        )

    # As contas somadas (ver REGRAS_SOMADAS) sao montadas antes, e as linhas que
    # as compoem ficam fora da disputa por confianca do resto do vocabulario.
    somadas: dict[str, dict[int, float]] = {}
    origens: dict[str, list[str]] = {}
    consumidas: set[int] = set()
    for indice, linha in enumerate(linhas):
        for regra in REGRAS_SOMADAS:
            if not regra.casa(linha):
                continue
            # A regra da D&A varre ``6.01.01.`` porque no metodo indireto aquela
            # e a secao de ajustes ao lucro. No direto, ``6.01.01`` e o
            # recebimento de clientes, e a mesma varredura pegaria linha de
            # recebimento com "amortizacao" no nome.
            if metodo_dfc == "direto" and regra.chave in _SO_NO_METODO_INDIRETO:
                continue
            valores = somadas.setdefault(regra.chave, {})
            valores[linha.ano] = valores.get(linha.ano, 0.0) + linha.valor
            etiqueta = f"{linha.codigo} - {linha.descricao}"
            partes = origens.setdefault(regra.chave, [])
            if etiqueta not in partes:
                partes.append(etiqueta)
            consumidas.add(indice)
            break

    for indice, linha in enumerate(linhas):
        if indice in consumidas:
            continue
        resultado = _reconhecer_na_demonstracao(linha, plano, metodo_dfc)
        if resultado.chave is None or resultado.confianca < CONFIANCA_MINIMA:
            # Uma conta filha nao esta "nao reconhecida": ela e a abertura de uma
            # conta que o app entende. 2.03.02 "Reservas de Capital" explica de
            # onde vem parte do 2.03; pedir que o usuario a mapeie a mao seria
            # pedir que ele reclassificasse o plano de contas da CVM. Elas ficam
            # na arvore, que e onde tem sentido. So sobra aqui o que nao tem pai
            # -- conta de primeiro nivel que o vocabulario nao alcanca.
            if "." not in linha.codigo:
                etiqueta = f"{linha.codigo} - {linha.descricao}"
                nao_reconhecidas.setdefault(
                    f"{linha.demonstracao}|{linha.codigo}",
                    LinhaNaoReconhecida(
                        rotulo=etiqueta,
                        aba=rotulo_da_aba[linha.demonstracao],
                        melhor_palpite=resultado.chave,
                        confianca=resultado.confianca,
                    ),
                )
            continue

        chave = resultado.chave
        # A disputa e por (conta, ano): dois anos da mesma conta nao competem
        # entre si, mas duas linhas do mesmo ano competem, e ganha a de codigo
        # exato sobre a que so casou por nome.
        anterior = confiancas.get((chave, linha.ano), -1.0)
        if resultado.confianca < anterior:
            continue
        confiancas[(chave, linha.ano)] = resultado.confianca
        tabela.setdefault(chave, {})[linha.ano] = linha.valor
        mapeamento[chave] = f"{linha.codigo} - {linha.descricao}"

    for chave, valores in somadas.items():
        tabela[chave] = valores
        mapeamento[chave] = " + ".join(origens[chave])

    _somar_arrendamento_fora_da_divida(linhas, tabela, mapeamento, avisos)
    _avisar_da_dentro_do_nao_recorrente(linhas, avisos)
    _somar_arrendamento_no_caixa(linhas, tabela, mapeamento)
    _padronizar_juros_no_fco(linhas, tabela, mapeamento, avisos)
    _reorganizar_o_fco(linhas, tabela, mapeamento, avisos)

    if not tabela:
        raise ErroCVM(
            "Nenhuma conta reconhecida nos arquivos da CVM para esta empresa. "
            "Confira se ela publicou DFP nos anos escolhidos."
        )

    # O sinal so pode ser padronizado com a serie inteira em maos: a regra olha
    # se a conta troca de sinal entre anos, e isso nao da para decidir linha a linha.
    for chave, valores in list(tabela.items()):
        ajustados, sinal_misto = _ajustar_sinal(POR_CHAVE[chave], valores)
        tabela[chave] = ajustados
        if sinal_misto:
            avisos.append(
                f"'{POR_CHAVE[chave].rotulo}' troca de sinal entre anos no arquivo "
                "da CVM; usei a magnitude em todos."
            )

    anos = sorted({ano for valores in tabela.values() for ano in valores})
    derivadas = _derivar(tabela, anos, mapeamento)

    ordem = [c.chave for c in CONTAS if c.chave in tabela]
    valores_df = pd.DataFrame(
        {ano: {chave: tabela[chave].get(ano, np.nan) for chave in ordem} for ano in anos},
        index=ordem,
        columns=anos,
    )

    from .esquema import CHAVES_OBRIGATORIAS

    faltando = [
        POR_CHAVE[chave].rotulo
        for chave in CHAVES_OBRIGATORIAS
        if chave not in valores_df.index or valores_df.loc[chave].isna().all()
    ]
    if faltando:
        avisos.append(
            "Contas obrigatorias nao encontradas: " + ", ".join(faltando) + ". "
            "Mapeie-as manualmente antes de modelar."
        )

    _conferir(valores_df, avisos)

    return Demonstracoes(
        empresa=empresa,
        valores=valores_df,
        origem=origem,
        unidade="R$",
        moeda="BRL",
        mapeamento=mapeamento,
        derivadas=derivadas,
        nao_reconhecidas=sorted(
            nao_reconhecidas.values(), key=lambda linha: linha.rotulo
        ),
        avisos=avisos,
        fonte=dict(fonte or {}),
        detalhe=montar_detalhe(linhas),
    )


ABAS = {"dre": "DRE", "bp": "Balanço", "dfc": "DFC"}


def escrever_planilha(linhas: list[LinhaCVM], destino: str | Path) -> Path:
    """Grava o que foi baixado como planilha larga, uma aba por demonstracao.

    Serve a dois propositos praticos. O usuario ganha um arquivo auditavel do
    que a CVM realmente publicou -- util para conferir a importacao linha a
    linha ou guardar junto do valuation. E a tela de conferencia ganha um
    arquivo em disco para reprocessar quando alguem corrige um mapeamento a
    mao, que e o mesmo caminho ja usado pelas outras origens.
    """
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    anos = sorted({linha.ano for linha in linhas})

    with pd.ExcelWriter(destino, engine="openpyxl") as escritor:
        for demonstracao, aba in ABAS.items():
            do_grupo = [linha for linha in linhas if linha.demonstracao == demonstracao]
            if not do_grupo:
                continue
            por_conta: dict[tuple[str, str], dict[int, float]] = {}
            for linha in do_grupo:
                por_conta.setdefault((linha.codigo, linha.descricao), {})[
                    linha.ano
                ] = linha.valor
            registros = [
                {
                    "Código": codigo,
                    # O rotulo repete o codigo porque e ele que a tela de
                    # conferencia mostra e depois procura de volta no arquivo.
                    "Conta": f"{codigo} - {descricao}",
                    **{ano: valores.get(ano) for ano in anos},
                }
                for (codigo, descricao), valores in sorted(por_conta.items())
            ]
            pd.DataFrame(registros).to_excel(escritor, sheet_name=aba, index=False)
    return destino


def importar_cvm(
    companhia: Companhia | int,
    anos: list[int] | range,
    cache: Path | None = None,
    catalogo: list[Companhia] | None = None,
    planilha: str | Path | None = None,
) -> Demonstracoes:
    """Baixa a DFP dos anos pedidos e devolve as demonstracoes canonicas.

    ``companhia`` pode ser um :class:`Companhia` ou o codigo CVM puro. Os
    valores saem em **reais**, ja corrigidos pela escala declarada em cada
    arquivo; a conversao para milhoes, se desejada, fica com
    :meth:`Demonstracoes.escalar`.

    ``planilha`` grava o que foi baixado no formato largo (ver
    :func:`escrever_planilha`), que e o que permite corrigir um mapeamento a
    mao depois.
    """
    registro: Companhia | None = None
    if isinstance(companhia, Companhia):
        registro = companhia
        codigo_cvm, nome = companhia.codigo_cvm, companhia.nome
    else:
        codigo_cvm = int(companhia)
        nome = str(companhia)
        for candidato in catalogo or []:
            if candidato.codigo_cvm == codigo_cvm:
                registro, nome = candidato, candidato.nome
                break

    anos = sorted({int(a) for a in anos})
    if not anos:
        raise ErroCVM("Escolha ao menos um ano.")

    linhas: list[LinhaCVM] = []
    avisos: list[str] = []
    anos_sem_dados: list[int] = []
    escalas: set[str] = set()
    escopos: set[str] = set()
    # O individual foi usado porque o consolidado veio **zerado**, e nao porque
    # ele faltava? Sao dois casos com explicacoes diferentes, e o aviso muda.
    consolidado_zerado = False
    # Qual escopo em qual ano. O escopo e decidido **por ano**, entao uma serie
    # pode misturar os dois -- e quem le precisa saber onde fica a costura, nao
    # so que ela existe.
    anos_por_escopo: dict[str, list[int]] = {}

    for ano in anos:
        zip_path = baixar_dfp(ano, cache=cache)
        # O escopo e decidido para a companhia inteira antes de ler qualquer
        # demonstracao, para que DRE, balanco e DFC descrevam a mesma entidade.
        escopo = escopo_da_companhia(zip_path, ano, codigo_cvm)
        if escopo is None:
            anos_sem_dados.append(ano)
            continue
        if escopo == "ind" and _escopo_existe(zip_path, ano, codigo_cvm, "con"):
            consolidado_zerado = True
        anos_por_escopo.setdefault(escopo, []).append(ano)
        do_ano: list[LinhaCVM] = []
        for demonstracao in GRUPOS:
            do_ano.extend(
                _linhas_da_demonstracao(
                    zip_path, ano, demonstracao, codigo_cvm, avisos, escopo
                )
            )
        if not do_ano:
            anos_sem_dados.append(ano)
            continue

        acoes = acoes_em_circulacao(zip_path, ano, codigo_cvm)
        if acoes:
            # A quantidade acompanha a escala dos valores para que equity
            # dividido por acoes de o preco por acao na unidade certa.
            do_ano.append(
                LinhaCVM(
                    # O rotulo casa com o sinonimo da conta canonica; a origem
                    # (emitidas menos tesouraria) fica documentada em
                    # ``acoes_em_circulacao``.
                    codigo="9.01",
                    descricao="Ações em circulação",
                    valor=acoes,
                    ano=max(l.ano for l in do_ano),
                    demonstracao="capital",
                    escala="UNIDADE",
                    escopo=escopo,
                )
            )
        linhas.extend(do_ano)
        # A quantidade de acoes nao e valor monetario: deixa-la entrar aqui
        # dispararia o aviso de escala trocada em toda companhia.
        escalas.update(
            linha.escala for linha in do_ano if linha.demonstracao != "capital"
        )
        escopos.update(linha.escopo for linha in do_ano)

    if not linhas:
        raise ErroCVM(
            f"A CVM nao tem DFP desta companhia (codigo {codigo_cvm}) em "
            f"{', '.join(str(a) for a in anos)}. Ela pode ter aberto capital depois, "
            "ter cancelado o registro ou publicar sob outro CNPJ do grupo."
        )

    if anos_sem_dados:
        avisos.append(
            "Sem DFP publicada em " + ", ".join(str(a) for a in anos_sem_dados) + "."
        )
    if "ind" in escopos and consolidado_zerado:
        avisos.append(
            "**O consolidado desta companhia vem zerado no arquivo da CVM**, com "
            "o plano de contas inteiro em zero, então usei a **individual**. A "
            "demonstração publicada pela companhia tem o consolidado — o que "
            "vem vazio é o extrato estruturado desse escopo. Medido nos "
            "arquivos: 2 companhias em 2024 e 3 em 2025, entre elas a TIM S.A., "
            "cuja consolidada é zero desde o exercício de 2024 e cuja individual "
            "traz R$ 25,4 bi de receita. Confira contra a DFP no portal antes de "
            "usar." + _onde_fica_a_costura(anos_por_escopo)
        )
    elif "ind" in escopos:
        avisos.append(
            "Esta companhia não publica demonstração consolidada em ao menos um "
            "dos anos; usei a **individual**, e ela costuma ser outra entidade. "
            "Medido nas 462 companhias que publicam os dois escopos em 2024: a "
            "receita individual é **0,40x a consolidada na mediana**, fica abaixo "
            "de 10% dela em 173 companhias e é **zero** em boa parte — na WEG a "
            "individual não tem receita nenhuma, e o lucro de R$ 6,0 bi vem todo "
            "de equivalência patrimonial. Margem, giro e capex sobre receita não "
            "querem dizer nada nesse caso." + _onde_fica_a_costura(anos_por_escopo)
        )
    if len(escalas) > 1:
        avisos.append(
            "A escala mudou entre os anos (" + ", ".join(sorted(escalas)) + "). "
            "Converti tudo para reais, entao a serie esta comparavel."
        )

    if planilha is not None:
        escrever_planilha(linhas, planilha)

    return montar_demonstracoes(
        linhas,
        empresa=nome,
        origem=f"CVM Dados Abertos - DFP {anos[0]}-{anos[-1]}",
        avisos=avisos,
        # Guardar codigo e anos e o que permite refazer esta mesma busca depois
        # -- quando sair um exercicio novo, ou quando a companhia reapresentar a
        # DFP. O setor viaja junto porque e o que permite montar um peer group
        # sem pedir ao usuario que classifique a empresa de novo.
        fonte={
            "tipo": FONTE_CVM,
            "codigo_cvm": codigo_cvm,
            "anos": list(anos),
            **({"setor": registro.setor} if registro and registro.setor else {}),
        },
    )


# ---------------------------------------------------------------------------
# ITR: o trimestre, e o ano movel que sai dele
# ---------------------------------------------------------------------------
#
# O ITR tem a mesma estrutura do DFP -- mesmas colunas, mesmo latin-1, mesmo
# ';' -- e uma armadilha propria, confirmada no arquivo de 2025:
#
# Para ``DT_REFER`` de 30/09, ``ORDEM_EXERC = ULTIMO``, a DRE traz **duas**
# linhas da mesma conta: o acumulado do exercicio (01/01 a 30/09, R$ 30,5 bi de
# receita na WEG) e o trimestre isolado (01/07 a 30/09, R$ 10,3 bi). Somar as
# duas infla em um terco; pegar a errada muda o numero pela metade. No primeiro
# trimestre ha uma linha so, porque acumulado e trimestre coincidem -- entao
# "pegar a ultima" acerta em marco e erra em setembro.
#
# A regra que funciona em qualquer trimestre e em qualquer exercicio social: o
# acumulado e a linha de **periodo mais longo**. Medidas as duracoes na secao
# ULTIMO de 2025, so existem tres faixas: 89-91 dias, 180-183 e 272-274.
# Sao Martinho, que fecha o exercicio em marco, acumula a partir de 01/04 -- a
# regra do periodo mais longo continua valendo sem saber disso.
#
# O balanco nao tem ``DT_INI_EXERC``: e uma data, nao um periodo. E o
# ``PENULTIMO`` do balanco e o **fim do exercicio anterior**, nao o mesmo
# trimestre do ano passado -- diferente da DRE. Confundir os dois compararia
# saldo de setembro com saldo de dezembro.

# Duracao minima, em dias, para uma linha de periodo ser considerada acumulada
# quando ha uma so. Serve para nao tratar um recorte estranho como exercicio.
_DIAS_DE_TRIMESTRE = 80


def trimestres_disponiveis(
    zip_path: Path, ano: int, codigo_cvm: int, escopo: str = "con"
) -> list[str]:
    """Datas de referencia que a companhia publicou no ano, da mais antiga."""
    dados = _ler_csv_do_zip(
        zip_path, _nome_no_zip("DRE", escopo, ano, "itr"), codigo_cvm
    )
    recorte = _filtrar_empresa(dados, codigo_cvm)
    if recorte.empty:
        return []
    return sorted({_texto(v) for v in recorte["DT_REFER"] if _texto(v)})


def _linhas_do_itr(
    zip_path: Path,
    ano: int,
    demonstracao: str,
    codigo_cvm: int,
    avisos: list[str],
    escopo: str,
    data_refer: str,
    ordem: str,
    periodo: str = "acumulado",
) -> list[LinhaCVM]:
    """Linhas de uma demonstracao do ITR, no periodo pedido.

    ``ordem`` e ``"ÚLTIMO"`` (exercicio corrente) ou ``"PENÚLTIMO"`` (o mesmo
    periodo do exercicio anterior, na DRE e na DFC). ``periodo`` escolhe entre o
    **acumulado** do exercicio ate o trimestre e o **trimestre isolado**, que a
    CVM publica lado a lado na mesma conta.
    """
    coletadas: list[LinhaCVM] = []

    for grupo in GRUPOS[demonstracao]:
        dados = _ler_csv_do_zip(
            zip_path, _nome_no_zip(grupo, escopo, ano, "itr"), codigo_cvm
        )
        recorte = _filtrar_empresa(dados, codigo_cvm, ordem=ordem)
        if recorte.empty:
            continue
        recorte = recorte[recorte["DT_REFER"].map(_texto) == data_refer]
        if recorte.empty:
            continue
        # A mesma guarda do anual: linha publicada duas vezes, byte a byte, faz a
        # regra somada contar as duas. Faltava aqui, e o ITR le os mesmos
        # arquivos das mesmas companhias.
        recorte = _sem_linhas_repetidas(recorte, demonstracao)

        # **Qual das duas linhas da mesma conta.** Para ``DT_REFER`` de 30/09 a
        # DRE traz o acumulado do exercicio (01/01-30/09) e o trimestre isolado
        # (01/07-30/09): o acumulado e a linha **mais longa** e o isolado, a
        # mais curta. No primeiro trimestre ha uma so, e as duas leituras
        # coincidem -- e por isso a escolha e por duracao e nao por posicao.
        #
        # Medidas as duracoes no ITR de 2025, so existem tres faixas: 89-91,
        # 180-183 e 272-274 dias. E o isolado e publicado por **100% das
        # companhias** em toda data de referencia, o que torna a visao
        # trimestral leitura direta e nao diferenca entre acumulados.
        if "DT_INI_EXERC" in recorte.columns:
            inicio = pd.to_datetime(recorte["DT_INI_EXERC"], errors="coerce")
            fim = pd.to_datetime(recorte["DT_FIM_EXERC"], errors="coerce")
            recorte = recorte.assign(_dias=(fim - inicio).dt.days)
            recorte = recorte.sort_values("_dias").drop_duplicates(
                subset=["CD_CONTA", "DS_CONTA"],
                keep="first" if periodo == "isolado" else "last",
            )

        # **O trimestre isolado do exercicio anterior so existe onde a companhia
        # o publica -- e na maioria das demonstracoes ele nao existe.** Medido no
        # ITR de 2025, secao ``PENULTIMO``: DRE e DRA trazem o trimestre em 454
        # das 460 companhias (99%), enquanto DFC, DVA e DMPL trazem em 10 (2%) e
        # o balanco em nenhuma -- ali o ``PENULTIMO`` e o **fim do exercicio
        # anterior**, sempre 31/12, igual nas tres datas de referencia.
        #
        # Sem esta guarda a leitura nao falha: ela mente. O acumulado de nove
        # meses de 2024 entraria rotulado como "3T24", tres vezes maior que o
        # trimestre, e o saldo de 31/12/2024 apareceria identico nas colunas de
        # 1T24, 2T24 e 3T24. Faltar a linha e honesto; traze-la errada, nao.
        if periodo == "isolado" and normalizar(ordem) == normalizar("PENÚLTIMO"):
            if "DT_INI_EXERC" not in recorte.columns:
                continue
            recorte = recorte[recorte["_dias"].between(_DIAS_DE_TRIMESTRE, 100)]
            if recorte.empty:
                continue

        for _, linha in recorte.iterrows():
            valor = pd.to_numeric(linha.get("VL_CONTA"), errors="coerce")
            if not np.isfinite(valor):
                continue
            fim_texto = _texto(linha.get("DT_FIM_EXERC"))
            ano_exercicio = int(fim_texto[:4]) if fim_texto[:4].isdigit() else ano
            coletadas.append(
                LinhaCVM(
                    codigo=_texto(linha.get("CD_CONTA")),
                    descricao=_texto(linha.get("DS_CONTA")),
                    valor=float(valor)
                    * _fator_da_linha(
                        linha.get("CD_CONTA"), linha.get("ESCALA_MOEDA"), avisos
                    ),
                    ano=ano_exercicio,
                    demonstracao=demonstracao,
                    escala=_texto(linha.get("ESCALA_MOEDA")),
                    escopo=escopo,
                    # Sem isto, ``detectar_metodo_da_dfc`` nao ve o ``DFC_MD`` do
                    # trimestral, e a DFC direta e lida com os codigos do
                    # indireto -- o mesmo defeito que o anual ja tinha corrigido.
                    grupo=grupo,
                )
            )
    return coletadas


def periodo_acumulado(
    zip_path: Path, ano: int, codigo_cvm: int, escopo: str, data_refer: str
) -> tuple[str, str] | None:
    """Inicio e fim do periodo acumulado do trimestre, como estao no arquivo.

    O inicio e o primeiro dia do **exercicio social** -- 01/01 para quem fecha
    em dezembro, 01/04 para Sao Martinho. E dele que sai qual exercicio ja
    fechou, que e a base do ano movel.
    """
    dados = _ler_csv_do_zip(
        zip_path, _nome_no_zip("DRE", escopo, ano, "itr"), codigo_cvm
    )
    recorte = _filtrar_empresa(dados, codigo_cvm, ordem="ultimo")
    recorte = recorte[recorte["DT_REFER"].map(_texto) == data_refer]
    if recorte.empty or "DT_INI_EXERC" not in recorte.columns:
        return None
    inicio = pd.to_datetime(recorte["DT_INI_EXERC"], errors="coerce")
    fim = pd.to_datetime(recorte["DT_FIM_EXERC"], errors="coerce")
    duracao = (fim - inicio).dt.days
    if duracao.dropna().empty:
        return None
    escolhida = duracao.idxmax()
    return (
        _texto(recorte.loc[escolhida, "DT_INI_EXERC"]),
        _texto(recorte.loc[escolhida, "DT_FIM_EXERC"]),
    )


def _itr_vazio(zip_path: Path, ano: int, escopo: str = "con") -> bool:
    """O arquivo do ano existe mas ainda nao tem nenhuma companhia?"""
    try:
        with zipfile.ZipFile(zip_path) as arquivo:
            bruto = arquivo.read(_nome_no_zip("DRE", escopo, ano, "itr"))
    except (KeyError, zipfile.BadZipFile, OSError):
        return True
    linhas = [linha for linha in bruto.splitlines()[1:] if linha]
    return not linhas


def _demonstracoes_do_itr(
    zip_path: Path,
    ano: int,
    codigo_cvm: int,
    escopo: str,
    data_refer: str,
    ordem: str,
    empresa: str,
    periodo: str = "acumulado",
) -> Demonstracoes:
    avisos: list[str] = []
    linhas: list[LinhaCVM] = []
    # **As seis demonstracoes, como no anual.** O ITR lia so tres, e o zip
    # trimestral traz as mesmas seis do DFP -- medido no de 2025: DVA com 116.854
    # linhas de 460 companhias, DRA com 32.114 e DMPL com 623.847. Fora dali
    # ficavam **sete contas canonicas que so existem na DVA**: receita bruta,
    # pessoal, impostos e taxas, aluguel, juros e o valor adicionado. Elas
    # respondem o que a DRE padronizada nao abre, e sumiam do ano movel sem que
    # nada dissesse.
    for demonstracao in GRUPOS:
        linhas.extend(
            _linhas_do_itr(
                zip_path, ano, demonstracao, codigo_cvm, avisos, escopo,
                data_refer, ordem, periodo
            )
        )
    if not linhas:
        raise ErroCVM(
            f"O ITR de {ano} nao tem dados da companhia {codigo_cvm} em {data_refer}."
        )
    return montar_demonstracoes(
        linhas,
        empresa=empresa,
        origem=f"ITR {data_refer} ({ordem}, {periodo})",
        avisos=avisos,
    )


def _avisar_se_a_dre_do_ano_movel_nao_fecha(
    tabela: pd.DataFrame, rotulo: int, avisos: list[str]
) -> None:
    """Confere as identidades da DRE sobre a coluna ja montada do ano movel.

    As correcoes de leitura -- sinal do imposto, lucro dos controladores quando a
    filha vem zerada -- rodam **por fonte**, e o ano movel combina tres. Uma
    correcao que fecha em cada parte pode nao fechar na soma, e isso nao e
    defeito de leitura: e propriedade da aritmetica.
    """
    from .importador import Demonstracoes

    try:
        conferencia = Demonstracoes(
            empresa="", valores=tabela
        ).conferir_dre_gerencial()
    except Exception:
        return
    if conferencia.empty or rotulo not in conferencia.columns:
        return

    quebrados = [
        str(subtotal)
        for subtotal, desvio in conferencia[rotulo].items()
        if np.isfinite(desvio) and desvio > 0.01
    ]
    if not quebrados:
        return
    avisos.append(
        "No ano movel, "
        + ", ".join(quebrados)
        + " nao fecha com a soma das linhas acima. O ano movel soma tres periodos, "
        "e quando as partes atribuem diferente -- tipicamente a divisao com "
        "minoritarios, que muda entre trimestres -- a identidade nao sobrevive a "
        "soma. Nao da para saber qual atribuicao descreve o periodo movel, entao o "
        "app avisa em vez de derivar por diferenca: a conta que nao fecha e a "
        "informacao."
        + _tamanho_da_diferenca(tabela, rotulo, quebrados)
    )


def _tamanho_da_diferenca(tabela: pd.DataFrame, rotulo: int, quebrados: list[str]) -> str:
    """De quanto e a diferenca, em dinheiro e em percentual do lucro.

    "Nao fecha" sem tamanho nao ajuda a decidir: quem le precisa saber se o
    problema vale 0,3% ou 78% do resultado -- no primeiro caso segue, no segundo
    para e vai ao arquivo. Medido nas 18 companhias que quebram nos
    controladores, a distancia vai de fracoes de por cento a multiplos do lucro.
    """
    if "Controladores" not in quebrados:
        return ""

    def valor(chave: str) -> float:
        if chave not in tabela.index or rotulo not in tabela.columns:
            return float("nan")
        try:
            return float(tabela.loc[chave, rotulo])
        except (TypeError, ValueError):
            return float("nan")

    lucro = valor("lucro_liquido")
    controladores = valor("lucro_controladores")
    minoritarios = valor("lucro_nao_controladores")
    if not all(np.isfinite(x) for x in (lucro, controladores)):
        return ""
    esperado = lucro - (minoritarios if np.isfinite(minoritarios) else 0.0)
    diferenca = esperado - controladores
    if not np.isfinite(diferenca) or diferenca == 0:
        return ""

    parte = f" A diferenca e de {diferenca:,.0f}".replace(",", ".")
    if lucro:
        parte += f", ou {abs(diferenca) / abs(lucro):.0%} do lucro consolidado"
    return parte + "."


def _identificar(
    companhia: Companhia | int, catalogo: list[Companhia] | None
) -> tuple[int, Companhia | None, str]:
    """Codigo CVM, registro do cadastro e nome, a partir de qualquer um dos dois."""
    if isinstance(companhia, Companhia):
        return companhia.codigo_cvm, companhia, companhia.nome
    codigo_cvm, nome = int(companhia), str(companhia)
    for candidato in catalogo or []:
        if candidato.codigo_cvm == codigo_cvm:
            return codigo_cvm, candidato, candidato.nome
    return codigo_cvm, None, nome


def _abrir_itr(
    ano: int, codigo_cvm: int, cache: Path | None, forcar_download: bool
) -> tuple[Path, int, str, list[str]]:
    """Zip do ITR, ano efetivo, escopo e trimestres com dado da companhia."""
    zip_itr = baixar_itr(ano, cache, forcar=forcar_download)
    escopo = escopo_da_companhia(zip_itr, ano, codigo_cvm, "itr") or ESCOPOS[0]
    trimestres = trimestres_disponiveis(zip_itr, ano, codigo_cvm, escopo)
    if not trimestres and _itr_vazio(zip_itr, ano):
        # Em janeiro o arquivo do ano ja existe e esta vazio; o ITR util e o do
        # ano anterior. A condicao e **o arquivo estar vazio**, e nao a
        # companhia faltar nele: sem essa distincao, pedir o ano movel de uma
        # companhia que nao publica ITR baixava o zip do ano anterior -- 33 MB
        # por consulta, para nada.
        ano -= 1
        zip_itr = baixar_itr(ano, cache, forcar=forcar_download)
        escopo = escopo_da_companhia(zip_itr, ano, codigo_cvm, "itr") or ESCOPOS[0]
        trimestres = trimestres_disponiveis(zip_itr, ano, codigo_cvm, escopo)
    if not trimestres:
        raise ErroCVM(
            f"A CVM nao tem ITR da companhia {codigo_cvm} em {ano} nem em {ano + 1}."
        )
    return zip_itr, ano, escopo, trimestres


def importar_ltm(
    companhia: Companhia | int,
    cache: Path | None = None,
    catalogo: list[Companhia] | None = None,
    ano: int | None = None,
    forcar_download: bool = False,
    data_refer: str | None = None,
) -> Demonstracoes:
    """Ano movel: o exercicio fechado, atualizado ate o trimestre pedido.

    ``data_refer`` escolhe **qual** trimestre encerra os doze meses; sem ele, o
    mais recente. E o que permite a serie rolante montar um ano movel por
    trimestre reusando esta funcao, em vez de reimplementar a formula -- duas
    implementacoes da mesma conta divergem no dia em que uma das duas muda.

    E o que faltava para o app "se atualizar quando sai balanco". A conta e a de
    sempre, e o ITR ja entrega as duas metades que ela pede::

        LTM = exercicio anterior fechado
              + acumulado do exercicio corrente (ORDEM_EXERC = ULTIMO)
              - acumulado do mesmo periodo do exercicio anterior (PENULTIMO)

    Contas de **resultado e de caixa** somam assim, porque descrevem um periodo.
    Contas de **balanco** nao: sao uma data, e o saldo certo e o do proprio
    trimestre. Somar o balanco pela mesma formula produziria um patrimonio que
    nao existe -- e o erro que este modulo separa por construcao, olhando
    ``demonstracao`` de cada conta canonica.

    O resultado tem uma coluna so, rotulada pelo ano de encerramento do periodo
    movel, e um aviso dizendo que aquilo nao e exercicio social. Sem o aviso,
    quem lesse "2025" numa companhia que fecha em dezembro entenderia ano cheio.
    """
    codigo_cvm, registro, nome = _identificar(companhia, catalogo)
    zip_itr, ano, escopo, trimestres = _abrir_itr(
        ano or date.today().year, codigo_cvm, cache, forcar_download
    )
    data_refer = data_refer or trimestres[-1]
    atual = _demonstracoes_do_itr(
        zip_itr, ano, codigo_cvm, escopo, data_refer, "ultimo", nome
    )
    anterior = _demonstracoes_do_itr(
        zip_itr, ano, codigo_cvm, escopo, data_refer, "penultimo", nome
    )

    # O exercicio-base e o **anterior ao que o ITR esta acumulando**, e nao
    # simplesmente o ano passado. Pedir "o DFP mais recente" quebra em duas
    # situacoes reais: quando o exercicio corrente ja fechou e foi publicado --
    # somar o acumulado por cima contaria os mesmos meses duas vezes, o que
    # inflava a receita da WEG em R$ 2,8 bi -- e quando o exercicio social nao
    # fecha em dezembro, caso em que o rotulo do ano nao acompanha o calendario.
    periodo = periodo_acumulado(zip_itr, ano, codigo_cvm, escopo, data_refer)
    if periodo is None:
        raise ErroCVM("Nao consegui identificar o periodo acumulado do trimestre.")
    inicio_do_exercicio = pd.to_datetime(periodo[0])
    fim_do_exercicio = inicio_do_exercicio + pd.DateOffset(years=1) - pd.Timedelta(days=1)
    ano_base = int(fim_do_exercicio.year) - 1

    anual = importar_cvm(
        registro or codigo_cvm, [ano_base], cache=cache, catalogo=catalogo
    )
    if ano_base not in anual.anos:
        raise ErroCVM(
            f"Para montar o ano movel preciso do exercicio {ano_base} fechado, e a "
            "CVM nao o tem para esta companhia."
        )

    fim = pd.to_datetime(data_refer)
    rotulo = int(fim.year)

    valores: dict[str, float] = {}
    origem_da_conta: dict[str, str] = {}
    for chave in set(anual.valores.index) | set(atual.valores.index):
        conta = POR_CHAVE.get(chave)
        if conta is None:
            continue
        if conta.demonstracao in ("bp", "capital"):
            saldo = atual.valor(chave)
            if saldo is not None and np.isfinite(saldo):
                valores[chave] = saldo
                origem_da_conta[chave] = f"saldo em {data_refer}"
            continue

        base = anual.valor(chave, ano_base)
        soma = atual.valor(chave)
        subtrai = anterior.valor(chave)
        partes = [base, soma, subtrai]
        if any(p is None or not np.isfinite(p) for p in partes):
            continue
        valores[chave] = base + soma - subtrai
        origem_da_conta[chave] = (
            f"{ano_base} + acumulado ate {data_refer} - mesmo periodo anterior"
        )

    if not valores:
        raise ErroCVM("Nao consegui montar o ano movel: faltam contas em comum.")

    ordem = [c.chave for c in CONTAS if c.chave in valores]
    tabela = pd.DataFrame({rotulo: {chave: valores[chave] for chave in ordem}})

    avisos = [
        f"**Este não é um exercício social.** A coluna {rotulo} é o ano móvel "
        f"encerrado em {data_refer}: o exercício de {ano_base} mais o acumulado até "
        "o trimestre, menos o mesmo período do ano anterior. Contas de balanço são o "
        f"saldo em {data_refer}, não uma soma."
    ]
    avisos += [a for a in atual.avisos if "ORDEM_EXERC" not in a]

    # **Companhia que troca de metodo da DFC entre o anual e o trimestre nao tem
    # ano movel para as contas de reconciliacao.** O ano movel e
    # ``anual + acumulado - mesmo periodo do ano anterior``, e caixa gerado,
    # variacao de giro e D&A da DFC so existem no metodo indireto: se um dos
    # lados publica pelo direto, a subtracao nao tem as duas metades e o
    # resultado sai NaN, calado. Medido entre o DFP de 2024 e o ultimo ITR de
    # 2025: **6 das 454 companhias trocam**, todas de direto para indireto --
    # entre elas Santander, BRB e Axia Energia Nordeste.
    #
    # A deteccao reusa o aviso que cada lado ja carrega, em vez de refazer a
    # leitura: um segundo caminho para a mesma pergunta divergiria do primeiro no
    # dia em que um dos dois mudasse.
    direto_no_anual = any(MARCA_METODO_DIRETO in a for a in anual.avisos)
    direto_no_trimestre = any(MARCA_METODO_DIRETO in a for a in atual.avisos)
    if direto_no_anual != direto_no_trimestre:
        de, para = (
            ("direto", "indireto") if direto_no_anual else ("indireto", "direto")
        )
        avisos.append(
            f"A DFC muda de metodo entre o exercicio fechado ({de}) e o trimestre "
            f"({para}). Caixa gerado pelas operacoes, variacao de capital de giro "
            "e D&A da DFC so existem no metodo indireto, entao o ano movel dessas "
            "contas nao tem as duas metades para subtrair e sai vazio. O total do "
            "operacional, o investimento e o financiamento continuam validos."
        )

    # **O ano movel e soma de tres periodos, e identidade da DRE nao sobrevive a
    # soma quando as partes atribuem diferente.** Medido no ITR de 2025: a ponte
    # fecha em 430 das 454 companhias, e das 24 que sobram **18 quebram no lucro
    # dos controladores** -- a Melhoramentos de Sao Paulo reconcilia no exercicio
    # fechado e nao no ano movel, porque a divisao com minoritarios mudou entre
    # os trimestres.
    #
    # Nao da para saber qual das duas atribuicoes descreve o periodo movel, entao
    # o app **avisa em vez de plugar**: derivar o controlador por diferenca aqui
    # esconderia que a soma nao fecha, e a conta que nao fecha e a informacao.
    _avisar_se_a_dre_do_ano_movel_nao_fecha(tabela, rotulo, avisos)

    return Demonstracoes(
        empresa=anual.empresa,
        valores=tabela,
        origem=f"CVM ITR — ano móvel até {data_refer}",
        unidade="reais",
        mapeamento=origem_da_conta,
        avisos=avisos,
        fonte={
            "tipo": FONTE_CVM,
            "codigo_cvm": codigo_cvm,
            "ltm": data_refer,
            "ano_base": ano_base,
            "setor": getattr(registro, "setor", "") or "",
        },
        detalhe=atual.detalhe,
    )


# ---------------------------------------------------------------------------
# Onde o juro pago mora: padronizar para que FCO signifique a mesma coisa
# ---------------------------------------------------------------------------
#
# O IFRS deixa a companhia escolher se juro pago vai no operacional ou no
# financiamento, e a base se divide: medido em 2024, **223 companhias poem no
# operacional e 121 no financiamento** (13 em ambos). Duas empresas identicas
# com classificacoes diferentes tem FCO diferente, e todo indicador que divide
# por FCO -- conversao de caixa, capex/FCO, cobertura do circulante -- deixa de
# comparar negocio e passa a comparar apresentacao.
#
# A padronizacao adotada e trazer o juro para o operacional, **abaixo da
# variacao do capital de giro, junto com os impostos pagos**. E onde o analista
# espera ve-lo: o FCO passa a ser caixa depois de servir a divida, para todo
# mundo. A alternativa -- somar de volta o juro de quem ja o tem dentro --
# produziria um FCO antes de juros que nenhuma companhia publica.
#
# A identidade da DFC sobrevive por construcao: o que sai do financiamento entra
# no operacional, e a soma das secoes nao muda.


def juros_pagos_no_financiamento(linhas: list[LinhaCVM]) -> dict[int, float]:
    """Juro pago que a companhia classificou na secao de financiamento.

    Devolve magnitudes por ano. So conta as linhas **mais externas** de 6.03:
    companhia que abre "Juros pagos" e, abaixo, "Juros de emprestimos" somaria o
    mesmo desembolso duas vezes.
    """
    candidatas = [
        linha
        for linha in linhas
        if linha.demonstracao == "dfc"
        and linha.codigo.startswith("6.03")
        and linha.codigo != "6.03"
        and _MARCA_JUROS_PAGOS.search(linha.descricao)
        and not _NAO_E_JURO_PAGO.search(linha.descricao)
        and linha.valor
    ]

    por_ano: dict[int, list[LinhaCVM]] = {}
    for linha in candidatas:
        por_ano.setdefault(linha.ano, []).append(linha)

    total: dict[int, float] = {}
    for ano, do_ano in por_ano.items():
        codigos = {linha.codigo for linha in do_ano}
        for linha in do_ano:
            tem_pai = any(
                linha.codigo != outro and linha.codigo.startswith(outro + ".")
                for outro in codigos
            )
            if not tem_pai:
                total[ano] = total.get(ano, 0.0) + abs(linha.valor)
    return total


def _padronizar_juros_no_fco(
    linhas: list[LinhaCVM],
    tabela: dict[str, dict[int, float]],
    mapeamento: dict[str, str],
    avisos: list[str],
) -> None:
    """Traz para o FCO o juro que a companhia deixou no financiamento."""
    no_financiamento = juros_pagos_no_financiamento(linhas)
    if not no_financiamento:
        return

    operacional = tabela.get("fluxo_operacional")
    financiamento = tabela.get("fluxo_financiamento")
    if not operacional or not financiamento:
        return

    movido: dict[int, float] = {}
    for ano, valor in no_financiamento.items():
        if ano not in operacional or ano not in financiamento:
            continue
        operacional[ano] -= valor
        financiamento[ano] += valor
        movido[ano] = valor

    if not movido:
        return

    tabela["juros_pagos_no_financiamento"] = movido
    mapeamento["juros_pagos_no_financiamento"] = "linhas de juros pagos em 6.03"
    for chave in ("fluxo_operacional", "fluxo_financiamento"):
        nota = "(juros pagos reclassificados)"
        if nota not in mapeamento.get(chave, ""):
            mapeamento[chave] = f"{mapeamento.get(chave, '')} {nota}".strip()

    avisos.append(
        "Esta companhia classifica juros pagos no fluxo de **financiamento**. "
        "Trouxe esses juros para o operacional, abaixo da variação do capital de "
        "giro e junto dos impostos pagos, para que o FCO signifique o mesmo que o "
        "das companhias que já os classificam ali. A soma das seções não muda; a "
        "linha reclassificada aparece como 'Juros pagos reclassificados para o FCO'."
    )


# ---------------------------------------------------------------------------
# O que esta no lugar errado dentro do proprio FCO
# ---------------------------------------------------------------------------
#
# A secao 6.01.02 e "variacoes nos ativos e passivos" -- capital de giro. Muita
# companhia lanca ali coisas que nao sao movimento de saldo: medido em 2024,
# **127 companhias poem imposto de renda pago dentro do giro (R$ 44,7 bi) e 69
# poem juros pagos (R$ 23,4 bi)**. O FCO nao muda com isso, mas o "investimento
# em giro" que se le da DFC vira outra coisa -- e ele e premissa de projecao.
#
# A separacao que importa e entre **pagamento** e **saldo**: "Impostos a
# recuperar" e "Tributos a recolher" sao giro de verdade e ficam; "Imposto de
# renda e contribuicao social pagos" nao e giro e desce para junto do juro.
_E_PAGAMENTO = re.compile(r"pago|pagos|pagamento|desembols|quita", re.I)
_E_MOVIMENTO_DE_SALDO = re.compile(
    r"a recuperar|a recolher|a pagar|a receber|obriga[cç]|cr[ée]dito|varia[cç]|"
    r"ativo|passivo",
    re.I,
)
_MARCA_IMPOSTO = re.compile(r"imposto|tribut|irpj|csll", re.I)

# Outorga de concessao. O padrao e **estreito de proposito**: na DFC a palavra
# "outorga" aparece sobretudo em "Opcoes outorgadas" e "Instrumentos
# patrimoniais outorgados", que sao remuneracao em acoes e nao concessao. Uma
# regra larga jogaria despesa com opcoes no capex. Medido: com este padrao sao
# 9 companhias e R$ 3,4 bilhoes; com "outorga" solto, 38 companhias, e a maioria
# delas e plano de opcoes.
_MARCA_OUTORGA = re.compile(
    r"poder concedente|onus da outorga|[oô]nus da outorga|outorga fixa|"
    r"outorga vari[aá]vel|direito de outorga|concess[aã]o a pagar|espectro|"
    r"radiofrequ",
    re.I,
)
_NAO_E_OUTORGA = re.compile(r"op[cç][oõ]es|instrumento|restrita", re.I)
_E_RECEBIMENTO = re.compile(r"recebiment|recebid", re.I)


def _mais_externas(linhas: list[LinhaCVM]) -> list[LinhaCVM]:
    """Descarta as linhas que sao filhas de outra ja presente na lista."""
    por_ano: dict[int, list[LinhaCVM]] = {}
    for linha in linhas:
        por_ano.setdefault(linha.ano, []).append(linha)
    resultado: list[LinhaCVM] = []
    for do_ano in por_ano.values():
        codigos = {linha.codigo for linha in do_ano}
        for linha in do_ano:
            if not any(
                linha.codigo != outro and linha.codigo.startswith(outro + ".")
                for outro in codigos
            ):
                resultado.append(linha)
    return resultado


def pagamentos_dentro_do_giro(linhas: list[LinhaCVM]) -> dict[int, float]:
    """Juro e imposto **pagos** lancados dentro da variacao do capital de giro."""
    candidatas = [
        linha
        for linha in linhas
        if linha.demonstracao == "dfc"
        and linha.codigo.startswith("6.01.02")
        and linha.codigo != "6.01.02"
        and linha.valor
        and (
            _MARCA_JUROS_PAGOS.search(linha.descricao)
            or _MARCA_IMPOSTO.search(linha.descricao)
        )
        and _E_PAGAMENTO.search(linha.descricao)
        and not _E_MOVIMENTO_DE_SALDO.search(linha.descricao)
        and not _NAO_E_JURO_PAGO.search(linha.descricao)
    ]
    total: dict[int, float] = {}
    for linha in _mais_externas(candidatas):
        total[linha.ano] = total.get(linha.ano, 0.0) + abs(linha.valor)
    return total


def outorgas_pagas(linhas: list[LinhaCVM]) -> dict[str, dict[int, float]]:
    """Pagamento de outorga, separado pela secao em que a companhia o lancou."""
    fora: dict[str, dict[int, float]] = {"operacional": {}, "financiamento": {}}
    candidatas = [
        linha
        for linha in linhas
        if linha.demonstracao == "dfc"
        and linha.codigo.startswith(("6.01", "6.03"))
        and linha.valor
        and _MARCA_OUTORGA.search(linha.descricao)
        and not _NAO_E_OUTORGA.search(linha.descricao)
        and _E_PAGAMENTO.search(linha.descricao)
        and not _E_RECEBIMENTO.search(linha.descricao)
    ]
    for linha in _mais_externas(candidatas):
        chave = "operacional" if linha.codigo.startswith("6.01") else "financiamento"
        fora[chave][linha.ano] = fora[chave].get(linha.ano, 0.0) + abs(linha.valor)
    return fora


def _reorganizar_o_fco(
    linhas: list[LinhaCVM],
    tabela: dict[str, dict[int, float]],
    mapeamento: dict[str, str],
    avisos: list[str],
) -> None:
    """Tira do giro o que e pagamento, e da operacao o que e investimento.

    Duas correcoes de lugar, com efeitos diferentes:

    * **Juro e imposto pagos dentro do capital de giro** descem para junto dos
      demais pagamentos. O FCO nao muda -- eles ja estavam dentro dele --, mas o
      investimento em giro deixa de carregar desembolso que nao e giro.
    * **Outorga de concessao** sai do operacional (ou do financiamento) e entra
      no investimento. E direito de explorar comprado a prazo: economicamente,
      capex. Aqui o FCO **muda**, e a identidade da DFC se preserva porque o
      mesmo valor entra no investimento.
    """
    giro = tabela.get("variacao_capital_giro")
    pagamentos = pagamentos_dentro_do_giro(linhas)
    movidos: dict[int, float] = {}
    if giro and pagamentos:
        for ano, valor in pagamentos.items():
            if ano not in giro:
                continue
            # O pagamento entrou no giro com sinal negativo; tira-lo e soma-lo
            # de volta, e o FCO continua exatamente o mesmo.
            giro[ano] += valor
            movidos[ano] = valor

    if movidos:
        tabela["pagamentos_reclassificados_do_giro"] = movidos
        mapeamento["pagamentos_reclassificados_do_giro"] = (
            "juros e impostos pagos lancados em 6.01.02"
        )
        nota = "(pagamentos retirados)"
        if nota not in mapeamento.get("variacao_capital_giro", ""):
            mapeamento["variacao_capital_giro"] = (
                f"{mapeamento.get('variacao_capital_giro', '')} {nota}".strip()
            )
        avisos.append(
            "Esta companhia lança juros e/ou impostos **pagos** dentro da variação "
            "de ativos e passivos. Tirei esses desembolsos do capital de giro e os "
            "deixei abaixo dele, ainda dentro do FCO. O caixa operacional não muda; "
            "muda o investimento em giro que se lê da DFC, que é premissa de projeção."
        )

    investimento = tabela.get("fluxo_investimento")
    if investimento is None:
        return

    outorga = outorgas_pagas(linhas)
    total_outorga: dict[int, float] = {}
    secoes = (
        ("operacional", tabela.get("fluxo_operacional")),
        ("financiamento", tabela.get("fluxo_financiamento")),
    )
    for secao, serie in secoes:
        valores = outorga[secao]
        if not valores or serie is None:
            continue
        for ano, valor in valores.items():
            if ano not in serie or ano not in investimento:
                continue
            serie[ano] += valor
            investimento[ano] -= valor
            total_outorga[ano] = total_outorga.get(ano, 0.0) + valor
            if giro is not None and secao == "operacional" and ano in giro:
                # Quando a outorga estava dentro do giro, ela tambem sai de la --
                # do contrario o giro ficaria com um buraco do tamanho dela.
                giro[ano] += valor

    if not total_outorga:
        return

    tabela["outorga_paga"] = total_outorga
    mapeamento["outorga_paga"] = "pagamentos ao poder concedente"
    capex = tabela.setdefault("capex", {})
    for ano, valor in total_outorga.items():
        capex[ano] = capex.get(ano, 0.0) + valor
    avisos.append(
        "Esta companhia paga outorga de concessão. Movi esses pagamentos para o "
        "fluxo de investimento e somei ao capex: comprar o direito de explorar é "
        "investimento, não custo de operar. A soma das seções não muda."
    )


# ---------------------------------------------------------------------------
# As tres leituras do tempo: anual, trimestral e ano movel rolante
# ---------------------------------------------------------------------------


def importar_trimestral(
    companhia: Companhia | int,
    cache: Path | None = None,
    catalogo: list[Companhia] | None = None,
    ano: int | None = None,
    forcar_download: bool = False,
) -> Demonstracoes:
    """Os trimestres **isolados** do exercicio, uma coluna cada.

    O trimestre isolado mostra inflexao: uma margem que virou no 3T aparece aqui
    e some no acumulado, diluida pelos trimestres anteriores. Ele e leitura
    direta e nao diferenca entre acumulados -- medido no ITR de 2025, **100% das
    companhias publicam a linha isolada** em toda data de referencia, ao lado do
    acumulado.

    **Carrega sazonalidade**, e por isso a serie sai rotulada por trimestre
    (``1T25``, ``2T25``): comparar 3T com 2T e comparar epocas do ano diferentes,
    e o par que se compara e 3T contra 3T. Quem quer a serie sem sazonalidade usa
    ``importar_ltm_rolante``.

    Contas de balanco **nao sao do periodo**: entram como o saldo no fim de cada
    trimestre, e nao como diferenca.
    """
    from .series import _rotulo_do_trimestre, montar_serie

    codigo_cvm, registro, nome = _identificar(companhia, catalogo)
    zip_itr, ano, escopo, trimestres = _abrir_itr(
        ano or date.today().year, codigo_cvm, cache, forcar_download
    )

    # **O `PENÚLTIMO` dobra a série sem baixar outro zip.** Para cada data de
    # referência o ITR publica o mesmo trimestre do exercício anterior ao lado do
    # corrente, e ele estava sendo lido só no caminho do ano móvel. Sem ele a
    # série tinha um exercício e o par que importa -- 3T contra 3T -- não existia
    # dentro dela; com ele, quatro trimestres de 2025 trazem quatro de 2024 de
    # graça.
    partes = []
    for data_refer in trimestres:
        for ordem in ("penultimo", "ultimo"):
            try:
                dfs = _demonstracoes_do_itr(
                    zip_itr, ano, codigo_cvm, escopo, data_refer, ordem, nome,
                    periodo="isolado",
                )
            except ErroCVM:
                continue
            # **Trimestre todo zero nao e trimestre**, e o mesmo criterio do
            # escopo um nivel abaixo: a secao existe no arquivo e nao foi
            # preenchida. Na TIM, o `PENULTIMO` consolidado do ITR de 2026 tem
            # 84 linhas e **nenhum valor diferente de zero**, enquanto o
            # individual do mesmo periodo esta cheio -- entrar como coluna de
            # zeros diria que a companhia nao faturou nada no trimestre.
            if not (dfs.valores.fillna(0) != 0).any().any():
                continue
            rotulo = _rotulo_do_trimestre(data_refer)
            if ordem == "penultimo":
                # Mesmo trimestre, exercicio anterior: 3T25 vira 3T24.
                numero, _, ano_curto = rotulo.partition("T")
                rotulo = f"{numero}T{int(ano_curto) - 1:02d}"
            partes.append((rotulo, dfs))

    # A ordem cronologica e a que se le, e as duas passadas a embaralham.
    def _cronologica(item):
        rotulo = item[0]
        trimestre, _, ano_curto = rotulo.partition("T")
        return (int(ano_curto), int(trimestre))

    partes = sorted(
        {rotulo: (rotulo, dfs) for rotulo, dfs in partes}.values(), key=_cronologica
    )

    if not partes:
        raise ErroCVM(
            f"A CVM nao tem trimestre da companhia {codigo_cvm} em {ano}."
        )

    return montar_serie(
        partes,
        empresa=nome,
        unidade="reais",
        origem=f"CVM ITR — trimestres isolados de {ano} e do exercício anterior",
        # **Estes textos vao para a tela**, e por isso vem acentuados. O codigo
        # em volta escreve em ASCII; o que o usuario le, nao.
        avisos=[
            "**Trimestres isolados, e não acumulados.** Cada coluna são três "
            "meses sozinhos, o que mostra inflexão mas **carrega sazonalidade**: "
            "comparar 3T com 2T compara épocas do ano diferentes, e o par certo "
            "é 3T contra 3T. Contas de balanço são o saldo no fim de cada "
            "trimestre, e não uma soma.",
            "**As colunas do exercício anterior têm só a DRE.** Elas vêm do "
            "`PENÚLTIMO` do próprio ITR, que publica o mesmo trimestre do ano "
            "passado ao lado do corrente — e o publica **só na DRE e na DRA**: "
            "medido no ITR de 2025, 99% das companhias trazem o trimestre "
            "anterior ali, contra 2% na DFC, na DVA e na DMPL. No balanço ele "
            "não existe de forma nenhuma: o `PENÚLTIMO` do balanço é o saldo de "
            "31/12, e não o fim do trimestre. Por isso caixa e balanço aparecem "
            "**vazios** nessas colunas, em vez de aparecerem errados.",
            "**São os números reapresentados.** O ano anterior vem como a "
            "companhia o publica hoje, e não como publicou na época — que é a "
            "base certa para comparar, e a razão de poder divergir de um "
            "relatório antigo. Conferidas 111 contas em 22 companhias contra o "
            "ITR do próprio ano, 102 batem exatamente e 9 diferem por "
            "reapresentação da companhia (a Auren refez o resultado bruto dos "
            "três trimestres de 2024).",
            *partes[-1][1].avisos,
        ],
    )


def importar_ltm_rolante(
    companhia: Companhia | int,
    cache: Path | None = None,
    catalogo: list[Companhia] | None = None,
    ano: int | None = None,
    forcar_download: bool = False,
) -> Demonstracoes:
    """O ano movel encerrado em **cada** trimestre, uma coluna cada.

    Tira a sazonalidade sem esperar o exercicio fechar, que e exatamente o que
    falta entre um balanco anual e o proximo -- e mostra a **tendencia**, que um
    ano movel sozinho nao mostra: doze meses em queda e doze meses em alta dao o
    mesmo ponto no ultimo trimestre.

    Cada coluna sai da mesma formula do ano movel pontual, aplicada naquele
    trimestre. **Nao e a soma dos quatro trimestres isolados**: o quarto
    trimestre do exercicio anterior nao existe no ITR, ele seria o exercicio
    fechado menos o acumulado de nove meses.
    """
    from .series import _rotulo_do_trimestre, montar_serie

    codigo_cvm, registro, nome = _identificar(companhia, catalogo)
    zip_itr, ano, escopo, trimestres = _abrir_itr(
        ano or date.today().year, codigo_cvm, cache, forcar_download
    )

    partes = []
    avisos_ultimo: list[str] = []
    for data_refer in trimestres:
        try:
            dfs = importar_ltm(
                registro or codigo_cvm,
                cache=cache,
                catalogo=catalogo,
                ano=ano,
                forcar_download=False,
                data_refer=data_refer,
            )
        except ErroCVM:
            continue
        partes.append((_rotulo_do_trimestre(data_refer), dfs))
        avisos_ultimo = dfs.avisos

    if not partes:
        raise ErroCVM(
            f"Nao consegui montar ano movel nenhum da companhia {codigo_cvm} em {ano}."
        )

    return montar_serie(
        partes,
        empresa=nome,
        unidade="reais",
        origem=f"CVM ITR — ano móvel rolante de {ano}",
        avisos=[
            "**Cada coluna e um ano movel de doze meses**, encerrado no trimestre "
            "que a rotula -- e nao um exercicio social. A serie tira a "
            "sazonalidade sem esperar o exercicio fechar, e mostra a tendencia "
            "que um ano movel sozinho esconde: doze meses em queda e doze em alta "
            "dao o mesmo ponto no ultimo trimestre. Contas de balanco sao o saldo "
            "no fim de cada trimestre.",
            *avisos_ultimo,
        ],
    )

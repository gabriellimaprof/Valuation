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
GRUPOS = {
    "dre": ("DRE",),
    "bp": ("BPA", "BPP"),
    "dfc": ("DFC_MI", "DFC_MD"),
}


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
    from datetime import date

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


def _nome_no_zip(grupo: str, escopo: str, ano: int) -> str:
    return f"dfp_cia_aberta_{grupo}_{escopo}_{ano}.csv"


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


def _filtrar_empresa(dados: pd.DataFrame, codigo_cvm: int) -> pd.DataFrame:
    """Linhas da companhia, so o exercicio ``ULTIMO`` e so a versao mais recente.

    O filtro de ``ORDEM_EXERC`` e o que impede o ano do meio de entrar duas
    vezes quando se pede uma serie de varios anos (ver o cabecalho do modulo).
    """
    if dados is None or dados.empty:
        return pd.DataFrame()

    codigos = dados["CD_CVM"].map(lambda v: _so_digitos(v) or "0").astype(int)
    recorte = dados[codigos == codigo_cvm]
    if recorte.empty:
        return recorte

    ordem = recorte["ORDEM_EXERC"].map(lambda v: normalizar(v))
    recorte = recorte[ordem == "ultimo"]
    if recorte.empty:
        return recorte

    # Uma companhia que reapresenta a DFP ganha VERSAO nova. Nos arquivos de 2024
    # a CVM ja publica so a ultima, mas quem depende disso quebra em silencio no
    # dia em que publicar as duas -- e somar duas versoes dobraria as contas.
    versoes = pd.to_numeric(recorte["VERSAO"], errors="coerce")
    if versoes.notna().any():
        recorte = recorte[versoes == versoes.max()]
    return recorte


def escopo_da_companhia(zip_path: Path, ano: int, codigo_cvm: int) -> str | None:
    """Consolidado ou individual, decidido uma vez para a companhia inteira.

    Escolher por demonstracao permitiria ler a DRE do grupo economico junto com
    a DFC da empresa isolada -- duas entidades diferentes na mesma tabela, sem
    nada indicando qual foi qual. Conferido nos arquivos de 2024: das 467
    companhias com consolidado, nenhuma deixa de publicar alguma demonstracao
    nesse escopo, entao travar aqui nao custa dado.
    """
    for escopo in ESCOPOS:
        for grupos in GRUPOS.values():
            for grupo in grupos:
                dados = _ler_csv_do_zip(
                    zip_path, _nome_no_zip(grupo, escopo, ano), codigo_cvm
                )
                if dados is not None and not _filtrar_empresa(dados, codigo_cvm).empty:
                    return escopo
    return None


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
                    * _fator_escala(linha.get("ESCALA_MOEDA"), avisos),
                    ano=ano_exercicio,
                    demonstracao=demonstracao,
                    escala=_texto(linha.get("ESCALA_MOEDA")),
                    escopo=escopo,
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


REGRAS_SOMADAS: tuple[RegraSomada, ...] = (
    RegraSomada(
        chave="capex",
        prefixo="6.02.",
        inclui=re.compile(r"imobiliz|intang[ií]|ativo fixo|capex|permanente", re.I),
        exclui=re.compile(
            r"venda|aliena|baixa|recebiment|resgate|receb\.|desinvestiment", re.I
        ),
        confirma=re.compile(
            r"aquisi|adi[cç][aã]o|adi[cç][oõ]es|compra|dispêndio|desembolso|"
            r"investiment|^no\s|^em\s",
            re.I,
        ),
        rotulo_curto_basta=True,
    ),
    RegraSomada(
        chave="juros_pagos",
        inclui=re.compile(r"juros", re.I),
        # JCP e remuneracao ao acionista, nao custo da divida: vai em dividendos.
        exclui=re.compile(
            r"recebid|capital pr[óo]prio|\bjcp\b|receita|capitaliz|a pagar", re.I
        ),
        confirma=re.compile(r"pag", re.I),
        secao_dispensa_verbo="6.03",
    ),
    RegraSomada(
        chave="dividendos_pagos",
        inclui=re.compile(r"dividendo|capital pr[óo]prio|\bjcp\b", re.I),
        exclui=re.compile(r"recebid|a receber|a pagar|receita", re.I),
        confirma=re.compile(r"pag|distribu", re.I),
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


def _reconhecer_na_demonstracao(linha: LinhaCVM, plano: str = PLANO_INDUSTRIAL):
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
    if plano == PLANO_INDUSTRIAL:
        resultado = reconhecer(linha.descricao, linha.codigo)
    else:
        resultado = reconhecer(linha.descricao, None)

    if resultado.chave is None:
        return resultado
    if POR_CHAVE[resultado.chave].demonstracao != linha.demonstracao:
        return type(resultado)(
            None, 0.0, f"'{resultado.chave}' nao pertence a {linha.demonstracao}"
        )
    return resultado


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

    rotulo_da_aba = {"dre": "DRE", "bp": "Balanço", "dfc": "DFC"}

    plano = detectar_plano(linhas)
    if plano == PLANO_FINANCEIRO:
        avisos.append(
            "Esta companhia publica no plano de contas de instituicao financeira "
            "ou seguradora, em que os mesmos codigos significam outras contas. "
            "Reconheci as linhas apenas pelo nome, e o modelo de FCFF/WACC nao se "
            "aplica a bancos e seguradoras -- confira conta por conta antes de usar."
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
        resultado = _reconhecer_na_demonstracao(linha, plano)
        if resultado.chave is None or resultado.confianca < CONFIANCA_MINIMA:
            etiqueta = f"{linha.codigo} - {linha.descricao}"
            nao_reconhecidas.setdefault(
                f"{linha.demonstracao}|{etiqueta}",
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
    derivadas = _derivar(tabela, anos)

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
    if isinstance(companhia, Companhia):
        codigo_cvm, nome = companhia.codigo_cvm, companhia.nome
    else:
        codigo_cvm = int(companhia)
        nome = str(companhia)
        for registro in catalogo or []:
            if registro.codigo_cvm == codigo_cvm:
                nome = registro.nome
                break

    anos = sorted({int(a) for a in anos})
    if not anos:
        raise ErroCVM("Escolha ao menos um ano.")

    linhas: list[LinhaCVM] = []
    avisos: list[str] = []
    anos_sem_dados: list[int] = []
    escalas: set[str] = set()
    escopos: set[str] = set()

    for ano in anos:
        zip_path = baixar_dfp(ano, cache=cache)
        # O escopo e decidido para a companhia inteira antes de ler qualquer
        # demonstracao, para que DRE, balanco e DFC descrevam a mesma entidade.
        escopo = escopo_da_companhia(zip_path, ano, codigo_cvm)
        if escopo is None:
            anos_sem_dados.append(ano)
            continue
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
        linhas.extend(do_ano)
        escalas.update(linha.escala for linha in do_ano)
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
    if "ind" in escopos:
        avisos.append(
            "Esta companhia nao publica demonstracao consolidada em ao menos um "
            "dos anos; usei a individual. Numeros individuais nao somam as "
            "controladas."
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
        # DFP. Sem isso, o valuation salvo sabe de onde veio em portugues, mas o
        # app nao sabe o suficiente para ir buscar de novo.
        fonte={"tipo": FONTE_CVM, "codigo_cvm": codigo_cvm, "anos": list(anos)},
    )

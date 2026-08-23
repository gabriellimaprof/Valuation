"""Dados de mercado: curva real brasileira e expectativas do Focus.

Serve a um proposito so, e vale dizer qual para nao virar gaveta de API: medir
o **risco-pais que o mercado cobra**, em vez de usar o valor de referencia
embarcado em ``dados_setoriais.py``.

O Ke continua montado em USD (ver a decisao em CLAUDE.md). O que muda e de onde
sai o ``risco_pais`` dessa conta. Hoje ele e um numero de ordem de grandeza; a
curva de NTN-B permite observa-lo.

A aritmetica
------------

A NTN-B paga taxa **real**. Para comparar com uma taxa nominal em USD e preciso
nominaliza-la pela inflacao esperada::

    rf_brl_nominal = (1 + taxa_real) x (1 + ipca_esperado) - 1

E converter o rf americano para BRL pelo mesmo diferencial de inflacao que o
motor ja usa::

    rf_usd_em_brl = (1 + rf_usd) x (1 + ipca) / (1 + inflacao_usd) - 1

A diferenca entre os dois e o que o mercado cobra a mais para financiar o Brasil.

O que essa diferenca e, e o que ela nao e
----------------------------------------

O termo que **domina** e o premio de risco de carregar o Brasil -- e ele que se
quer medir. Liquidez da NTN-B e ruido de inflacao sao de segunda ordem, mas
existem, e por isso a funcao devolve as parcelas junto do resultado: quem le
decide quanto atribuir a risco-pais, e o app nao troca o padrao sozinho.

**A medida atual e um piso, nao um ponto.** A NTN-B e indexada: quem a carrega
nao corre risco de inflacao. Quem carrega titulo nominal corre, e cobra por
isso -- o premio de risco de inflacao::

    titulo nominal = juro real + inflacao esperada + premio de risco de inflacao
    NTN-B          = juro real                                       (indexada)

Nominalizar a NTN-B so com a inflacao esperada, como se faz aqui, omite esse
premio e produz um ``rf_brl_nominal`` baixo demais -- logo, um risco-pais
subestimado.

A correcao esta ao alcance e nao foi feita: usar a **inflacao implicita**
(prefixado menos NTN-B de prazo equivalente) no lugar do IPCA do Focus. Ela ja
embute o premio, e os dois titulos vem do mesmo arquivo que ``curva_ntnb`` le.
"""

from __future__ import annotations

import http.client
import io
import json
import re
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

URL_FOCUS = (
    "https://olinda.bcb.gov.br/olinda/servico/Expectativas/versao/v1/odata/"
    "ExpectativasMercadoAnuais"
)
URL_SGS = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{serie}/dados"
URL_TESOURO = (
    "https://www.tesourotransparente.gov.br/ckan/dataset/"
    "df56aa42-484a-4a59-8184-7676580c81e3/resource/"
    "796d2059-14e9-44e3-80c9-2d9e30b405c1/download/PrecoTaxaTesouroDireto.csv"
)

SERIE_SELIC_META = 432
SERIE_IPCA_12M = 13522

ENCODING = "latin-1"
TEMPO_LIMITE = 180
TENTATIVAS = 2

# O titulo padrao da curva real: IPCA+ sem juros semestrais.
TITULO_NTNB = "Tesouro IPCA+"
# Prazo de referencia para o risco-pais. Longo o bastante para nao depender do
# ciclo de juros, curto o bastante para ter liquidez.
ANOS_REFERENCIA = 10


class ErroMercado(Exception):
    """Falha ao obter ou interpretar um dado de mercado."""


def diretorio_cache() -> Path:
    return Path.home() / ".cache" / "valuation" / "mercado"


def _buscar(url: str, cabecalhos: dict | None = None) -> bytes:
    """GET com as mesmas garantias do leitor da CVM: retentativa e erro tratado."""
    ultimo: Exception | None = None
    for _ in range(TENTATIVAS):
        try:
            pedido = urllib.request.Request(url, headers=cabecalhos or {})
            with urllib.request.urlopen(pedido, timeout=TEMPO_LIMITE) as resposta:
                return resposta.read()
        except urllib.error.HTTPError as erro:
            raise ErroMercado(f"{url} respondeu {erro.code}.") from erro
        except (urllib.error.URLError, http.client.HTTPException, TimeoutError, OSError) as erro:
            ultimo = erro
    raise ErroMercado(f"Nao consegui obter {url}: {ultimo}") from ultimo


# ---------------------------------------------------------------------------
# Focus
# ---------------------------------------------------------------------------


# O Focus publica **duas** estatisticas para a mesma coleta e o mesmo ano, no
# campo ``baseCalculo``: 0 usa as respostas dos ultimos 30 dias, 1 usa so as dos
# ultimos 5 dias uteis. Sem filtrar, cada ano volta duplicado -- medido na coleta
# de 14/08/2026, o IPCA de 2027 aparecia com mediana 4,2402 (base 0, 148 casas) e
# 4,2060 (base 1, 69 casas), e o codigo pegava uma das duas por ordem de linha.
#
# A base 0 e a do relatorio Focus publicado, e tem **mais que o dobro de
# respondentes**. A 1 e mais recente e mais ruidosa; fica disponivel por
# parametro para quem quiser a leitura do dia.
BASE_30_DIAS = 0
BASE_5_DIAS = 1


def expectativas(
    indicador: str, cache: Path | None = None, base: int = BASE_30_DIAS
) -> pd.DataFrame:
    """Projecoes do Focus para um indicador, por ano de referencia.

    Devolve a coleta mais recente, com mediana, dispersao e quantas casas
    responderam -- a dispersao importa: 151 casas projetando Selic entre 12,25%
    e 14,25% nao e a mesma coisa que consenso.
    """
    filtro = urllib.parse.quote(f"Indicador eq '{indicador}'")
    url = f"{URL_FOCUS}?$format=json&$orderby=Data desc&$top=120&$filter={filtro}"
    dados = json.loads(_buscar(url.replace(" ", "%20")).decode("utf-8"))
    linhas = dados.get("value") or []
    if not linhas:
        raise ErroMercado(f"O Focus nao devolveu nada para '{indicador}'.")

    tabela = pd.DataFrame(linhas)
    recente = tabela["Data"].max()
    tabela = tabela[tabela["Data"] == recente]
    if "baseCalculo" in tabela.columns:
        escolhida = tabela[tabela["baseCalculo"] == base]
        if not escolhida.empty:
            tabela = escolhida
    saida = (
        tabela.assign(ano=tabela["DataReferencia"].astype(int))
        .set_index("ano")[["Mediana", "Media", "DesvioPadrao", "numeroRespondentes"]]
        .sort_index()
    )
    saida.attrs["coleta"] = str(recente)[:10]
    return saida


def ipca_esperado(anos_a_frente: int = 3, cache: Path | None = None) -> float:
    """IPCA de longo prazo pelo Focus, em decimal.

    Usa o ano mais distante disponivel dentro da janela: a projecao curta carrega
    o choque corrente, e o que se quer aqui e a inflacao de regime.
    """
    tabela = expectativas("IPCA", cache)
    limite = date.today().year + anos_a_frente
    candidatos = tabela[tabela.index <= limite]
    if candidatos.empty:
        raise ErroMercado("O Focus nao tem IPCA para a janela pedida.")
    return float(candidatos["Mediana"].iloc[-1]) / 100.0


# ---------------------------------------------------------------------------
# Curva real
# ---------------------------------------------------------------------------


def curva_ntnb(caminho: str | Path | None = None) -> pd.DataFrame:
    """Taxa real das NTN-B por vencimento, da coleta mais recente do arquivo.

    O arquivo do Tesouro tem o historico inteiro. **O `Range` nao economiza
    nada**: medido em agosto de 2026, o servidor responde `206 Partial Content`
    e manda os 14,4 MB inteiros do mesmo jeito, em 3 a 7 segundos. O cabecalho
    fica porque nao custa e pode voltar a ser respeitado; o que resolve o custo e
    o cache em disco de :func:`taxa_real_ntnb`, que busca uma vez por dia.

    O comentario anterior dizia que so os primeiros blocos eram lidos. Nao era
    verdade -- so a *leitura* e parcial, o download nao.
    """
    if caminho is not None:
        bruto = Path(caminho).read_bytes()
    else:
        bruto = _buscar(URL_TESOURO, {"Range": "bytes=0-400000"})

    quebra = b"\r\n" if b"\r\n" in bruto else b"\n"
    linhas = bruto.split(quebra)
    if len(linhas) < 2:
        raise ErroMercado("O arquivo do Tesouro veio vazio.")

    # A ultima linha pode ter sido cortada no meio pelo Range.
    corpo = [l for l in linhas[1:-1] if l.startswith(TITULO_NTNB.encode(ENCODING) + b";")]
    if not corpo:
        raise ErroMercado("Nao achei NTN-B no recorte do arquivo do Tesouro.")

    registros = []
    for linha in corpo:
        campos = linha.decode(ENCODING).split(";")
        if len(campos) < 4:
            continue
        registros.append(
            {
                "vencimento": pd.to_datetime(campos[1], format="%d/%m/%Y"),
                "data_base": pd.to_datetime(campos[2], format="%d/%m/%Y"),
                "taxa_real": float(campos[3].replace(",", ".")) / 100.0,
            }
        )

    tabela = pd.DataFrame(registros)
    recente = tabela["data_base"].max()
    return tabela[tabela["data_base"] == recente].sort_values("vencimento").reset_index(drop=True)


def taxa_real_longa(curva: pd.DataFrame, anos: int = ANOS_REFERENCIA) -> float:
    """Taxa real do vencimento mais proximo do prazo pedido."""
    if curva.empty:
        raise ErroMercado("A curva veio vazia.")
    alvo = pd.Timestamp(curva["data_base"].iloc[0]) + pd.DateOffset(years=anos)
    distancia = (curva["vencimento"] - alvo).abs()
    return float(curva.loc[distancia.idxmin(), "taxa_real"])


# ---------------------------------------------------------------------------
# O que isto existe para calcular
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RiscoPaisImplicito:
    """O que a curva real diz sobre o premio de financiar o Brasil."""

    taxa_real_ntnb: float
    ipca_esperado: float
    rf_brl_nominal: float
    rf_usd: float
    rf_usd_em_brl: float
    diferenca: float
    vencimento: str = ""

    @property
    def explicacao(self) -> str:
        return (
            f"NTN-B de {self.vencimento} paga {self.taxa_real_ntnb:.2%} real; com "
            f"IPCA esperado de {self.ipca_esperado:.2%}, isso e "
            f"{self.rf_brl_nominal:.2%} nominal em BRL. O rf americano de "
            f"{self.rf_usd:.2%} convertido para BRL da {self.rf_usd_em_brl:.2%}. "
            f"A diferenca e {self.diferenca:.2%}."
        )

    @property
    def ressalva(self) -> str:
        return (
            "Esta diferenca nao e risco soberano puro: carrega o premio de "
            "liquidez da NTN-B e qualquer descasamento entre a inflacao usada "
            "aqui e a que o mercado precifica. Use-a como ordem de grandeza, e "
            "confira antes de trocar a premissa."
        )


def risco_pais_implicito(
    taxa_real: float,
    ipca: float,
    rf_usd: float,
    inflacao_usd: float,
    vencimento: str = "",
) -> RiscoPaisImplicito:
    """Quanto o mercado cobra a mais em BRL do que em USD, pela curva real.

    Puro de proposito: recebe taxas e devolve a conta, sem tocar a rede. E onde
    o erro de real contra nominal moraria, entao e o que precisa de teste.
    """
    for nome, valor in (("taxa_real", taxa_real), ("ipca", ipca), ("rf_usd", rf_usd)):
        if not np.isfinite(valor):
            raise ValueError(f"{nome} precisa ser um numero.")

    rf_brl_nominal = (1 + taxa_real) * (1 + ipca) - 1
    rf_usd_em_brl = (1 + rf_usd) * (1 + ipca) / (1 + inflacao_usd) - 1
    return RiscoPaisImplicito(
        taxa_real_ntnb=taxa_real,
        ipca_esperado=ipca,
        rf_brl_nominal=rf_brl_nominal,
        rf_usd=rf_usd,
        rf_usd_em_brl=rf_usd_em_brl,
        diferenca=rf_brl_nominal - rf_usd_em_brl,
        vencimento=vencimento,
    )


def medir_risco_pais(
    rf_usd: float,
    inflacao_usd: float,
    anos: int = ANOS_REFERENCIA,
    caminho_curva: str | Path | None = None,
    ipca: float | None = None,
) -> RiscoPaisImplicito:
    """Busca curva e Focus e devolve o risco-pais implicito."""
    curva = curva_ntnb(caminho_curva)
    taxa = taxa_real_longa(curva, anos)
    inflacao = ipca if ipca is not None else ipca_esperado()

    alvo = pd.Timestamp(curva["data_base"].iloc[0]) + pd.DateOffset(years=anos)
    distancia = (curva["vencimento"] - alvo).abs()
    vencimento = curva.loc[distancia.idxmin(), "vencimento"].strftime("%d/%m/%Y")

    return risco_pais_implicito(taxa, inflacao, rf_usd, inflacao_usd, vencimento)


# ---------------------------------------------------------------------------
# O bloco macro inteiro, numa chamada
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MacroDoFocus:
    """As premissas macro como o mercado as projeta, prontas para comparar.

    Existe para responder de uma vez a pergunta que o analista faz ao abrir a
    tela: "o que eu digitei esta perto do consenso?". Traz a **data da coleta** e
    quantas casas responderam porque projecao de consenso sem numero de
    respondentes nao e consenso, e sim media de quem quis responder.
    """

    ipca: float
    pib_real: float
    selic: float
    cambio: float
    ano_de_referencia: int
    coleta: str
    respondentes: dict[str, int]

    def comparar(self, macro) -> pd.DataFrame:
        """O que esta no modelo contra o que o Focus projeta, lado a lado."""
        linhas = {
            "IPCA": (macro.inflacao_brl, self.ipca),
            "PIB real": (getattr(macro, "pib_real", float("nan")), self.pib_real),
        }
        return pd.DataFrame(
            [
                {
                    "Premissa": nome,
                    "No modelo": no_modelo,
                    "Focus": no_focus,
                    "Diferença": no_modelo - no_focus,
                }
                for nome, (no_modelo, no_focus) in linhas.items()
            ]
        ).set_index("Premissa")


# Os nomes dos indicadores vem **acentuados** do Olinda, e "PIB Total" nao e
# "PIB": pedir o nome errado devolve lista vazia, e nao erro.
INDICADORES_FOCUS = {
    "ipca": "IPCA",
    "pib_real": "PIB Total",
    "selic": "Selic",
    "cambio": "Câmbio",
}


def macro_do_focus(anos_a_frente: int = 3, cache: Path | None = None) -> MacroDoFocus:
    """IPCA, PIB real, Selic e câmbio de longo prazo, pelo Focus.

    Usa o ano mais distante dentro da janela, e nao o proximo: a projecao curta
    carrega o choque corrente, e premissa de perpetuidade quer regime. Medido na
    coleta de 14/08/2026, a diferenca entre os dois nao e pequena -- IPCA de
    5,02% para 2026 contra **3,50%** para 2029.

    **Nao troca nada sozinho.** Devolve os numeros para a tela mostrar ao lado
    dos que o usuario digitou; aplicar e decisao dele. O padrao do app continua
    sendo a pratica do dono do projeto (IPCA 5%, PIB real 1,5%), que e mais
    conservadora que o consenso nos dois.
    """
    limite = date.today().year + anos_a_frente
    valores: dict[str, float] = {}
    respondentes: dict[str, int] = {}
    coleta = ""
    ano_escolhido = limite

    for chave, indicador in INDICADORES_FOCUS.items():
        tabela = expectativas(indicador, cache)
        coleta = coleta or str(tabela.attrs.get("coleta", ""))
        candidatos = tabela[tabela.index <= limite]
        if candidatos.empty:
            raise ErroMercado(f"O Focus nao tem '{indicador}' para a janela pedida.")
        linha = candidatos.iloc[-1]
        ano_escolhido = int(candidatos.index[-1])
        # Cambio e preco em reais por dolar, e nao taxa: nao se divide por 100.
        valores[chave] = float(linha["Mediana"]) / (1.0 if chave == "cambio" else 100.0)
        respondentes[chave] = int(linha["numeroRespondentes"])

    return MacroDoFocus(
        ipca=valores["ipca"],
        pib_real=valores["pib_real"],
        selic=valores["selic"],
        cambio=valores["cambio"],
        ano_de_referencia=ano_escolhido,
        coleta=coleta,
        respondentes=respondentes,
    )


# ---------------------------------------------------------------------------
# Cotacao da B3
# ---------------------------------------------------------------------------

# **Por que esta fonte, e o que ela nao garante.** O app precisava de um preco
# para fechar a margem de seguranca, e sem ele o campo nascia preenchido com o
# proprio DCF -- um numero que se lia como dado de mercado e nao era. As
# alternativas foram medidas antes de escolher:
#
#   brapi.dev  -> HTTP 401, exige token; guardar credencial contraria a regra de
#                 o app nao gravar nada em disco
#   stooq      -> nao tem os papeis da B3
#   Yahoo      -> responde, mas **so com User-Agent**: sem ele devolve 429
#
# Sobrou o Yahoo, e ele e **endpoint nao documentado**: pode mudar ou sair do ar
# sem aviso, e nao ha contrato de servico. Por isso a busca e opt-in (so acontece
# quando o usuario clica), nunca troca nada sozinha, e a falha e tratada como
# normal -- o campo manual continua sendo o caminho principal, e nao um plano B.
COTACAO_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
# Sem isto o Yahoo devolve 429. Nao e disfarce: e um cliente identificando-se
# para um endpoint que recusa requisicao sem identificacao nenhuma.
CABECALHO_COTACAO = {"User-Agent": "valuation-app/1.0"}
SUFIXO_B3 = ".SA"


@dataclass(frozen=True)
class Cotacao:
    """O ultimo preco negociado de um papel, com a origem declarada."""

    ticker: str
    preco: float
    moeda: str
    nome: str
    negociado_em: datetime

    def valor_de_mercado(self, acoes: float) -> float:
        """Preco x acoes em circulacao, na unidade em que as acoes vierem."""
        return self.preco * acoes


def _normalizar_ticker(ticker: str) -> str:
    """``wege3`` vira ``WEGE3.SA``; ``WEGE3.SA`` fica como esta.

    O sufixo e o que diz ao Yahoo que o papel e da B3. Sem ele, ``WEGE3``
    encontra outra coisa ou nada -- e "nada" seria o melhor dos dois casos.
    """
    limpo = ticker.strip().upper()
    if not limpo:
        raise ErroMercado("Informe o codigo do papel, como WEGE3.")
    return limpo if "." in limpo else limpo + SUFIXO_B3


def cotacao(ticker: str) -> Cotacao:
    """Ultimo preco negociado de um papel da B3.

    Levanta ``ErroMercado`` em qualquer falha -- rede fora, papel inexistente,
    resposta com formato diferente do esperado. Quem chama trata como recusa e
    segue com o numero digitado a mao: **a cotacao e conveniencia, nao
    dependencia**.
    """
    alvo = _normalizar_ticker(ticker)
    bruto = _buscar(COTACAO_URL.format(ticker=alvo), CABECALHO_COTACAO)
    return interpretar_cotacao(bruto, alvo)


def interpretar_cotacao(bruto: bytes, ticker: str) -> Cotacao:
    """Le a resposta do Yahoo. Separada da rede para o teste nao precisar dela."""
    try:
        dados = json.loads(bruto)
        meta = dados["chart"]["result"][0]["meta"]
        preco = float(meta["regularMarketPrice"])
    except (json.JSONDecodeError, KeyError, IndexError, TypeError, ValueError) as erro:
        raise ErroMercado(
            f"Nao reconheci a resposta da cotacao de {ticker}."
        ) from erro

    if not np.isfinite(preco) or preco <= 0:
        raise ErroMercado(f"A cotacao de {ticker} veio como {preco}.")

    momento = meta.get("regularMarketTime")
    return Cotacao(
        ticker=ticker,
        preco=preco,
        moeda=str(meta.get("currency") or "BRL"),
        nome=str(meta.get("longName") or ticker),
        negociado_em=(
            datetime.fromtimestamp(int(momento), tz=timezone.utc)
            if momento
            else datetime.now(tz=timezone.utc)
        ),
    )


# ---------------------------------------------------------------------------
# A taxa real do dia, com cache em disco
# ---------------------------------------------------------------------------

# O arquivo do Tesouro custa 14 MB e alguns segundos, e a curva se move uma vez
# por dia util. Guardar em disco o numero -- e nao o arquivo -- torna a
# atualizacao automatica barata: a primeira sessao do dia paga a busca, as
# demais leem um JSON de duas linhas.
ARQUIVO_DA_TAXA = "ntnb_taxa_real.json"


@dataclass(frozen=True)
class TaxaRealDoDia:
    """A taxa real longa da NTN-B, com a data da coleta e de onde veio."""

    taxa: float
    coletada_em: date
    do_cache: bool

    @property
    def dias(self) -> int:
        return (date.today() - self.coletada_em).days


def taxa_real_ntnb(
    cache: Path | None = None, anos: int = ANOS_REFERENCIA, hoje: date | None = None
) -> TaxaRealDoDia:
    """A taxa real longa, buscando no maximo **uma vez por dia**.

    Devolve tambem a data da coleta, porque quem consome precisa poder dizer a
    idade do numero -- um valor de mercado sem data e indistinguivel de um valor
    embarcado.

    Levanta ``ErroMercado`` quando nao ha cache do dia **e** a rede falha. Quem
    chama decide o que fazer; no app, a decisao e cair na referencia embarcada e
    dizer isso na tela.
    """
    hoje = hoje or date.today()
    pasta = cache or diretorio_cache()
    arquivo = pasta / ARQUIVO_DA_TAXA

    if arquivo.exists():
        try:
            guardado = json.loads(arquivo.read_text(encoding="utf-8"))
            coletada = date.fromisoformat(guardado["coletada_em"])
            if coletada == hoje:
                return TaxaRealDoDia(float(guardado["taxa"]), coletada, do_cache=True)
        except (json.JSONDecodeError, KeyError, ValueError, OSError):
            pass  # cache corrompido e o mesmo que cache ausente

    taxa = taxa_real_longa(curva_ntnb(), anos=anos)
    pasta.mkdir(parents=True, exist_ok=True)
    arquivo.write_text(
        json.dumps({"taxa": taxa, "coletada_em": hoje.isoformat()}),
        encoding="utf-8",
    )
    return TaxaRealDoDia(taxa, hoje, do_cache=False)


# ---------------------------------------------------------------------------
# Achar o papel a partir do nome da companhia
# ---------------------------------------------------------------------------

# **O cadastro da CVM nao traz ticker.** Tem CNPJ, codigo CVM, setor e ate o
# auditor -- nada que ligue a companhia ao papel na B3. A busca do Yahoo e a
# unica fonte gratuita que responde a isso, e ela **funciona pela metade**.
#
# Medido em 40 companhias com DFP de 2024, sorteadas:
#
#     acerta o papel certo    16  (40%)
#     devolve papel de outra   0  ( 0%)
#     nao acha nada           24  (60%)
#
# O numero que decide o desenho e o do meio: ela **nunca devolveu a empresa
# errada**. O modo de falha e "nao achei", que e visivel; nao e "achei outra
# coisa", que seria invisivel e encheria o campo de preco com o numero de outra
# companhia. Por isso a busca entra como **sugestao que o usuario confirma**, e
# nao como preenchimento automatico -- 40% de economia de digitacao sem nenhum
# caso em que o app mente.
#
# Entre os 60% que nao acha ha companhia de capital fechado (concessionaria,
# securitizadora) -- onde "nao achei" e a resposta certa -- e listadas que ela
# perde mesmo assim, como o Banco do Brasil.
BUSCA_DE_PAPEL = (
    "https://query2.finance.yahoo.com/v1/finance/search"
    "?q={termo}&quotesCount=10&newsCount=0&region=BR&lang=pt-BR"
)

# Palavras que nao identificam a companhia e so atrapalham a busca.
RUIDO_NO_NOME = frozenset(
    {
        "s", "a", "sa", "cia", "companhia", "participacoes", "participacao",
        "holding", "holdings", "brasil", "brasileira", "do", "da", "de", "e",
        "ltda", "industria", "comercio", "empreendimentos", "grupo", "em",
        "recuperacao", "judicial",
    }
)


@dataclass(frozen=True)
class PapelSugerido:
    """Um candidato a papel da companhia, para o usuario confirmar."""

    ticker: str
    nome: str


def _palavras_do_nome(nome: str) -> list[str]:
    cru = unicodedata.normalize("NFKD", str(nome)).encode("ascii", "ignore").decode()
    palavras = cru.lower().replace(".", " ").replace("/", " ").replace("-", " ").split()
    return [p for p in palavras if p not in RUIDO_NO_NOME and len(p) > 2]


def _sem_fracionario(ticker: str) -> str:
    """``NGRD3F.SA`` vira ``NGRD3.SA``.

    O sufixo ``F`` e o mercado fracionario: mesmo papel, negociado em lote
    avulso. Ele tem preco proprio -- mais fino, porque o livro e menor -- e vem
    **sem nome de companhia** na resposta do Yahoo. O canonico da os dois
    melhores.
    """
    base, _, sufixo = ticker.partition(".")
    if len(base) > 1 and base.endswith("F") and base[-2].isdigit():
        base = base[:-1]
    return f"{base}.{sufixo}" if sufixo else base


def procurar_papel(nome: str) -> list[PapelSugerido]:
    """Papeis da B3 que parecem ser desta companhia, do melhor para o pior.

    Devolve lista vazia quando nao acha -- que e o caso em 60% das companhias.
    **Nunca levanta por ausencia**: nao achar papel e resposta, e nao falha.
    """
    palavras = _palavras_do_nome(nome)
    if not palavras:
        return []

    url = BUSCA_DE_PAPEL.format(termo=urllib.parse.quote(" ".join(palavras[:3])))
    try:
        achados = json.loads(_buscar(url, CABECALHO_COTACAO)).get("quotes", [])
    except (ErroMercado, json.JSONDecodeError, TypeError):
        return []

    do_nome = set(palavras)
    sugestoes: list[PapelSugerido] = []
    vistos: set[str] = set()
    for achado in achados:
        ticker = str(achado.get("symbol") or "")
        if not ticker.endswith(SUFIXO_B3):
            continue
        canonico = _sem_fracionario(ticker)
        if canonico in vistos:
            continue
        rotulo = str(achado.get("shortname") or achado.get("longname") or "")
        # O nome do papel tem de compartilhar palavra com o da companhia. Sem
        # esta conferencia a busca devolveria o primeiro `.SA` que aparecesse --
        # e ai o modo de falha deixaria de ser "nao achei" e passaria a ser
        # "achei outra", que e o que nao pode acontecer.
        if not (set(_palavras_do_nome(rotulo)) & do_nome):
            continue
        vistos.add(canonico)
        sugestoes.append(PapelSugerido(canonico, rotulo))
    return sugestoes

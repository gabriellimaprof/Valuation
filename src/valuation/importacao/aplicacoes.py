"""Titulos e valores mobiliarios: quando sao caixa, e quando nao sao.

A divida liquida abate o TVM **circulante** (`1.01.02`) e deixa de fora o **nao
circulante** (`1.02.01.01/.02/.03`). As duas escolhas sao discutiveis, e por
razoes opostas.

**O TVM de longo prazo costuma ser caixa.** Conferido contra o que as companhias
publicam em 2024, nas quatro em que ele mais pesa: a Ultrapar o abate (11.163 no
app, 7.756 publicados, e a diferenca e exatamente a linha); a Embraer define a
divida liquida com "investimentos financeiros de **curto e longo prazo**"; a
Cyrela publica a linha "Titulos e Valores Mobiliarios LP" com **2.256**, que e o
que o app le; e a Petrobras inclui o titulo liquido "ainda que o prazo de
vencimento seja superior a 12 meses" -- a divida liquida dela, 323.489, fica a
0,09% da ampla do app.

**E o TVM nem sempre e caixa, em nenhum dos dois prazos.** O plano da CVM so
separa pela *mensuracao* do IFRS 9 -- valor justo no resultado, em ORA, custo
amortizado --, e isso nao diz se o dinheiro esta livre. Quem diz e a subconta
que a companhia abre embaixo, com o rotulo dela. Medido em 2024: das 135
companhias com TVM de longo prazo, **72 abrem subconta**, e o que aparece fora
de "aplicacao" e pouco, mas grande:

    Simpar       2.244  Instrumentos financeiros derivativos
    Localiza     1.216  Certificados de deposito bancario vinculados
    Serena         488  Caixa restrito
    Bradsaude      139  Aplicacoes Garantidoras de Provisoes Tecnicas

E a participacao societaria -- o caso classico de "TVM que e investimento" --
nao apareceu no longo prazo de ninguem: apareceu no **circulante** da CSN,
"Acoes Usiminas", R$ 861 mi, que a divida liquida padrao abate como se fosse
caixa.

Por isso a classificacao e de **linha**, e vale para os dois prazos. Ela tem tres
saidas:

* ``caixa`` -- abate a divida;
* ``vinculado`` -- abate, mas so paga a obrigacao a que esta preso. A Serena o
  soma ao caixa (1.428 + 488 = 1.916, e ela publica "caixa total ajustado de
  R$ 1,92 bi"), entao ficar fora contrariaria a propria companhia; o que se faz
  e dizer que ele esta ali. A Localiza tambem: a divida liquida que ela publica
  (R$ 30,1 bi) so se reconstroi abatendo o CDB vinculado de longo prazo;
* ``nao_e_caixa`` -- derivativo, lastro de provisao tecnica, participacao em
  outra companhia, carteira de credito, conta que nem e aplicacao.

**A seguradora e o caso que o rotulo da linha nao denuncia, e a companhia sim.**
A Porto Seguro tem R$ 11 bi de TVM de longo prazo em contas que so dizem "custo
amortizado" -- a carteira que lastreia a provisao tecnica. O sinal esta no resto
da demonstracao: quem publica **premio ou contraprestacao na receita e sinistro
no custo**, ou **provisao tecnica no passivo**, opera seguro ou plano de saude.
Ver :func:`opera_seguro` para a medicao e para o que ela deixa passar.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .importador import colunas_de_periodo

TVM_CIRCULANTE = "1.01.02"
REALIZAVEL_A_LONGO_PRAZO = "1.02.01"

# **So as tres linhas de aplicacao financeira.** `1.02.01.0\d` alcancaria contas
# a receber (.04), estoques (.05) e tributos diferidos (.06) do realizavel a
# longo prazo -- e foi o que inflou a Vale para R$ 59 bi na primeira medicao,
# quase toda a divida liquida dela.
BALDES_DO_IFRS_9 = ("01", "02", "03")

CAIXA = "caixa"
VINCULADO = "vinculado"
NAO_E_CAIXA = "nao_e_caixa"

# O que abate a divida. `vinculado` entra porque as companhias o somam ao caixa
# -- ver a nota do modulo sobre a Serena.
ABATE_A_DIVIDA = frozenset({CAIXA, VINCULADO})

# Ordem importa: o primeiro sinal que casa decide. "Aplicacoes **garantidoras**
# de provisoes tecnicas" tem de cair em lastro antes de "garantia" a mandar para
# vinculado.
#
# `\bacoes\b` e com fronteira de palavra de proposito: sem ela, "aplic**acoes**
# financeiras" -- o rotulo de quase toda linha desta arvore -- viraria
# participacao societaria.
SINAIS: tuple[tuple[str, re.Pattern, str], ...] = (
    (
        NAO_E_CAIXA,
        re.compile(r"derivativ|\bswaps?\b|\bhedge\b"),
        "Derivativo: protege a dívida, não a paga. Quando cobre dívida em outra "
        "moeda, a companhia costuma somá-lo à dívida — mas não é caixa.",
    ),
    (
        NAO_E_CAIXA,
        re.compile(r"garantidora|provis\w* tecnic"),
        "Lastro de provisão técnica: é a reserva que a regulação exige contra "
        "sinistros e eventos, e já tem destino.",
    ),
    (
        NAO_E_CAIXA,
        re.compile(r"\bacoes\b|participac|instrumentos? patrimonia"),
        "Participação em outra companhia: é investimento, vale o preço da ação e "
        "não o saldo, e não paga dívida sem ser vendida. Na ponte, o lugar dela é "
        "em ativos não operacionais.",
    ),
    (
        NAO_E_CAIXA,
        re.compile(r"operac\w* de credito|carteira de credito"),
        "Carteira de crédito: é o negócio de uma financeira do grupo e rende "
        "dentro da operação. A Cyrela publica a dívida líquida com e sem a da "
        "CashMe por isso.",
    ),
    (
        NAO_E_CAIXA,
        re.compile(r"partes? relacionad"),
        "Crédito a parte relacionada: é empréstimo a outra empresa do grupo ou "
        "do controlador, e não aplicação de tesouraria.",
    ),
    (
        NAO_E_CAIXA,
        re.compile(r"adiantamento"),
        "Não é aplicação financeira: a companhia publicou outra conta dentro do "
        "grupo de aplicações.",
    ),
    (
        VINCULADO,
        # "Caixa Margem" e margem depositada em bolsa contra derivativo: nao sai
        # enquanto a posicao estiver aberta.
        re.compile(
            r"vinculad|restrit|restric|cauc|escrow|conta reserva|garantia|\bmargem\b"
        ),
        "Vinculado a uma obrigação: só paga a dívida a que está preso. A companhia "
        "costuma somá-lo ao caixa; para medir o que ela tem livre, tire-o.",
    ),
)

MOTIVO_CAIXA = "Aplicação financeira sem sinal de restrição no rótulo publicado."

# **O teto, e nao a medida.** A regulacao exige ativo garantidor contra a
# provisao tecnica, mas nao o balanco inteiro: a Hapvida tem R$ 8,2 bi de TVM
# circulante, e quanto disso e garantidor so a nota explicativa diz. A linha fica
# fora da ampla -- errar para o lado de nao dar ao acionista o dinheiro dos
# segurados --, e o motivo diz que e uma parte, e onde conferir.
MOTIVO_LASTRO_DE_SEGURADORA = (
    "Carteira de seguradora ou operadora de saúde: a companhia publica prêmio e "
    "sinistro, ou provisão técnica, e parte desta carteira é ativo garantidor "
    "dessa obrigação — que não está na ponte. O rótulo não diz quanto: a nota de "
    "ativos garantidores diz. Somar tudo ao caixa daria ao acionista o dinheiro "
    "dos segurados."
)

# O titulo que a propria companhia declara livre continua caixa mesmo numa
# seguradora: a Bradsaude separa "Aplicacoes livres" (400) das "Garantidoras de
# Provisoes Tecnicas" (139), e as duas leituras estao certas.
DECLARADO_LIVRE = re.compile(r"\blivres?\b")

# **Quem opera seguro ou plano de saude.** A receita com premio ou contraprestacao
# **e** um custo com sinistro ou evento, ou a provisao tecnica no passivo.
#
# Medido nas 415 companhias de 2024, a regra marca **5**: Porto Seguro,
# Bradsaude, Hapvida, Qualicorp e Hospital Care Caledonia -- todas de seguro ou
# saude. Entre as que tem TVM de longo prazo, pega Porto Seguro (11.014),
# Hapvida (481) e Bradsaude (400 livres, que ficam), **95% do valor**. A **Porto
# Saude** (674) passava: ela ja fala a lingua do IFRS 17 -- ver logo abaixo.
#
# **Cada metade da regra sozinha erra.** "premio" e "contraprestacao" soltos no
# passivo marcaram 12 companhias a mais -- "Contraprestacao a Pagar a Clientes"
# da Frasle, "Premio de opcao de acoes" da Mills, a contraprestacao contingente
# de aquisicao da EDP. Por isso a receita precisa estar em `3.01` e vir
# acompanhada de sinistro, e no passivo so vale "provisao tecnica".
RECEITA_DE_SEGURO = re.compile(r"premio|contraprestac")
CUSTO_DE_SEGURO = re.compile(r"sinistr|eventos indenizaveis|eventos/sinistros")
PROVISAO_TECNICA = re.compile(r"provis\w* tecnic")

# **E o vocabulario do IFRS 17**, que trocou premio, sinistro e provisao tecnica
# por receita de seguro e contrato de seguro a partir de 2023. A Porto Saude
# publica "Receita de seguro" e "Contratos de seguros", e nenhuma das palavras
# antigas -- por isso passava.
#
# Medido nas 415 companhias de 2024: a receita de seguro em `3.01` marca as
# quatro seguradoras e operadoras (Porto Seguro, Porto Saude, Bradsaude,
# Hapvida); o passivo de contrato de seguro acrescenta a **Rede D'Or**, dona da
# SulAmerica, e a Alianca da Bahia. "Seguros" solto e **despesa com apolice
# contratada** -- geradora, concessionaria, varejo, "Seguros a pagar" -- e nao
# pode marcar ninguem: por isso a receita exige "receita de" e o passivo exige
# "contrato".
RECEITA_DE_SEGURO_IFRS_17 = re.compile(r"receita de (?:contratos? de )?seguros?")
PASSIVO_DE_CONTRATO_DE_SEGURO = re.compile(r"contratos? de seguros?")

# Diferenca entre o grupo e a soma das subcontas abaixo da qual ela e
# arredondamento, e nao uma parte que a companhia deixou sem abrir.
FOLGA_DO_RESIDUO = 0.005


@dataclass(frozen=True)
class LinhaDeTitulo:
    """Uma linha de TVM publicada, com o que ela e."""

    codigo: str
    rotulo: str
    valor: float
    classe: str
    motivo: str

    @property
    def longo_prazo(self) -> bool:
        return self.codigo.startswith(REALIZAVEL_A_LONGO_PRAZO + ".")

    @property
    def abate_a_divida(self) -> bool:
        return self.classe in ABATE_A_DIVIDA


def _sem_acento(texto: str) -> str:
    return (
        unicodedata.normalize("NFKD", str(texto))
        .encode("ascii", "ignore")
        .decode()
        .lower()
    )


def classificar(rotulo: str) -> tuple[str, str]:
    """A classe de uma linha de TVM pelo rotulo publicado, e o porque."""
    texto = _sem_acento(rotulo)
    for classe, padrao, motivo in SINAIS:
        if padrao.search(texto):
            return classe, motivo
    return CAIXA, MOTIVO_CAIXA


def plano_industrial(detalhe: pd.DataFrame | None) -> bool:
    """A arvore e do plano industrial, onde estes codigos significam o que aqui se le.

    No plano de banco e seguradora `1.02.01` e outra conta, e a divida liquida
    nem se aplica. O rotulo do grupo decide, como em todo o importador: codigo
    muda de significado entre planos, rotulo nao.
    """
    if detalhe is None or detalhe.empty or "codigo" not in detalhe.columns:
        return False
    grupo = detalhe[detalhe["codigo"].astype(str) == REALIZAVEL_A_LONGO_PRAZO]
    return not grupo.empty and "realiz" in _sem_acento(grupo["rotulo"].iloc[0])


def opera_seguro(detalhe: pd.DataFrame | None) -> bool:
    """A companhia opera seguro ou plano de saude? Ver `RECEITA_DE_SEGURO`."""
    if detalhe is None or detalhe.empty or "codigo" not in detalhe.columns:
        return False
    codigos = detalhe["codigo"].astype(str)
    rotulos = detalhe["rotulo"].map(_sem_acento)
    receita = rotulos[codigos.str.startswith("3.01")].str.contains(RECEITA_DE_SEGURO)
    custo = rotulos[codigos.str.startswith("3.")].str.contains(CUSTO_DE_SEGURO)
    provisao = rotulos[codigos.str.startswith("2.")].str.contains(PROVISAO_TECNICA)
    receita_ifrs_17 = rotulos[codigos.str.startswith("3.01")].str.contains(
        RECEITA_DE_SEGURO_IFRS_17
    )
    passivo_ifrs_17 = rotulos[codigos.str.startswith("2.")].str.contains(
        PASSIVO_DE_CONTRATO_DE_SEGURO
    )
    return bool(
        (receita.any() and custo.any())
        or provisao.any()
        or receita_ifrs_17.any()
        or passivo_ifrs_17.any()
    )


# **Na seguradora, parte das "outras despesas operacionais" e a propria
# operacao.** O plano da CVM nao tem linha de sinistro no plano industrial, e a
# Porto Seguro lanca o custo principal dentro de `3.04.05`: "Despesas de seguro"
# (-21.614 em 2024), resseguro (-56), custo de aquisicao (-774), custo dos
# servicos prestados (-241). O app trata `3.04.05` inteira como item nao
# recorrente -- e, ali, tirava o sinistro da margem.
#
# Medido nas 8 companhias do sinal de seguradora em 2024: so a Porto Seguro lanca
# a operacao ali. Porto Saude, Bradsaude e Hapvida a lancam no custo dos servicos
# (3.02), e a margem recorrente delas ja batia com a reportada. De 2021 a 2025,
# em todo o universo, **so tres** companhias tem vocabulario de seguro dentro de
# 3.04.04/3.04.05: a Porto Seguro nos cinco exercicios, pesando de 7 a 29 vezes o
# EBIT -- com os rotulos antigos ("Sinistros retidos", "Variacao das provisoes
# tecnicas") ate 2022 e os do IFRS 17 depois, e o padrao pega os dois --, e Eneva
# e OceanPact, que nao operam seguro e lancam **indenizacao de seguro recebida**
# em outras receitas, de 1% a 4% do EBIT. Essa e evento de verdade, e fica.
#
# O padrao so vale para quem `opera_seguro`: "custos dos servicos prestados" e
# operacao de uma seguradora, e numa industrial o mesmo rotulo seria outra
# discussao.
OPERACAO_DE_SEGURO = re.compile(
    r"segur|sinistr|resseguro|retrocess|provis\w* tecnic|previdenc"
    r"|custos? de aquisic|servicos prestados|salvados|ressarciment"
)


def operacao_de_seguro_em_outros(detalhe: pd.DataFrame | None, colunas) -> pd.Series:
    """O que a seguradora lanca como operacao dentro de `3.04.04` e `3.04.05`.

    Zero para quem nao opera seguro ou nao tem arvore: nao ha o que tirar do
    item nao recorrente.
    """
    colunas = list(colunas)
    zeros = pd.Series(0.0, index=colunas, dtype=float)
    if detalhe is None or detalhe.empty or not opera_seguro(detalhe):
        return zeros
    codigos = detalhe["codigo"].astype(str)
    filhas = detalhe[codigos.str.match(r"^3\.04\.0[45]\.\d+$")]
    operacao = filhas[filhas["rotulo"].map(_sem_acento).str.contains(OPERACAO_DE_SEGURO)]
    if operacao.empty:
        return zeros
    return pd.Series(
        {
            coluna: float(pd.to_numeric(operacao[coluna], errors="coerce").fillna(0).sum())
            if coluna in operacao.columns
            else 0.0
            for coluna in colunas
        },
        dtype=float,
    )


# **Derivativo no balanco, para a reconciliacao -- e nao para a divida.** A
# Localiza abate o swap da divida liquida que publica (2.060 liquidos em 2024, e
# sem ele os R$ 30,1 bi nao se reconstroem). Mas medido nas 415 companhias de
# 2024, 190 publicam derivativo, e das 475 folhas encontradas **399 dizem so
# "Instrumentos Financeiros Derivativos"**: o rotulo nao separa o swap da divida
# do hedge da receita. Os maiores casos sao justamente os que nao protegem
# divida -- Suzano com 6.568 liquidos a pagar contra receita em dolar, Raizen com
# 2.518 a receber em commodity. Somar tudo a divida erraria onde pesa.
#
# So ativo (`1.`) e passivo (`2.01`, `2.02`): a primeira varredura pegou tambem
# a reserva de hedge do patrimonio (`2.03`), e a Klabin aparecia com 1.989 de
# "passivo" que era ajuste de avaliacao patrimonial.
DERIVATIVO = re.compile(r"derivativ|\bswaps?\b")


def derivativos_no_balanco(detalhe: pd.DataFrame | None, coluna=None) -> tuple[float, float]:
    """``(ativo, passivo)`` de derivativos publicados, somando so as folhas."""
    if detalhe is None or detalhe.empty or "codigo" not in detalhe.columns:
        return 0.0, 0.0
    periodos = colunas_de_periodo(detalhe)
    if not periodos:
        return 0.0, 0.0
    coluna = periodos[-1] if coluna is None else coluna
    if coluna not in detalhe.columns:
        return 0.0, 0.0
    codigos = detalhe["codigo"].astype(str)
    no_balanco = codigos.str.match(r"^(1\.|2\.0[12]\.)")
    casa = detalhe[no_balanco & detalhe["rotulo"].map(_sem_acento).str.contains(DERIVATIVO)]
    ativo = passivo = 0.0
    codigos_que_casam = set(casa["codigo"].astype(str))
    for _, linha in casa.iterrows():
        codigo = str(linha["codigo"])
        if any(outro.startswith(codigo + ".") for outro in codigos_que_casam):
            continue
        valor = _numero(linha[coluna])
        if not np.isfinite(valor):
            continue
        if codigo.startswith("1."):
            ativo += valor
        else:
            passivo += valor
    return ativo, passivo


def _numero(valor) -> float:
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return float("nan")
    return numero


def _como_lastro(linha: "LinhaDeTitulo") -> "LinhaDeTitulo":
    """Numa seguradora, o titulo sem sinal nenhum e lastro, e nao caixa."""
    if linha.classe != CAIXA or DECLARADO_LIVRE.search(_sem_acento(linha.rotulo)):
        return linha
    return LinhaDeTitulo(
        linha.codigo, linha.rotulo, linha.valor, NAO_E_CAIXA, MOTIVO_LASTRO_DE_SEGURADORA
    )


def _linhas_do_grupo(
    detalhe: pd.DataFrame, grupo: str, coluna, seguradora: bool = False
) -> list[LinhaDeTitulo]:
    """As linhas de um grupo do IFRS 9, abertas ate onde a companhia abriu.

    **A subconta nao precisa somar o grupo.** A WEG publica `1.02.01.01` com
    R$ 17,1 mi e a unica filha, "Titulos Designados a Valor Justo", com **zero**:
    ler so as filhas perderia o saldo inteiro. O que as filhas nao explicam vira
    uma linha com o rotulo do proprio grupo.
    """
    codigos = detalhe["codigo"].astype(str)
    linha_do_grupo = detalhe[codigos == grupo]
    if linha_do_grupo.empty:
        return []
    total = _numero(linha_do_grupo[coluna].iloc[0])
    nivel = grupo.count(".") + 1

    filhas = detalhe[
        codigos.str.startswith(grupo + ".")
        & (codigos.str.count(r"\.") + 1 == nivel + 1)
    ]
    linhas: list[LinhaDeTitulo] = []
    for _, filha in filhas.iterrows():
        valor = _numero(filha[coluna])
        if not np.isfinite(valor) or valor == 0:
            continue
        classe, motivo = classificar(filha["rotulo"])
        linhas.append(
            LinhaDeTitulo(str(filha["codigo"]), str(filha["rotulo"]), valor, classe, motivo)
        )

    # **O ajuste negativo segue a conta que ele ajusta.** A Localiza publica
    # "CDB vinculados" com 1.216 e, ao lado, "(-) Ajuste a Valor Presente" com
    # -242. O rotulo do ajuste nao tem sinal nenhum e cairia em caixa -- e a
    # tela mostraria caixa negativo ao lado de um vinculado inflado.
    positivas = {l.classe for l in linhas if l.valor > 0}
    if len(positivas) == 1:
        (classe_das_irmas,) = positivas
        linhas = [
            LinhaDeTitulo(
                l.codigo, l.rotulo, l.valor, classe_das_irmas,
                next(p.motivo for p in linhas if p.valor > 0),
            )
            if l.valor < 0 and l.motivo == MOTIVO_CAIXA
            else l
            for l in linhas
        ]

    if np.isfinite(total) and total != 0:
        residuo = total - sum(l.valor for l in linhas)
        if abs(residuo) > FOLGA_DO_RESIDUO * abs(total):
            classe, motivo = classificar(linha_do_grupo["rotulo"].iloc[0])
            linhas.append(
                LinhaDeTitulo(
                    grupo, str(linha_do_grupo["rotulo"].iloc[0]), residuo, classe, motivo
                )
            )
    if seguradora:
        linhas = [_como_lastro(l) for l in linhas]
    return linhas


def titulos(detalhe: pd.DataFrame | None, coluna=None) -> list[LinhaDeTitulo]:
    """Todas as linhas de TVM -- circulante e de longo prazo -- num periodo.

    Sem arvore publicada, ou numa arvore de outro plano, a lista e vazia: nao ha
    o que classificar.
    """
    if not plano_industrial(detalhe):
        return []
    periodos = colunas_de_periodo(detalhe)
    if not periodos:
        return []
    if coluna is None:
        coluna = periodos[-1]
    if coluna not in detalhe.columns:
        return []

    seguradora = opera_seguro(detalhe)
    linhas: list[LinhaDeTitulo] = []
    for raiz in (TVM_CIRCULANTE, REALIZAVEL_A_LONGO_PRAZO):
        for balde in BALDES_DO_IFRS_9:
            linhas += _linhas_do_grupo(detalhe, f"{raiz}.{balde}", coluna, seguradora)
    return linhas


def longo_prazo_que_abate(detalhe: pd.DataFrame | None, colunas) -> pd.Series:
    """O TVM de longo prazo que abate a divida, por periodo.

    **Vazio e zero sao respostas diferentes.** Sem arvore -- importacao de
    planilha, plano financeiro -- o valor e NaN: nao se sabe. Com arvore e sem a
    linha, e zero: a demonstracao inteira esta ali, e a linha nao esta. Tratar o
    primeiro como o segundo faria a divida liquida ampla sair igual a padrao
    para quem nunca teve como medi-la, com cara de medida.
    """
    colunas = list(colunas)
    if not plano_industrial(detalhe):
        return pd.Series(np.nan, index=colunas, dtype=float)
    valores = {}
    for coluna in colunas:
        if coluna not in detalhe.columns:
            valores[coluna] = np.nan
            continue
        valores[coluna] = float(
            sum(
                l.valor
                for l in titulos(detalhe, coluna)
                if l.longo_prazo and l.abate_a_divida
            )
        )
    return pd.Series(valores, dtype=float)

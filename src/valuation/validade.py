"""O que neste modelo envelheceu -- um registro so, para todos os consumidores.

Um valuation e uma fotografia de varias fontes com **datas diferentes**: a
demonstracao e de um exercicio, a curva de juros e do dia, o beta setorial e da
revisao anual, o preco e de quando o analista olhou a tela. Retomado tres meses
depois, o mesmo arquivo continua devolvendo um numero -- e nada ali diz que
metade dos insumos mudou.

As pecas de validade ja existiam espalhadas: a NTN-B embarcada tem data e corte
(`custo_capital.NTNB_MEDIDA_EM`), os betas tem `ATUALIZADO_EM`, a base de
percentis compara a propria safra com o cache (`referencias.safra`), e a tela de
Dados sabe rebuscar a CVM. O que faltava era alguem **perguntar de uma vez**: o
que aqui esta velho, quanto, e o que isso move.

Este modulo nao busca nada e nao corrige nada. Ele le o que o modelo ja carrega e
devolve uma lista de insumos datados -- e a decisao de atualizar continua com
quem conhece o caso, pela mesma razao de sempre: trocar premissa pelas costas do
analista e pior do que mostrar que ela envelheceu.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

# O que cada insumo move no resultado. Serve para ordenar a lista: insumo que
# mexe no WACC vale uma linha antes do que mexe so na comparacao com a base.
MOVE_O_WACC = "WACC"
MOVE_O_FLUXO = "fluxo"
MOVE_O_PRECO = "preço"
MOVE_A_REFERENCIA = "referência"

_PESO_DO_QUE_MOVE = {
    MOVE_O_WACC: 0,
    MOVE_O_FLUXO: 1,
    MOVE_O_PRECO: 2,
    MOVE_A_REFERENCIA: 3,
}

# Quanto vale um preco antes de merecer conferencia. **E escolha, nao medicao**:
# o preco muda todo dia, e o que envelhece nao e o numero e sim a conclusao
# ("com 23% de margem") que o material carrega. Um mes e o intervalo em que uma
# tese de valor costuma continuar valendo sem revisao.
DIAS_DE_VALIDADE_DO_PRECO = 30

# Os betas setoriais saem da planilha do Damodaran, publicada **uma vez por
# ano**, em janeiro. Depois de um ano a edicao seguinte ja saiu.
DIAS_DE_VALIDADE_DOS_BETAS = 365

# O prazo da CVM para o ITR: 45 dias apos o fim do trimestre (Instrucao 480,
# art. 29). A serie trimestral nao envelhece por idade em dias, e sim quando o
# **prazo do trimestre seguinte vence** -- e a partir dai existe informacao
# publicada que o modelo nao viu.
#
# **O prazo nao e a publicacao.** Companhia entrega antes, companhia atrasa, e
# ler o ITR em cache para confirmar custaria abrir um zip de dezenas de MB a
# cada diagnostico. Por isso o texto diz "o prazo venceu" e manda conferir, em
# vez de afirmar que o arquivo existe.
DIAS_ATE_O_PRAZO_DO_ITR = 45
_FIM_DOS_TRIMESTRES = {1: (3, 31), 2: (6, 30), 3: (9, 30)}


def trimestre_com_prazo_vencido(hoje: date | None = None) -> tuple[int, int] | None:
    """O trimestre mais recente cujo ITR ja deveria ter sido entregue.

    Devolve ``(ano, trimestre)``. O quarto trimestre nao tem ITR -- ele vira a
    DFP, com prazo proprio --, entao a contagem so considera os tres primeiros.
    """
    hoje = hoje or date.today()
    candidatos = []
    for ano in (hoje.year, hoje.year - 1):
        for trimestre, (mes, dia) in _FIM_DOS_TRIMESTRES.items():
            fim = date(ano, mes, dia)
            prazo = fim + timedelta(days=DIAS_ATE_O_PRAZO_DO_ITR)
            if prazo <= hoje:
                candidatos.append((ano, trimestre))
    return max(candidatos) if candidatos else None


@dataclass(frozen=True)
class Insumo:
    """Um numero do modelo que tem data, e portanto validade.

    ``vencido_declarado`` existe para o insumo que **nao envelhece por tempo**:
    a base de percentis nao vence em N dias, ela vence quando sai um exercicio
    mais novo do que o medido. Nesse caso a fonte diz se venceu, e ``medido_em``
    serve so para o leitor situar a medicao.
    """

    chave: str
    nome: str
    medido_em: date | None
    move: str
    como_atualizar: str
    valido_por_dias: int | None = None
    detalhe: str = ""
    vencido_declarado: bool | None = None

    def idade_em_dias(self, hoje: date | None = None) -> int | None:
        if self.medido_em is None:
            return None
        return ((hoje or date.today()) - self.medido_em).days

    def vencido(self, hoje: date | None = None) -> bool:
        if self.vencido_declarado is not None:
            return self.vencido_declarado
        idade = self.idade_em_dias(hoje)
        if idade is None or self.valido_por_dias is None:
            return False
        return idade > self.valido_por_dias


def _insumo_da_taxa_livre_de_risco(empresa, rf_em: date | None) -> Insumo | None:
    """A taxa que o modelo usa, seja ela a embarcada ou a informada.

    **A informada tambem envelhece.** O desenho inicial calava quando `rf_brl`
    estava preenchido -- "quem informou ja resolveu o campo" --, e resolveu
    *naquele dia*: a taxa veio de uma curva de uma data, e a curva se move. O
    app parava de avisar justamente no caso em que o numero veio do mercado.

    Sem data gravada -- projeto salvo antes desta mudanca, ou numero digitado a
    mao -- nao da para dizer a idade, e o modulo nao inventa uma.
    """
    from .custo_capital import DIAS_ATE_A_REFERENCIA_ENVELHECER, NTNB_MEDIDA_EM

    premissas = getattr(empresa, "custo_capital", None)
    if premissas is None or premissas.metodo != "local":
        return None

    if premissas.rf_brl is None:
        return Insumo(
            chave="rf_brl",
            nome="Taxa livre de risco (NTN-B de referência)",
            medido_em=NTNB_MEDIDA_EM,
            move=MOVE_O_WACC,
            valido_por_dias=DIAS_ATE_A_REFERENCIA_ENVELHECER,
            como_atualizar=(
                "Em Custo de capital, busque a curva do Tesouro — o número do dia "
                "substitui a referência embarcada."
            ),
            detalhe=(
                "O modelo está usando a taxa real embarcada no app, porque nenhum "
                "rf foi informado. Ela decide o WACC inteiro."
            ),
        )
    if rf_em is None:
        return None
    return Insumo(
        chave="rf_brl",
        nome="Taxa livre de risco (informada)",
        medido_em=rf_em,
        move=MOVE_O_WACC,
        valido_por_dias=DIAS_ATE_A_REFERENCIA_ENVELHECER,
        como_atualizar=(
            "Em Custo de capital, busque a curva do Tesouro de novo e aplique."
        ),
        detalhe="O rf veio da curva aplicada nesta data, e a curva se move.",
    )


def _insumo_dos_betas(empresa, setor: str | None) -> Insumo | None:
    """O beta setorial, e so quando ele de fato veio da tabela.

    **A premissa sozinha nao distingue** um beta desalavancado digitado a mao de
    um trazido da planilha do Damodaran -- os dois ocupam o mesmo campo. Quem
    sabe e quem escolheu: a tela guarda o setor quando a caixa e usada. Sem
    setor declarado, este modulo nao afirma a origem, e portanto nao afirma a
    validade.
    """
    from .dados_setoriais import ATUALIZADO_EM

    premissas = getattr(empresa, "custo_capital", None)
    if premissas is None or premissas.beta_desalavancado is None or not setor:
        return None
    try:
        ano, mes = (int(parte) for parte in ATUALIZADO_EM.split("-"))
        medido_em = date(ano, mes, 1)
    except (ValueError, AttributeError):
        medido_em = None
    return Insumo(
        chave="betas_setoriais",
        nome="Beta do setor (Damodaran)",
        medido_em=medido_em,
        move=MOVE_O_WACC,
        valido_por_dias=DIAS_DE_VALIDADE_DOS_BETAS,
        como_atualizar=(
            "A planilha do Damodaran sai em janeiro; recarregue-a em "
            "dados_setoriais e refaça a medição por setor."
        ),
        detalhe=f"Edição usada para o beta desalavancado de {setor}.",
    )


def _insumo_da_base_de_referencias(cache=None) -> Insumo | None:
    """Os percentis que a tela cita, contra o exercicio mais novo publicado.

    Nao envelhece por tempo: envelhece quando sai DFP mais recente do que a
    safra medida -- e e a propria `referencias.safra` que sabe disso.
    """
    from . import referencias

    safra = referencias.safra(cache)
    if safra is None:
        return None
    return Insumo(
        chave="base_de_referencias",
        nome="Base de percentis das companhias brasileiras",
        medido_em=date(safra.ano_medido, 12, 31),
        move=MOVE_A_REFERENCIA,
        vencido_declarado=bool(safra.desatualizada),
        como_atualizar=(
            "Reconstrua o universo (`python -m valuation.pares`) e regenere os "
            "percentis."
        ),
        detalhe=(
            f"Medida em {safra.companhias} companhias do exercício "
            f"{safra.ano_medido}"
            + (
                f"; a CVM já publicou {safra.ano_mais_novo}."
                if safra.desatualizada
                else "."
            )
        ),
    )


def _ultimo_exercicio(colunas) -> int | None:
    """O ano mais recente da serie, seja ela anual ou trimestral.

    Uma serie de ano movel tem colunas como ``3T25``, e nao inteiros: exigir
    numero fazia a lista estourar em vez de responder. O leitor de rotulo ja
    existe -- e quando nem ele entende a coluna, a resposta e ausencia, nao
    palpite.
    """
    from .importacao.series import periodo_do_rotulo

    anos = []
    for coluna in colunas:
        if isinstance(coluna, bool):
            continue
        if isinstance(coluna, (int, float)):
            anos.append(int(coluna))
            continue
        periodo = periodo_do_rotulo(coluna)
        if periodo:
            anos.append(periodo[0])
    return max(anos) if anos else None


def _insumo_das_demonstracoes(demonstracoes, cache=None, hoje=None) -> Insumo | None:
    """O historico importado, contra o que a CVM ja publicou.

    **Serie anual e serie trimestral envelhecem por regras diferentes.** Uma DFP
    de 2025 nao fica velha em marco de 2026: fica velha quando a de 2026 sai, e
    quem sabe disso e o cache -- a mesma regra da tela de Dados. Ja uma serie
    rotulada por trimestre fica velha quando **vence o prazo do trimestre
    seguinte**, e ai a comparacao por exercicio nao enxerga nada: quem importou
    1T26 e volta em outubro tem a mesma "2026" na coluna.
    """
    from .importacao.series import periodo_do_rotulo

    if demonstracoes is None or not getattr(demonstracoes, "anos", None):
        return None
    ultimo = _ultimo_exercicio(demonstracoes.anos)
    if ultimo is None:
        return None

    trimestre_importado = periodo_do_rotulo(demonstracoes.anos[-1])
    if trimestre_importado is not None:
        return _insumo_da_serie_trimestral(demonstracoes, trimestre_importado, hoje)
    mais_novo = None
    try:
        from .pares import _anos_de_dfp_no_cache

        publicados = _anos_de_dfp_no_cache(cache)
        mais_novo = publicados[-1] if publicados else None
    except Exception:  # noqa: BLE001 - sem cache nao ha com o que comparar
        mais_novo = None

    tem_novo = bool(mais_novo and mais_novo > ultimo)
    return Insumo(
        chave="demonstracoes",
        nome="Demonstrações importadas",
        medido_em=date(ultimo, 12, 31),
        move=MOVE_O_FLUXO,
        vencido_declarado=tem_novo,
        como_atualizar=(
            "Em Dados, use **Atualizar da CVM** — a busca é refeita incluindo o "
            "exercício novo."
        ),
        detalhe=(
            f"Última coluna importada: {demonstracoes.anos[-1]}"
            + (f"; a CVM já publicou {mais_novo}." if tem_novo else ".")
        ),
    )


def _insumo_da_serie_trimestral(demonstracoes, importado, hoje) -> Insumo:
    """A serie por trimestre, contra o prazo do ITR seguinte."""
    esperado = trimestre_com_prazo_vencido(hoje)
    tem_novo = bool(esperado and esperado > importado)
    rotulo = demonstracoes.anos[-1]
    if tem_novo:
        ano, trimestre = esperado
        fim = date(ano, *_FIM_DOS_TRIMESTRES[trimestre])
        prazo = fim + timedelta(days=DIAS_ATE_O_PRAZO_DO_ITR)
        detalhe = (
            f"Última coluna importada: {rotulo}. O prazo do ITR do {trimestre}T"
            f"{str(ano)[-2:]} venceu em {prazo.strftime('%d/%m/%Y')} — confira se "
            "a companhia já publicou."
        )
    else:
        detalhe = f"Última coluna importada: {rotulo}."
    return Insumo(
        chave="demonstracoes",
        nome="Demonstrações importadas (série trimestral)",
        medido_em=date(importado[0], *_FIM_DOS_TRIMESTRES.get(importado[1], (12, 31))),
        move=MOVE_O_FLUXO,
        vencido_declarado=tem_novo,
        como_atualizar=(
            "Em Dados, reimporte a série — o trimestre novo entra como coluna."
        ),
        detalhe=detalhe,
    )


def _insumo_do_preco(preco_em: date | None) -> Insumo | None:
    if preco_em is None:
        return None
    return Insumo(
        chave="preco",
        nome="Preço de mercado informado",
        medido_em=preco_em,
        move=MOVE_O_PRECO,
        valido_por_dias=DIAS_DE_VALIDADE_DO_PRECO,
        como_atualizar="Informe o preço de hoje em Margem de segurança.",
        detalhe=(
            "A margem de segurança e o retorno esperado são medidos contra ele."
        ),
    )


def insumos(
    empresa=None,
    demonstracoes=None,
    preco_em: date | None = None,
    cache=None,
    setor: str | None = None,
    hoje: date | None = None,
    rf_em: date | None = None,
) -> list[Insumo]:
    """Os insumos datados deste modelo, do que mais move o valor para o que menos.

    Tudo e opcional: o que nao foi informado simplesmente nao vira linha. Um
    modelo montado a mao, sem historico importado e sem preco, tem so o custo de
    capital para envelhecer -- e e isso que a lista deve mostrar.
    """
    candidatos = [
        _insumo_da_taxa_livre_de_risco(empresa, rf_em) if empresa is not None else None,
        _insumo_dos_betas(empresa, setor) if empresa is not None else None,
        _insumo_das_demonstracoes(demonstracoes, cache, hoje),
        _insumo_do_preco(preco_em),
        _insumo_da_base_de_referencias(cache),
    ]
    presentes = [i for i in candidatos if i is not None]
    return sorted(presentes, key=lambda i: _PESO_DO_QUE_MOVE.get(i.move, 9))


def vencidos(
    empresa=None,
    demonstracoes=None,
    preco_em: date | None = None,
    cache=None,
    hoje: date | None = None,
    setor: str | None = None,
    rf_em: date | None = None,
) -> list[Insumo]:
    """So os que passaram da validade, na mesma ordem."""
    return [
        i
        for i in insumos(empresa, demonstracoes, preco_em, cache, setor, hoje, rf_em)
        if i.vencido(hoje)
    ]


def resumo(
    empresa=None,
    demonstracoes=None,
    preco_em: date | None = None,
    cache=None,
    hoje: date | None = None,
    setor: str | None = None,
    rf_em: date | None = None,
) -> str:
    """Uma linha para a barra lateral e para o rodape dos entregaveis."""
    todos = insumos(empresa, demonstracoes, preco_em, cache, setor, hoje, rf_em)
    if not todos:
        return ""
    velhos = [i for i in todos if i.vencido(hoje)]
    if not velhos:
        return f"{len(todos)} insumos datados, todos dentro da validade."
    nomes = ", ".join(i.nome.split(" (")[0].lower() for i in velhos)
    return f"{len(velhos)} de {len(todos)} insumos pedem atualização: {nomes}."

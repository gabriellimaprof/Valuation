"""Diagnostico automatico do modelo: o app criticando o proprio valuation.

Um DCF sempre devolve um numero. O numero ser *defensavel* depende de coisas
que a aritmetica nao verifica: crescer para sempre acima da economia, crescer
sem reinvestir, projetar margem que a empresa nunca entregou, deixar a
perpetuidade responder por quase todo o valor.

Cada achado explica o que foi encontrado, por que aquilo importa e o que fazer
-- e nao apenas que algo esta fora de um intervalo. Para um analista em
formacao, esta e a parte do app que ensina; para um analista experiente, e a
checklist que ninguem lembra de rodar inteira antes de mandar o material.

As faixas usadas sao heuristicas de mercado, nao leis. Um achado e um convite a
justificar a premissa, nunca uma proibicao.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .historico import AnaliseHistorica
from .modelo import ResultadoValuation

ERRO = "erro"
ALERTA = "alerta"
INFORMACAO = "informacao"

_ORDEM_SEVERIDADE = {ERRO: 0, ALERTA: 1, INFORMACAO: 2}


def _pct(valor: float, casas: int = 1) -> str:
    """Percentual no padrao brasileiro, com virgula decimal.

    Os achados sao lidos por quem trabalha em portugues; "9,0%" e o que essa
    pessoa espera ver, e "9.0%" destoa do resto do app.
    """
    if not np.isfinite(valor):
        return "n/d"
    return f"{valor * 100:.{casas}f}%".replace(".", ",")


def _num(valor: float, casas: int = 1) -> str:
    """Numero no padrao brasileiro: milhar com ponto, decimal com virgula."""
    if not np.isfinite(valor):
        return "n/d"
    return f"{valor:,.{casas}f}".replace(",", "@").replace(".", ",").replace("@", ".")

# Faixas de referencia. Deliberadamente largas: servem para pegar o absurdo, nao
# para impor uma visao de mundo.
BETA_MINIMO, BETA_MAXIMO = 0.3, 2.5
WACC_MINIMO_BRL, WACC_MAXIMO_BRL = 0.07, 0.30
PESO_PERPETUIDADE_ALTO = 0.75
ALAVANCAGEM_ALTA = 3.5
MARGEM_ROIC_WACC_EXCEPCIONAL = 0.10
# Acima disto, o retorno passa a depender mais do mercado do que da empresa.
PESO_RERATING_ALTO = 0.40
TSR_IMPLAUSIVEL = 0.40
# Abaixo disto, a maior parte do EBITDA nao chega ao caixa. Nao e defeito por si
# -- empresa que cresce rapido prende caixa no giro --, mas precisa de explicacao.
CONVERSAO_CAIXA_BAIXA = 0.60
# Diferenca entre o juro da DRE e o juro pago que sugere capitalizacao.
JUROS_CAPITALIZADOS = 0.02
# A partir daqui o arrendamento deixa de ser detalhe da divida e passa a mudar a
# leitura do EBITDA e da alavancagem. Em Petrobras chega a metade.
LEASING_RELEVANTE = 0.20


@dataclass(frozen=True)
class Achado:
    """Um ponto do modelo que merece atencao, com o porque e o que fazer."""

    codigo: str
    severidade: str
    titulo: str
    detalhe: str
    acao: str = ""
    referencia: str = ""

    @property
    def icone(self) -> str:
        return {ERRO: "🔴", ALERTA: "🟡", INFORMACAO: "🔵"}.get(self.severidade, "•")


@dataclass(frozen=True)
class Diagnostico:
    """Conjunto de achados de um modelo, do mais grave para o menos."""

    achados: list[Achado] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.achados)

    def por_severidade(self, severidade: str) -> list[Achado]:
        return [a for a in self.achados if a.severidade == severidade]

    @property
    def erros(self) -> list[Achado]:
        return self.por_severidade(ERRO)

    @property
    def alertas(self) -> list[Achado]:
        return self.por_severidade(ALERTA)

    @property
    def aprovado(self) -> bool:
        """O modelo passou sem nenhum achado grave?"""
        return not self.erros

    def tabela(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "Severidade": a.severidade,
                    "Achado": a.titulo,
                    "Detalhe": a.detalhe,
                    "O que fazer": a.acao,
                    "Referencia": a.referencia,
                }
                for a in self.achados
            ]
        )


def _ordenar(achados: list[Achado]) -> list[Achado]:
    return sorted(achados, key=lambda a: _ORDEM_SEVERIDADE.get(a.severidade, 9))


def diagnosticar(
    resultado: ResultadoValuation,
    analise: AnaliseHistorica | None = None,
    crescimento_nominal_economia: float | None = None,
    retorno=None,
) -> Diagnostico:
    """Roda a bateria de verificacoes sobre um valuation ja calculado.

    ``analise`` habilita as comparacoes com o historico da propria empresa, que
    sao as mais uteis: uma margem de 25% nao e otimista em abstrato, e otimista
    para quem entregou 18% nos ultimos cinco anos.

    ``crescimento_nominal_economia`` e o teto natural do crescimento perpetuo.
    Sem ele, vem da propria macro da empresa: inflacao de longo prazo composta
    com o PIB real. Antes eram 2% de PIB real fixos no codigo, o que fazia o
    teto ignorar quem tinha estressado a macro.

    ``retorno`` e uma ``DecomposicaoTSR`` ja calculada. Com ela, a checklist
    passa a cobrir tambem a tese de retorno -- de onde vem o ganho esperado e se
    ele compensa o risco -- e nao apenas a consistencia interna do fluxo.
    """
    empresa = resultado.empresa
    wacc = resultado.dcf.taxa_desconto
    g = empresa.perpetuidade.crescimento_perpetuo
    if crescimento_nominal_economia is None:
        crescimento_nominal_economia = empresa.macro.pib_nominal

    achados: list[Achado] = []
    achados += _checar_perpetuidade(resultado, g, wacc, crescimento_nominal_economia)
    achados += _checar_reinvestimento(resultado, g, wacc)
    achados += _checar_custo_de_capital(resultado, wacc)
    achados += _checar_estrutura_do_valor(resultado)
    if analise is not None:
        achados += _checar_contra_historico(resultado, analise)
    if retorno is not None:
        achados += _checar_retorno(resultado, retorno)

    return Diagnostico(achados=_ordenar(achados))


def _checar_retorno(resultado: ResultadoValuation, retorno) -> list[Achado]:
    """Verificacoes sobre a tese de retorno, e nao sobre o fluxo de caixa."""
    achados = []
    ke = resultado.custo_capital.ke_brl
    tsr = retorno.tsr
    if not np.isfinite(tsr):
        return achados

    if tsr < ke:
        achados.append(
            Achado(
                codigo="retorno_abaixo_do_exigido",
                severidade=ALERTA,
                titulo=(
                    f"Retorno esperado ({_pct(tsr)}) abaixo do exigido ({_pct(ke)})"
                ),
                detalhe=(
                    "A este preço, o investimento entrega menos do que o risco da "
                    f"empresa pede — uma diferença de {_pct(ke - tsr)} ao ano. Comprar "
                    "assim é aceitar ser mal remunerado pelo risco assumido."
                ),
                acao=(
                    "Veja em Retorno esperado qual o preço máximo para o retorno que "
                    "você exige, ou revise as premissas que sustentam o lucro projetado."
                ),
                referencia="CFA Institute, Equity Asset Valuation, cap. 1",
            )
        )

    peso = abs(retorno.contribuicao_multiplo) / abs(tsr) if tsr else float("nan")
    if np.isfinite(peso) and peso > PESO_RERATING_ALTO:
        direcao = "expansão" if retorno.contribuicao_multiplo > 0 else "contração"
        achados.append(
            Achado(
                codigo="retorno_depende_de_rerating",
                severidade=ALERTA,
                titulo=f"{_pct(peso, 0)} do retorno vem de {direcao} de múltiplo",
                detalhe=(
                    "Essa parcela não depende de a empresa entregar coisa alguma: "
                    "depende de quanto o próximo comprador estará disposto a pagar. "
                    "Uma tese apoiada principalmente aí é uma aposta sobre o humor do "
                    "mercado, não sobre o negócio."
                ),
                acao=(
                    "Explicite por que o mercado reavaliaria a empresa, e calcule o "
                    "retorno no cenário em que o múltiplo não muda."
                ),
                referencia="Damodaran, The Little Book of Valuation, cap. 7",
            )
        )

    if tsr > TSR_IMPLAUSIVEL:
        achados.append(
            Achado(
                codigo="retorno_implausivel",
                severidade=ALERTA,
                titulo=f"Retorno esperado de {_pct(tsr, 0)} ao ano",
                detalhe=(
                    "Retornos dessa ordem raramente sobrevivem a uma revisão. Costumam "
                    "vir de preço de entrada muito abaixo do valor, de crescimento "
                    "otimista ou de múltiplo de saída generoso — e o mercado "
                    "dificilmente deixaria uma oportunidade dessas de pé."
                ),
                acao=(
                    "Confira o preço de entrada e o múltiplo de saída antes de "
                    "defender o número."
                ),
                referencia="",
            )
        )

    entrada, saida = retorno.multiplo_entrada, retorno.multiplo_saida
    if entrada > 0 and saida > entrada * 1.2:
        achados.append(
            Achado(
                codigo="multiplo_de_saida_generoso",
                severidade=INFORMACAO,
                titulo=(
                    f"Múltiplo de saída ({_num(saida, 1)}x) mais de 20% acima do de "
                    f"entrada ({_num(entrada, 1)}x)"
                ),
                detalhe=(
                    "O modelo assume vender mais caro, por real de lucro, do que "
                    "comprou. É possível, mas é uma hipótese sobre o mercado que "
                    "convém estar consciente."
                ),
                acao="Rode também com o múltiplo de saída igual ao de entrada.",
                referencia="",
            )
        )

    return achados


def _checar_perpetuidade(
    resultado: ResultadoValuation, g: float, wacc: float, teto_economia: float
) -> list[Achado]:
    achados = []
    perp = resultado.empresa.perpetuidade

    if perp.metodo == "gordon":
        if g > teto_economia:
            achados.append(
                Achado(
                    codigo="g_acima_da_economia",
                    severidade=ALERTA,
                    titulo=f"Crescimento perpétuo de {_pct(g, 1)} supera a economia",
                    detalhe=(
                        f"O modelo faz a empresa crescer {_pct(g, 1)} para sempre, acima do "
                        f"crescimento nominal estimado da economia ({_pct(teto_economia, 1)}). "
                        "Crescer acima da economia para sempre significa que a empresa "
                        "acabaria por se tornar maior que o próprio PIB."
                    ),
                    acao=(
                        f"Reduza o crescimento perpétuo para no máximo {_pct(teto_economia, 1)}, "
                        "ou alongue a projeção explícita se a empresa ainda tem uma fase "
                        "de crescimento acelerado a percorrer."
                    ),
                    referencia="Damodaran, Investment Valuation, cap. 12 (stable growth)",
                )
            )
        if wacc - g < 0.02:
            achados.append(
                Achado(
                    codigo="spread_wacc_g_estreito",
                    severidade=ALERTA,
                    titulo="Diferença entre WACC e crescimento perpétuo muito estreita",
                    detalhe=(
                        f"WACC de {_pct(wacc, 2)} contra crescimento de {_pct(g, 2)}: o denominador "
                        f"da perpetuidade e apenas {_pct(wacc - g, 2)}. Nessa faixa, uma "
                        "mudanca de 0,5 p.p. em qualquer um dos dois altera o valor da "
                        "empresa em dezenas de por cento."
                    ),
                    acao=(
                        "Olhe a tabela de sensibilidade antes de defender o número: "
                        "provavelmente a faixa de valor e larga demais para um número único."
                    ),
                    referencia="CFA Institute, Equity Asset Valuation, cap. 4",
                )
            )

        roic_perp = perp.roic_perpetuidade
        if roic_perp is None and g > 0:
            achados.append(
                Achado(
                    codigo="perpetuidade_sem_reinvestimento",
                    severidade=ALERTA,
                    titulo="Crescimento perpétuo sem reinvestimento explícito",
                    detalhe=(
                        f"A perpetuidade cresce {_pct(g, 1)} ao ano a partir do fluxo do ultimo "
                        "ano projetado, sem exigir reinvestimento para sustentar esse "
                        "crescimento. Isso costuma superestimar o valor terminal, porque "
                        "crescer para sempre exige investir para sempre."
                    ),
                    acao=(
                        "Informe o ROIC de perpetuidade. O modelo passa a descontar do "
                        "fluxo perpétuo a taxa de reinvestimento g/ROIC, que e a forma "
                        "consistente de crescer."
                    ),
                    referencia="Damodaran, Investment Valuation, cap. 12",
                )
            )
        elif roic_perp is not None:
            if roic_perp <= wacc:
                achados.append(
                    Achado(
                        codigo="roic_perpetuo_abaixo_do_wacc",
                        severidade=ALERTA,
                        titulo=f"ROIC perpétuo ({_pct(roic_perp, 1)}) não supera o WACC ({_pct(wacc, 1)})",
                        detalhe=(
                            "Quando o retorno sobre o capital não supera o custo do capital, "
                            "cada real reinvestido destrói valor. Nesse regime, crescer "
                            "*reduz* o valor da empresa em vez de aumenta-lo."
                        ),
                        acao=(
                            "Se essa é mesmo a realidade do negócio, considere crescimento "
                            "perpétuo zero: a empresa vale mais distribuindo caixa do que "
                            "reinvestindo."
                        ),
                        referencia="Damodaran, The Little Book of Valuation, cap. 4",
                    )
                )
            elif roic_perp - wacc > MARGEM_ROIC_WACC_EXCEPCIONAL:
                achados.append(
                    Achado(
                        codigo="roic_perpetuo_excepcional",
                        severidade=ALERTA,
                        titulo=f"ROIC perpétuo {_pct(roic_perp - wacc, 1)} acima do WACC, para sempre",
                        detalhe=(
                            f"O modelo assume ROIC de {_pct(roic_perp, 1)} contra WACC de "
                            f"{_pct(wacc, 1)} em perpetuidade. Manter esse spread para sempre "
                            "equivale a supor uma barreira de entrada que nunca e erodida "
                            "pela concorrência."
                        ),
                        acao=(
                            "Justifique a vantagem competitiva (marca, rede, licença, "
                            "escala) ou aproxime o ROIC perpétuo do WACC."
                        ),
                        referencia="Damodaran, Investment Valuation, cap. 12",
                    )
                )

    return achados


def _checar_reinvestimento(
    resultado: ResultadoValuation, g: float, wacc: float
) -> list[Achado]:
    achados = []
    proj = resultado.projecao

    capex_final = float(proj.capex[-1])
    deprec_final = float(proj.depreciacao[-1])
    if deprec_final > 0 and capex_final < deprec_final and g > 0:
        achados.append(
            Achado(
                codigo="capex_abaixo_da_depreciacao",
                severidade=ALERTA,
                titulo="Empresa entra na perpetuidade investindo menos do que deprecia",
                detalhe=(
                    f"No ultimo ano projetado o capex e {_num(capex_final / deprec_final, 2)}x a "
                    f"depreciacao, mas a empresa cresce {_pct(g, 1)} para sempre depois disso. "
                    "Uma base de ativos que encolhe não sustenta receita que cresce."
                ),
                acao=(
                    "Eleve o capex do ultimo ano para ao menos o nivel da depreciacao, ou "
                    "use a normalizacao por ROIC na perpetuidade."
                ),
                referencia="Koller, Goedhart & Wessels, Valuation, cap. 10",
            )
        )

    # ROIC marginal: quanto de NOPAT adicional cada real reinvestido gerou.
    nopat = proj.nopat
    reinvestimento = proj.capex - proj.depreciacao + proj.variacao_capital_giro
    if len(nopat) >= 2:
        delta_nopat = np.diff(nopat)
        base = reinvestimento[:-1]
        with np.errstate(divide="ignore", invalid="ignore"):
            roic_marginal = np.where(base > 0, delta_nopat / base, np.nan)
        validos = roic_marginal[np.isfinite(roic_marginal)]
        if validos.size:
            mediana = float(np.median(validos))
            if mediana > 1.0:
                achados.append(
                    Achado(
                        codigo="roic_marginal_implausivel",
                        severidade=ALERTA,
                        titulo=f"Retorno sobre o capital novo implícito de {_pct(mediana, 0)}",
                        detalhe=(
                            "A projeção gera NOPAT adicional muito acima do que reinveste: "
                            f"cada real investido produz {_num(mediana, 2)} de lucro operacional "
                            "por ano. Isso normalmente indica margem crescendo sem que o "
                            "modelo cobre o investimento correspondente."
                        ),
                        acao=(
                            "Confira capex e capital de giro projetados. Crescimento de "
                            "receita quase sempre exige capital de giro proporcional."
                        ),
                        referencia="Damodaran, Investment Valuation, cap. 11",
                    )
                )
            elif mediana < 0:
                achados.append(
                    Achado(
                        codigo="roic_marginal_negativo",
                        severidade=ALERTA,
                        titulo="A projeção reinveste e o lucro operacional cai",
                        detalhe=(
                            "O NOPAT projetado diminui apesar do reinvestimento. Se isso e "
                            "intencional (setor em declínio), tudo bem; se não, há "
                            "inconsistência entre margens e investimento."
                        ),
                        acao="Reveja a trajetoria de margens frente ao capex projetado.",
                        referencia="Koller, Goedhart & Wessels, Valuation, cap. 10",
                    )
                )

    return achados


def _checar_custo_de_capital(resultado: ResultadoValuation, wacc: float) -> list[Achado]:
    achados = []
    cc = resultado.custo_capital
    premissas = resultado.empresa.custo_capital

    if not BETA_MINIMO <= cc.beta_realavancado <= BETA_MAXIMO:
        achados.append(
            Achado(
                codigo="beta_fora_da_faixa",
                severidade=ALERTA,
                titulo=f"Beta realavancado de {_num(cc.beta_realavancado, 2)} fora da faixa usual",
                detalhe=(
                    f"Betas de empresas listadas concentram-se entre {_num(BETA_MINIMO, 1)} e "
                    f"{_num(BETA_MAXIMO, 1)}. Fora dessa faixa costuma haver erro no beta do "
                    "setor ou na estrutura de capital alvo."
                ),
                acao="Confira o beta do setor e o D/E alvo usado para realavancar.",
                referencia="CFA Institute, Equity Asset Valuation, cap. 2",
            )
        )

    if not WACC_MINIMO_BRL <= wacc <= WACC_MAXIMO_BRL:
        achados.append(
            Achado(
                codigo="wacc_fora_da_faixa",
                severidade=ALERTA,
                titulo=f"WACC de {_pct(wacc, 2)} fora da faixa típica em BRL nominal",
                detalhe=(
                    f"Para empresas brasileiras, o WACC nominal em reais costuma ficar "
                    f"entre {_pct(WACC_MINIMO_BRL, 0)} e {_pct(WACC_MAXIMO_BRL, 0)}. Valores fora "
                    "disso geralmente vem de taxa livre de risco, risco-país ou inflacao "
                    "informados em unidade errada."
                ),
                acao="Confira se todas as taxas estão em decimais (0,045 e não 4,5).",
                referencia="Damodaran, country risk premiums",
            )
        )

    if cc.kd_bruto_brl > cc.ke_brl:
        achados.append(
            Achado(
                codigo="kd_acima_do_ke",
                severidade=ALERTA,
                titulo="Custo da dívida acima do custo do capital próprio",
                detalhe=(
                    f"Kd de {_pct(cc.kd_bruto_brl, 2)} contra Ke de {_pct(cc.ke_brl, 2)}. O credor "
                    "tem prioridade sobre o acionista no recebimento, entao normalmente "
                    "exige menos retorno. O inverso sugere erro em uma das duas pontas."
                ),
                acao="Reveja o spread de crédito ou o premio de risco do equity.",
                referencia="CFA Institute, Corporate Finance",
            )
        )

    if premissas.divida_pl_alvo > ALAVANCAGEM_ALTA:
        achados.append(
            Achado(
                codigo="alavancagem_alvo_alta",
                severidade=INFORMACAO,
                titulo=f"Estrutura de capital alvo bastante alavancada (D/E {_num(premissas.divida_pl_alvo, 1)})",
                detalhe=(
                    "Com essa alavancagem, o beta realavancado e o custo da dívida deveriam "
                    "refletir risco de crédito relevante. O modelo não ajusta isso sozinho."
                ),
                acao="Considere elevar o spread de crédito coerentemente com a alavancagem.",
                referencia="Damodaran, Applied Corporate Finance, cap. 8",
            )
        )

    return achados


def _checar_estrutura_do_valor(resultado: ResultadoValuation) -> list[Achado]:
    achados = []
    peso = resultado.dcf.peso_perpetuidade

    if np.isfinite(peso) and peso > PESO_PERPETUIDADE_ALTO:
        achados.append(
            Achado(
                codigo="peso_da_perpetuidade",
                severidade=ALERTA,
                titulo=f"{_pct(peso, 0)} do valor vem da perpetuidade",
                detalhe=(
                    "Quase todo o valor está depois do horizonte projetado, ou seja, "
                    "depende de duas premissas (crescimento perpétuo e taxa de desconto) "
                    "em vez das projeções que você construiu linha a linha."
                ),
                acao=(
                    "Alongue a projeção explícita até a empresa atingir maturidade -- "
                    "normalmente 7 a 10 anos para empresas ainda em crescimento."
                ),
                referencia="Koller, Goedhart & Wessels, Valuation, cap. 12",
            )
        )

    if resultado.equity_value <= 0:
        achados.append(
            Achado(
                codigo="equity_negativo",
                severidade=ERRO,
                titulo="Valor do equity negativo ou nulo",
                detalhe=(
                    f"O Enterprise Value de {_num(resultado.enterprise_value, 1)} não cobre a "
                    "dívida líquida e os demais itens da ponte. Ou a empresa está "
                    "efetivamente insolvente, ou há erro de unidade entre a projeção e o "
                    "balanço."
                ),
                acao=(
                    "Confirme que projeção e ponte estão na mesma unidade (ambas em R$ mil "
                    "ou ambas em R$ milhões)."
                ),
                referencia="",
            )
        )

    fluxos_negativos = int((resultado.dcf.fluxos < 0).sum())
    if fluxos_negativos and fluxos_negativos == len(resultado.dcf.fluxos):
        achados.append(
            Achado(
                codigo="todos_os_fluxos_negativos",
                severidade=ERRO,
                titulo="Todos os fluxos de caixa projetados são negativos",
                detalhe=(
                    "A empresa queima caixa em todo o horizonte explícito e ainda assim "
                    "recebe um valor terminal positivo. O valor fica inteiramente apoiado "
                    "em uma recuperacao que o modelo não mostra."
                ),
                acao="Alongue a projeção até o ano em que a empresa passa a gerar caixa.",
                referencia="Damodaran, Valuing Young and Distressed Companies",
            )
        )
    elif fluxos_negativos:
        achados.append(
            Achado(
                codigo="fluxos_negativos",
                severidade=INFORMACAO,
                titulo=f"{fluxos_negativos} ano(s) com fluxo de caixa negativo",
                detalhe=(
                    "Normal em fase de investimento pesado, mas exige que a empresa "
                    "tenha como financiar o período."
                ),
                acao="Confira se a estrutura de capital projetada suporta a queima.",
                referencia="",
            )
        )

    return achados


def _checar_contra_historico(
    resultado: ResultadoValuation, analise: AnaliseHistorica
) -> list[Achado]:
    """Compara as premissas projetadas com o que a empresa de fato entregou."""
    achados = []
    proj = resultado.projecao

    margem_projetada = float(np.median(proj.ebitda / proj.receita))
    margens_hist = analise.linha("Margem EBITDA").replace([np.inf, -np.inf], np.nan).dropna()
    if not margens_hist.empty:
        maxima, minima = float(margens_hist.max()), float(margens_hist.min())
        if margem_projetada > maxima + 0.02:
            achados.append(
                Achado(
                    codigo="margem_acima_do_historico",
                    severidade=ALERTA,
                    titulo=(
                        f"Margem EBITDA projetada ({_pct(margem_projetada, 1)}) acima do melhor "
                        f"ano histórico ({_pct(maxima, 1)})"
                    ),
                    detalhe=(
                        "O modelo assume que a empresa passa a operar acima do melhor "
                        "desempenho que ja teve, e mantem esse patamar."
                    ),
                    acao=(
                        "Explicite o que muda: ganho de escala, mix, reestruturação, "
                        "repasse de preço. Sem uma razão concreta, use a mediana histórica."
                    ),
                    referencia="CFA Institute, Financial Statement Analysis",
                )
            )
        elif margem_projetada < minima - 0.02:
            achados.append(
                Achado(
                    codigo="margem_abaixo_do_historico",
                    severidade=INFORMACAO,
                    titulo=(
                        f"Margem EBITDA projetada ({_pct(margem_projetada, 1)}) abaixo do pior "
                        f"ano histórico ({_pct(minima, 1)})"
                    ),
                    detalhe="A projeção e mais conservadora do que qualquer ano ja realizado.",
                    acao="Confirme se o conservadorismo e intencional.",
                    referencia="",
                )
            )

    crescimento_projetado = float(np.median(np.diff(proj.receita) / proj.receita[:-1])) if len(proj.receita) > 1 else float("nan")
    cagr_hist = analise.mediana("Crescimento da receita")
    if np.isfinite(crescimento_projetado) and np.isfinite(cagr_hist):
        if crescimento_projetado > cagr_hist + 0.05:
            achados.append(
                Achado(
                    codigo="crescimento_acima_do_historico",
                    severidade=ALERTA,
                    titulo=(
                        f"Crescimento projetado ({_pct(crescimento_projetado, 1)}) bem acima do "
                        f"histórico ({_pct(cagr_hist, 1)})"
                    ),
                    detalhe=(
                        "A aceleracao precisa vir de algum lugar: novo mercado, nova "
                        "capacidade, aquisição. Nenhum deles e gratuito."
                    ),
                    acao=(
                        "Verifique se o capex projetado comporta a expansão de receita "
                        "assumida."
                    ),
                    referencia="Damodaran, Investment Valuation, cap. 11",
                )
            )

    # --- contraprovas de caixa, quando a origem trouxe a DFC aberta ---------

    conversao = analise.mediana("Conversao de caixa (FCO / EBITDA)")
    if np.isfinite(conversao) and conversao < CONVERSAO_CAIXA_BAIXA:
        achados.append(
            Achado(
                codigo="ebitda_nao_vira_caixa",
                severidade=ALERTA,
                titulo=(
                    f"Só {_pct(conversao, 0)} do EBITDA virou caixa operacional"
                ),
                detalhe=(
                    "O EBITDA e o ponto de partida do valor, mas quem paga dívida e "
                    "dividendo e o caixa. Conversao baixa e persistente costuma "
                    "significar lucro preso no capital de giro ou receita "
                    "reconhecida antes de ser recebida."
                ),
                acao=(
                    "Olhe o investimento em giro no histórico antes de projetar "
                    "margem estável."
                ),
                referencia="Koller, Goedhart & Wessels, Valuation, cap. 20",
            )
        )

    leasing = analise.ultimo("Arrendamento / Divida bruta")
    if np.isfinite(leasing) and leasing > LEASING_RELEVANTE:
        achados.append(
            Achado(
                codigo="divida_e_muito_arrendamento",
                severidade=INFORMACAO,
                titulo=f"{_pct(leasing, 0)} da dívida bruta é arrendamento (IFRS 16)",
                detalhe=(
                    "Desde 2019 o aluguel vira ativo de direito de uso e passivo de "
                    "arrendamento, e a despesa sai do EBITDA para virar depreciação "
                    "mais juros. Duas consequências: o EBITDA fica maior do que era "
                    "antes da norma, e essa dívida já está no balanço."
                ),
                acao=(
                    "Não capitalize o aluguel de novo — contaria a mesma dívida duas "
                    "vezes. Ao comparar múltiplos, confirme que os pares seguem a "
                    "mesma norma."
                ),
                referencia="CPC 06 (R2) / IFRS 16",
            )
        )

    kd_competencia = analise.mediana("Custo da divida efetivo")
    kd_caixa = analise.mediana("Custo da divida pelo caixa")
    if (
        np.isfinite(kd_competencia)
        and np.isfinite(kd_caixa)
        and kd_competencia > kd_caixa + JUROS_CAPITALIZADOS
    ):
        achados.append(
            Achado(
                codigo="juros_capitalizados",
                severidade=INFORMACAO,
                titulo=(
                    f"A despesa financeira ({_pct(kd_competencia, 1)} da dívida) supera "
                    f"o juro efetivamente pago ({_pct(kd_caixa, 1)})"
                ),
                detalhe=(
                    "Parte do custo da dívida nao saiu do caixa no período: pode ter "
                    "sido capitalizada em obra, acumulada para pagar depois ou ser "
                    "variação monetária sem desembolso."
                ),
                acao=(
                    "Para o Kd do WACC, o custo contratado importa mais que o pago no "
                    "ano; para o fluxo do acionista, o pago."
                ),
                referencia="",
            )
        )

    roic_hist = analise.mediana("ROIC")
    roic_perp = resultado.empresa.perpetuidade.roic_perpetuidade
    if roic_perp is not None and np.isfinite(roic_hist) and roic_perp > roic_hist + 0.05:
        achados.append(
            Achado(
                codigo="roic_perpetuo_acima_do_historico",
                severidade=ALERTA,
                titulo=(
                    f"ROIC de perpetuidade ({_pct(roic_perp, 1)}) acima do histórico "
                    f"({_pct(roic_hist, 1)})"
                ),
                detalhe=(
                    "A perpetuidade assume um retorno sobre o capital melhor do que a "
                    "empresa costuma entregar, e para sempre."
                ),
                acao="Ancore o ROIC perpétuo no histórico, salvo mudanca estrutural clara.",
                referencia="Koller, Goedhart & Wessels, Valuation, cap. 10",
            )
        )

    alavancagem = analise.ultimo("Divida liquida / EBITDA")
    if np.isfinite(alavancagem) and alavancagem > ALAVANCAGEM_ALTA:
        achados.append(
            Achado(
                codigo="alavancagem_historica_alta",
                severidade=INFORMACAO,
                titulo=f"Dívida líquida / EBITDA de {_num(alavancagem, 1)}x no ultimo ano",
                detalhe=(
                    "Alavancagem nesse patamar costuma vir acompanhada de covenants e de "
                    "custo de dívida mais alto do que o de uma empresa media do setor."
                ),
                acao="Confira se o spread de crédito usado reflete esse nivel de risco.",
                referencia="CFA Institute, Corporate Finance",
            )
        )

    return achados

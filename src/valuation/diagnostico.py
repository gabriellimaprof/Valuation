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

# Faixas de referencia. Deliberadamente largas: servem para pegar o absurdo, nao
# para impor uma visao de mundo.
BETA_MINIMO, BETA_MAXIMO = 0.3, 2.5
WACC_MINIMO_BRL, WACC_MAXIMO_BRL = 0.07, 0.30
PESO_PERPETUIDADE_ALTO = 0.75
ALAVANCAGEM_ALTA = 3.5
MARGEM_ROIC_WACC_EXCEPCIONAL = 0.10


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
) -> Diagnostico:
    """Roda a bateria de verificacoes sobre um valuation ja calculado.

    ``analise`` habilita as comparacoes com o historico da propria empresa, que
    sao as mais uteis: uma margem de 25% nao e otimista em abstrato, e otimista
    para quem entregou 18% nos ultimos cinco anos.

    ``crescimento_nominal_economia`` e o teto natural do crescimento perpetuo.
    Sem ele, e estimado como inflacao de longo prazo mais 2% de PIB real.
    """
    empresa = resultado.empresa
    wacc = resultado.dcf.taxa_desconto
    g = empresa.perpetuidade.crescimento_perpetuo
    if crescimento_nominal_economia is None:
        crescimento_nominal_economia = empresa.macro.inflacao_brl + 0.02

    achados: list[Achado] = []
    achados += _checar_perpetuidade(resultado, g, wacc, crescimento_nominal_economia)
    achados += _checar_reinvestimento(resultado, g, wacc)
    achados += _checar_custo_de_capital(resultado, wacc)
    achados += _checar_estrutura_do_valor(resultado)
    if analise is not None:
        achados += _checar_contra_historico(resultado, analise)

    return Diagnostico(achados=_ordenar(achados))


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
                    titulo=f"Crescimento perpetuo de {g:.1%} supera a economia",
                    detalhe=(
                        f"O modelo faz a empresa crescer {g:.1%} para sempre, acima do "
                        f"crescimento nominal estimado da economia ({teto_economia:.1%}). "
                        "Crescer acima da economia para sempre significa que a empresa "
                        "acabaria por se tornar maior que o proprio PIB."
                    ),
                    acao=(
                        f"Reduza o crescimento perpetuo para no maximo {teto_economia:.1%}, "
                        "ou alongue a projecao explicita se a empresa ainda tem uma fase "
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
                    titulo="Diferenca entre WACC e crescimento perpetuo muito estreita",
                    detalhe=(
                        f"WACC de {wacc:.2%} contra crescimento de {g:.2%}: o denominador "
                        f"da perpetuidade e apenas {wacc - g:.2%}. Nessa faixa, uma "
                        "mudanca de 0,5 p.p. em qualquer um dos dois altera o valor da "
                        "empresa em dezenas de por cento."
                    ),
                    acao=(
                        "Olhe a tabela de sensibilidade antes de defender o numero: "
                        "provavelmente a faixa de valor e larga demais para um numero unico."
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
                    titulo="Crescimento perpetuo sem reinvestimento explicito",
                    detalhe=(
                        f"A perpetuidade cresce {g:.1%} ao ano a partir do fluxo do ultimo "
                        "ano projetado, sem exigir reinvestimento para sustentar esse "
                        "crescimento. Isso costuma superestimar o valor terminal, porque "
                        "crescer para sempre exige investir para sempre."
                    ),
                    acao=(
                        "Informe o ROIC de perpetuidade. O modelo passa a descontar do "
                        "fluxo perpetuo a taxa de reinvestimento g/ROIC, que e a forma "
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
                        titulo=f"ROIC perpetuo ({roic_perp:.1%}) nao supera o WACC ({wacc:.1%})",
                        detalhe=(
                            "Quando o retorno sobre o capital nao supera o custo do capital, "
                            "cada real reinvestido destroi valor. Nesse regime, crescer "
                            "*reduz* o valor da empresa em vez de aumenta-lo."
                        ),
                        acao=(
                            "Se essa e mesmo a realidade do negocio, considere crescimento "
                            "perpetuo zero: a empresa vale mais distribuindo caixa do que "
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
                        titulo=f"ROIC perpetuo {roic_perp - wacc:.1%} acima do WACC, para sempre",
                        detalhe=(
                            f"O modelo assume ROIC de {roic_perp:.1%} contra WACC de "
                            f"{wacc:.1%} em perpetuidade. Manter esse spread para sempre "
                            "equivale a supor uma barreira de entrada que nunca e erodida "
                            "pela concorrencia."
                        ),
                        acao=(
                            "Justifique a vantagem competitiva (marca, rede, licenca, "
                            "escala) ou aproxime o ROIC perpetuo do WACC."
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
                    f"No ultimo ano projetado o capex e {capex_final / deprec_final:.2f}x a "
                    f"depreciacao, mas a empresa cresce {g:.1%} para sempre depois disso. "
                    "Uma base de ativos que encolhe nao sustenta receita que cresce."
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
                        titulo=f"Retorno sobre o capital novo implicito de {mediana:.0%}",
                        detalhe=(
                            "A projecao gera NOPAT adicional muito acima do que reinveste: "
                            f"cada real investido produz {mediana:.2f} de lucro operacional "
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
                        titulo="A projecao reinveste e o lucro operacional cai",
                        detalhe=(
                            "O NOPAT projetado diminui apesar do reinvestimento. Se isso e "
                            "intencional (setor em declinio), tudo bem; se nao, ha "
                            "inconsistencia entre margens e investimento."
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
                titulo=f"Beta realavancado de {cc.beta_realavancado:.2f} fora da faixa usual",
                detalhe=(
                    f"Betas de empresas listadas concentram-se entre {BETA_MINIMO:.1f} e "
                    f"{BETA_MAXIMO:.1f}. Fora dessa faixa costuma haver erro no beta do "
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
                titulo=f"WACC de {wacc:.2%} fora da faixa tipica em BRL nominal",
                detalhe=(
                    f"Para empresas brasileiras, o WACC nominal em reais costuma ficar "
                    f"entre {WACC_MINIMO_BRL:.0%} e {WACC_MAXIMO_BRL:.0%}. Valores fora "
                    "disso geralmente vem de taxa livre de risco, risco-pais ou inflacao "
                    "informados em unidade errada."
                ),
                acao="Confira se todas as taxas estao em decimais (0,045 e nao 4,5).",
                referencia="Damodaran, country risk premiums",
            )
        )

    if cc.kd_bruto_brl > cc.ke_brl:
        achados.append(
            Achado(
                codigo="kd_acima_do_ke",
                severidade=ALERTA,
                titulo="Custo da divida acima do custo do capital proprio",
                detalhe=(
                    f"Kd de {cc.kd_bruto_brl:.2%} contra Ke de {cc.ke_brl:.2%}. O credor "
                    "tem prioridade sobre o acionista no recebimento, entao normalmente "
                    "exige menos retorno. O inverso sugere erro em uma das duas pontas."
                ),
                acao="Reveja o spread de credito ou o premio de risco do equity.",
                referencia="CFA Institute, Corporate Finance",
            )
        )

    if premissas.divida_pl_alvo > ALAVANCAGEM_ALTA:
        achados.append(
            Achado(
                codigo="alavancagem_alvo_alta",
                severidade=INFORMACAO,
                titulo=f"Estrutura de capital alvo bastante alavancada (D/E {premissas.divida_pl_alvo:.1f})",
                detalhe=(
                    "Com essa alavancagem, o beta realavancado e o custo da divida deveriam "
                    "refletir risco de credito relevante. O modelo nao ajusta isso sozinho."
                ),
                acao="Considere elevar o spread de credito coerentemente com a alavancagem.",
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
                titulo=f"{peso:.0%} do valor vem da perpetuidade",
                detalhe=(
                    "Quase todo o valor esta depois do horizonte projetado, ou seja, "
                    "depende de duas premissas (crescimento perpetuo e taxa de desconto) "
                    "em vez das projecoes que voce construiu linha a linha."
                ),
                acao=(
                    "Alongue a projecao explicita ate a empresa atingir maturidade -- "
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
                    f"O Enterprise Value de {resultado.enterprise_value:,.1f} nao cobre a "
                    "divida liquida e os demais itens da ponte. Ou a empresa esta "
                    "efetivamente insolvente, ou ha erro de unidade entre a projecao e o "
                    "balanco."
                ),
                acao=(
                    "Confirme que projecao e ponte estao na mesma unidade (ambas em R$ mil "
                    "ou ambas em R$ milhoes)."
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
                titulo="Todos os fluxos de caixa projetados sao negativos",
                detalhe=(
                    "A empresa queima caixa em todo o horizonte explicito e ainda assim "
                    "recebe um valor terminal positivo. O valor fica inteiramente apoiado "
                    "em uma recuperacao que o modelo nao mostra."
                ),
                acao="Alongue a projecao ate o ano em que a empresa passa a gerar caixa.",
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
                    "tenha como financiar o periodo."
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
                        f"Margem EBITDA projetada ({margem_projetada:.1%}) acima do melhor "
                        f"ano historico ({maxima:.1%})"
                    ),
                    detalhe=(
                        "O modelo assume que a empresa passa a operar acima do melhor "
                        "desempenho que ja teve, e mantem esse patamar."
                    ),
                    acao=(
                        "Explicite o que muda: ganho de escala, mix, reestruturacao, "
                        "repasse de preco. Sem uma razao concreta, use a mediana historica."
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
                        f"Margem EBITDA projetada ({margem_projetada:.1%}) abaixo do pior "
                        f"ano historico ({minima:.1%})"
                    ),
                    detalhe="A projecao e mais conservadora do que qualquer ano ja realizado.",
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
                        f"Crescimento projetado ({crescimento_projetado:.1%}) bem acima do "
                        f"historico ({cagr_hist:.1%})"
                    ),
                    detalhe=(
                        "A aceleracao precisa vir de algum lugar: novo mercado, nova "
                        "capacidade, aquisicao. Nenhum deles e gratuito."
                    ),
                    acao=(
                        "Verifique se o capex projetado comporta a expansao de receita "
                        "assumida."
                    ),
                    referencia="Damodaran, Investment Valuation, cap. 11",
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
                    f"ROIC de perpetuidade ({roic_perp:.1%}) acima do historico "
                    f"({roic_hist:.1%})"
                ),
                detalhe=(
                    "A perpetuidade assume um retorno sobre o capital melhor do que a "
                    "empresa costuma entregar, e para sempre."
                ),
                acao="Ancore o ROIC perpetuo no historico, salvo mudanca estrutural clara.",
                referencia="Koller, Goedhart & Wessels, Valuation, cap. 10",
            )
        )

    alavancagem = analise.ultimo("Divida liquida / EBITDA")
    if np.isfinite(alavancagem) and alavancagem > ALAVANCAGEM_ALTA:
        achados.append(
            Achado(
                codigo="alavancagem_historica_alta",
                severidade=INFORMACAO,
                titulo=f"Divida liquida / EBITDA de {alavancagem:.1f}x no ultimo ano",
                detalhe=(
                    "Alavancagem nesse patamar costuma vir acompanhada de covenants e de "
                    "custo de divida mais alto do que o de uma empresa media do setor."
                ),
                acao="Confira se o spread de credito usado reflete esse nivel de risco.",
                referencia="CFA Institute, Corporate Finance",
            )
        )

    return achados

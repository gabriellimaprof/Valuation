"""Ferramentas de valuation de empresas com foco no mercado brasileiro.

Fluxo tipico::

    from valuation import carregar_empresa, avaliar, exportar_excel

    empresa = carregar_empresa("exemplos/empresa_exemplo.yaml")
    resultado = avaliar(empresa, meio_de_ano=True)
    print(resultado.resumo())
    exportar_excel(resultado, "saida/valuation.xlsx")
"""

from .custo_capital import (
    ResultadoCustoCapital,
    calcular_custo_capital,
    converter_taxa,
    desalavancar_beta,
    realavancar_beta,
)
from .dcf import ResultadoDCF, avaliar_dcf, fatores_desconto, ponte_ev_equity
from .entrada import ArquivoModelo, carregar_comparaveis, carregar_empresa, carregar_modelo
from .erros import CombinacaoInviavel
from .excel import exportar_excel
from .modelo import ResultadoValuation, avaliar, substituir, substituir_varios
from .multiplos import (
    Alvo,
    Comparavel,
    avaliar_por_multiplos,
    estatisticas,
    faixa_de_valor,
    tabela_comparaveis,
)
from .premissas import (
    ALIQUOTA_IR_BRASIL,
    Empresa,
    PonteValor,
    PremissasCustoCapital,
    PremissasMacro,
    PremissasOperacionais,
    PremissasPerpetuidade,
)
from .projecao import Projecao, projetar
from .sensibilidade import (
    Distribuicao,
    ResultadoSimulacao,
    cenarios,
    monte_carlo,
    tabela_sensibilidade,
)

__version__ = "0.1.0"

__all__ = [
    "ALIQUOTA_IR_BRASIL",
    "Alvo",
    "ArquivoModelo",
    "CombinacaoInviavel",
    "Comparavel",
    "Distribuicao",
    "Empresa",
    "PonteValor",
    "PremissasCustoCapital",
    "PremissasMacro",
    "PremissasOperacionais",
    "PremissasPerpetuidade",
    "Projecao",
    "ResultadoCustoCapital",
    "ResultadoDCF",
    "ResultadoSimulacao",
    "ResultadoValuation",
    "avaliar",
    "avaliar_dcf",
    "avaliar_por_multiplos",
    "calcular_custo_capital",
    "carregar_comparaveis",
    "carregar_empresa",
    "carregar_modelo",
    "cenarios",
    "converter_taxa",
    "desalavancar_beta",
    "estatisticas",
    "exportar_excel",
    "faixa_de_valor",
    "fatores_desconto",
    "monte_carlo",
    "ponte_ev_equity",
    "projetar",
    "realavancar_beta",
    "substituir",
    "substituir_varios",
    "tabela_comparaveis",
    "tabela_sensibilidade",
]

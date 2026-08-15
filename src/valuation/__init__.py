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
from .casos_especiais import (
    capitalizar_leasing_operacional,
    capitalizar_pesquisa_desenvolvimento,
    normalizar_margem_ciclica,
)
from .dados_setoriais import (
    SETORES,
    buscar_setor,
    listar_setores,
    macro_do_pais,
    premissas_do_setor,
)
from .dcf import ResultadoDCF, avaliar_dcf, fatores_desconto, ponte_ev_equity
from .diagnostico import Achado, Diagnostico, diagnosticar
from .entrada import ArquivoModelo, carregar_comparaveis, carregar_empresa, carregar_modelo
from .erros import CombinacaoInviavel
from .excel import exportar_excel
from .historico import AnaliseHistorica, analisar, sugerir_premissas
from .importacao import Demonstracoes, gerar_template, importar
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
from .projecao import Projecao, calcular_impostos, projetar
from .retorno import (
    DecomposicaoTSR,
    PonteDeValor,
    ProjecaoAcionista,
    decompor_ponte_ev,
    decompor_tsr,
    multiplo_de_saida_do_dcf,
    preco_para_tsr,
    projetar_acionista,
    tir,
)
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
    "Achado",
    "Alvo",
    "AnaliseHistorica",
    "ArquivoModelo",
    "CombinacaoInviavel",
    "Comparavel",
    "DecomposicaoTSR",
    "Demonstracoes",
    "Diagnostico",
    "Distribuicao",
    "Empresa",
    "PonteDeValor",
    "PonteValor",
    "PremissasCustoCapital",
    "PremissasMacro",
    "PremissasOperacionais",
    "PremissasPerpetuidade",
    "Projecao",
    "ProjecaoAcionista",
    "ResultadoCustoCapital",
    "ResultadoDCF",
    "ResultadoSimulacao",
    "ResultadoValuation",
    "SETORES",
    "analisar",
    "avaliar",
    "avaliar_dcf",
    "avaliar_por_multiplos",
    "buscar_setor",
    "calcular_custo_capital",
    "calcular_impostos",
    "capitalizar_leasing_operacional",
    "capitalizar_pesquisa_desenvolvimento",
    "carregar_comparaveis",
    "carregar_empresa",
    "carregar_modelo",
    "cenarios",
    "converter_taxa",
    "decompor_ponte_ev",
    "decompor_tsr",
    "desalavancar_beta",
    "diagnosticar",
    "estatisticas",
    "exportar_excel",
    "faixa_de_valor",
    "fatores_desconto",
    "gerar_template",
    "importar",
    "listar_setores",
    "macro_do_pais",
    "monte_carlo",
    "multiplo_de_saida_do_dcf",
    "normalizar_margem_ciclica",
    "ponte_ev_equity",
    "preco_para_tsr",
    "premissas_do_setor",
    "projetar",
    "projetar_acionista",
    "realavancar_beta",
    "substituir",
    "substituir_varios",
    "sugerir_premissas",
    "tabela_comparaveis",
    "tabela_sensibilidade",
    "tir",
]

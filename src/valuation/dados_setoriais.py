"""Parametros de referencia por setor e por pais.

**Leia isto antes de usar em trabalho real.** Os numeros embarcados aqui sao
*valores de referencia* de ordem de grandeza, compilados para que o app funcione
sem depender de rede e para que um analista em formacao tenha um ponto de
partida plausivel. Eles **nao sao** a base oficial do Damodaran, nao sao
atualizados automaticamente e envelhecem: betas setoriais e premios de risco-pais
mudam todo ano.

Para trabalho que vai para cliente ou comite, baixe as planilhas oficiais em
``pages.stern.nyu.edu/~adamodar/New_Home_Page/data.html`` -- ``betas.xls`` (ou
``betaemerg.xls`` para mercados emergentes) e ``ctryprem.xlsx`` -- e carregue com
``carregar_betas_damodaran`` / ``carregar_risco_pais_damodaran``. Os valores
carregados substituem os embarcados.

Origem dos valores embarcados: ordens de grandeza tipicas de mercados
emergentes; ``ATUALIZADO_EM`` registra quando foram revisados pela ultima vez.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

ATUALIZADO_EM = "2026-01"
AVISO_REFERENCIA = (
    "Betas e D/E setoriais da planilha de mercados emergentes do Damodaran, "
    f"edicao de {ATUALIZADO_EM}, agregados por setor do app. E um instantaneo: "
    "para trabalho formal, carregue a edicao corrente."
)


@dataclass(frozen=True)
class Setor:
    """Parametros tipicos de um setor.

    ``beta_desalavancado`` ja vem sem o efeito da estrutura de capital, entao e
    ele que deve ser realavancado para o D/E alvo da empresa avaliada.
    """

    nome: str
    beta_desalavancado: float
    divida_pl_tipico: float
    margem_ebitda_tipica: float
    observacao: str = ""
    # Setor em que a divida e insumo, e nao financiamento. Nele o beta **nao se
    # realavanca**: o risco do deposito ja esta dentro do beta observado do
    # equity, e o D/E de um banco brasileiro (11,2x na mediana) levaria o Ke a
    # 41% em dolar. Ver ``PremissasCustoCapital.instituicao_financeira``.
    financeiro: bool = False


SETORES: tuple[Setor, ...] = (
    Setor("Agronegocio", 0.61, 0.58, 0.20, "Ciclico, sensivel a commodity e cambio"),
    Setor("Alimentos e bebidas", 0.73, 0.33, 0.18, "Defensivo, demanda estavel"),
    Setor("Bancos e servicos financeiros", 0.95, 0.00, float("nan"),
          "Valuation por lucro residual; WACC nao se aplica, e o beta nao se realavanca",
          financeiro=True),
    Setor("Bens de capital", 1.16, 0.14, 0.15, "Ciclico, ligado ao investimento"),
    Setor("Construcao civil", 0.48, 1.90, 0.16, "Muito ciclico e sensivel a juros"),
    Setor("Educacao", 0.81, 0.34, 0.22, ""),
    Setor("Energia eletrica", 0.47, 1.02, 0.35, "Regulado, fluxo previsivel, alavancado"),
    Setor("Farmaceutico e saude", 0.91, 0.23, 0.20, ""),
    Setor("Mineracao", 1.22, 0.25, 0.35, "Preco de commodity domina o resultado"),
    Setor("Papel e celulose", 0.64, 1.01, 0.30, "Ciclico e intensivo em capital"),
    Setor("Petroleo e gas", 1.14, 0.30, 0.30, "Preco de commodity domina o resultado"),
    Setor("Quimico e petroquimico", 0.99, 0.46, 0.14, ""),
    Setor("Saneamento", 0.43, 0.93, 0.40, "Regulado, fluxo muito previsivel"),
    Setor("Seguros", 0.85, 0.15, float("nan"), "Valuation por FCFE ou lucro residual"),
    Setor("Servicos de TI e software", 1.27, 0.08, 0.22, "Pouco intensivo em capital fixo"),
    Setor("Shopping centers e imobiliario", 0.64, 0.61, 0.60,
          "Margem alta porque a receita e aluguel; muito sensivel a juros"),
    Setor("Siderurgia e metalurgia", 1.01, 0.51, 0.18, "Ciclico"),
    Setor("Telecomunicacoes", 0.70, 0.32, 0.35, "Intensivo em capital, receita recorrente"),
    Setor("Transporte e logistica", 0.74, 0.81, 0.25, "Intensivo em capital"),
    Setor("Varejo", 0.86, 0.28, 0.10, "Margem baixa, giro alto"),
    Setor("Vestuario e calcados", 0.75, 0.26, 0.14, ""),
    Setor("Media e entretenimento", 1.21, 0.12, 0.20, ""),
)

POR_NOME: dict[str, Setor] = {s.nome: s for s in SETORES}

# **De onde vem cada numero da tabela acima.** Ate 2025-01 os betas eram ordens
# de grandeza compiladas a mao, e o proprio modulo avisava que nao eram a base
# oficial. Desde que a sugestao de WACC passou a usar o beta do setor, eles
# decidem o custo de capital de toda companhia, e ordem de grandeza nao basta.
#
# Cada setor do app agrega as industrias do Damodaran abaixo, ponderadas pelo
# numero de empresas, na planilha de **mercados emergentes** (`betaemerg.xls`,
# edicao de 2026-01-05). O beta e a **media 2021-26 do beta desalavancado
# corrigido por caixa** -- o que o proprio Damodaran indica como beta puro do
# negocio, e a media por ser menos volatil que o ano. A D/E e a da mesma
# planilha.
#
# **Bancos e Seguros nao foram trocados.** No banco a D/E inclui deposito (2,46
# na planilha) e o app nao realavanca beta de banco; o beta alavancado oficial,
# 0,59, derrubaria o Ke e o valor por lucro residual de toda instituicao sem que
# nada tivesse sido conferido. Na seguradora o float pesa como alavancagem pela
# mesma razao. Os dois pedem medicao propria.
#
# Medido o efeito, com a regra de teto de D/E 3 e piso de Kd 3%, nas 415
# companhias: a mediana do WACC sugerido vai de 12,4% para 12,0%, e as fora de
# 7%-30% passam de 1 para 3. As maiores mudancas: Construcao civil de 1,05 para
# 0,48 (a D/E tipica de incorporadora e 1,90, nao 0,60), Bens de capital de 0,95
# para 1,16, Papel e celulose de 0,90 para 0,64.
INDUSTRIAS_DAMODARAN: dict[str, tuple[str, ...]] = {
    "Agronegocio": ("Farming/Agriculture",),
    "Alimentos e bebidas": ("Food Processing", "Beverage (Alcoholic)", "Beverage (Soft)"),
    "Bens de capital": ("Machinery", "Electrical Equipment"),
    "Construcao civil": ("Homebuilding", "Real Estate (Development)"),
    "Educacao": ("Education",),
    "Energia eletrica": ("Power", "Utility (General)"),
    "Farmaceutico e saude": (
        "Drugs (Pharmaceutical)",
        "Hospitals/Healthcare Facilities",
        "Healthcare Support Services",
    ),
    "Mineracao": ("Metals & Mining",),
    "Papel e celulose": ("Paper/Forest Products",),
    "Petroleo e gas": ("Oil/Gas (Integrated)", "Oil/Gas (Production and Exploration)"),
    "Quimico e petroquimico": ("Chemical (Basic)", "Chemical (Diversified)"),
    "Saneamento": ("Utility (Water)",),
    "Servicos de TI e software": ("Software (System & Application)", "Computer Services"),
    "Shopping centers e imobiliario": ("Real Estate (Operations & Services)",),
    "Siderurgia e metalurgia": ("Steel",),
    "Telecomunicacoes": ("Telecom. Services", "Telecom (Wireless)"),
    "Transporte e logistica": ("Transportation", "Trucking"),
    "Varejo": ("Retail (General)", "Retail (Special Lines)", "Retail (Grocery and Food)"),
    "Vestuario e calcados": ("Apparel", "Shoe"),
    "Media e entretenimento": ("Entertainment", "Broadcasting"),
}


def setores_da_planilha(tabela: pd.DataFrame) -> dict[str, tuple[float, float]]:
    """``{setor: (beta desalavancado, D/E)}`` a partir da planilha carregada.

    Existe para que a proxima atualizacao da tabela seja um comando, e nao uma
    transcricao: carregue com `carregar_betas_damodaran` e compare.
    """
    colunas = {str(c).strip().lower(): c for c in tabela.columns}
    media = next((c for k, c in colunas.items() if k.startswith("average")), None)
    corrigido = colunas.get("unlevered beta corrected for cash")
    firmas = colunas.get("number of firms")
    razao = colunas.get("d/e ratio")
    if corrigido is None or firmas is None or razao is None:
        raise ValueError("A planilha nao traz beta corrigido por caixa, empresas e D/E.")
    saida = {}
    for setor, industrias in INDUSTRIAS_DAMODARAN.items():
        linhas = tabela.loc[[i for i in industrias if i in tabela.index]]
        if linhas.empty:
            continue
        pesos = pd.to_numeric(linhas[firmas], errors="coerce").fillna(0).astype(float)
        beta = pd.to_numeric(linhas[corrigido], errors="coerce")
        if media is not None:
            beta = pd.to_numeric(linhas[media], errors="coerce").fillna(beta)
        endividamento = pd.to_numeric(linhas[razao], errors="coerce")
        saida[setor] = (
            float(np.average(beta.astype(float), weights=pesos)),
            float(np.average(endividamento.astype(float), weights=pesos)),
        )
    return saida

# **O setor do cadastro da CVM, traduzido para os setores desta tabela.** A
# importacao ja guarda o setor da companhia (`Demonstracoes.fonte["setor"]`), e
# ate aqui a sugestao nao o usava: gravava beta 1,0 com a D/E do setor igual a
# da propria companhia, e o beta nunca era realavancado. A CSN, com 77% do
# capital em divida, saia com WACC de 6,4%.
#
# O prefixo "Emp. Adm. Part. - " e da holding e nao muda o negocio. Ficam **sem
# traducao** os setores que nao tem par nesta tabela (hospedagem, embalagens,
# "Sem Setor Principal") e os financeiros: uma companhia no plano industrial com
# setor "Intermediacao Financeira" nao deve virar banco por causa do cadastro --
# isso trocaria o metodo inteiro. Medido no universo de 2021-2025, a traducao
# cobre 384 das 415 companhias.
SETOR_DO_CADASTRO_CVM: dict[str, str] = {
    "Agricultura (Açúcar, Álcool e Cana)": "Agronegocio",
    "Alimentos": "Alimentos e bebidas",
    "Bebidas e Fumo": "Alimentos e bebidas",
    "Brinquedos e Lazer": "Media e entretenimento",
    "Comunicação e Informática": "Servicos de TI e software",
    "Comércio (Atacado e Varejo)": "Varejo",
    "Const. Civil, Mat. Const. e Decoração": "Construcao civil",
    "Construção Civil, Mat. Constr. e Decoração": "Construcao civil",
    "Educação": "Educacao",
    "Energia Elétrica": "Energia eletrica",
    "Extração Mineral": "Mineracao",
    "Farmacêutico e Higiene": "Farmaceutico e saude",
    "Máqs., Equip., Veíc. e Peças": "Bens de capital",
    "Máquinas, Equipamentos, Veículos e Peças": "Bens de capital",
    "Metalurgia e Siderurgia": "Siderurgia e metalurgia",
    "Papel e Celulose": "Papel e celulose",
    "Petroquímicos e Borracha": "Quimico e petroquimico",
    "Petróleo e Gás": "Petroleo e gas",
    "Saneamento, Serv. Água e Gás": "Saneamento",
    "Seguradoras e Corretoras": "Seguros",
    "Serviços Médicos": "Farmaceutico e saude",
    "Serviços médicos": "Farmaceutico e saude",
    "Serviços Transporte e Logística": "Transporte e logistica",
    "Telecomunicações": "Telecomunicacoes",
    "Têxtil e Vestuário": "Vestuario e calcados",
}

# O beta de quem nao tem setor traduzido: a mediana dos setores nao financeiros,
# e nao 1,0. Um marcador que o app realavanca vira premissa, e a mediana e o
# marcador menos arbitrario que a propria tabela oferece.
BETA_DESALAVANCADO_SEM_SETOR: float = float(
    np.median([s.beta_desalavancado for s in SETORES if not s.financeiro])
)


def setor_do_cadastro(nome_cvm: str | None) -> Setor | None:
    """O setor desta tabela para o setor do cadastro da CVM, ou ``None``."""
    if not nome_cvm:
        return None
    nome = str(nome_cvm).replace("Emp. Adm. Part. - ", "").strip()
    traduzido = SETOR_DO_CADASTRO_CVM.get(nome)
    setor = POR_NOME.get(traduzido) if traduzido else None
    if setor is None or setor.financeiro:
        return None
    return setor


@dataclass(frozen=True)
class Pais:
    """Parametros de mercado de um pais."""

    nome: str
    risco_pais: float
    inflacao_longo_prazo: float
    aliquota_ir: float


PAISES: tuple[Pais, ...] = (
    Pais("Brasil", 0.025, 0.040, 0.34),
    Pais("Estados Unidos", 0.000, 0.023, 0.25),
    Pais("Mexico", 0.019, 0.035, 0.30),
    Pais("Chile", 0.011, 0.030, 0.27),
    Pais("Colombia", 0.028, 0.035, 0.35),
    Pais("Argentina", 0.095, 0.150, 0.35),
    Pais("Peru", 0.017, 0.025, 0.295),
)

PAISES_POR_NOME: dict[str, Pais] = {p.nome: p for p in PAISES}

# Premio de risco de mercado maduro (EUA). Referencia de ordem de grandeza.
ERP_MADURO_REFERENCIA = 0.045


def listar_setores() -> pd.DataFrame:
    """Tabela dos setores disponiveis, para exibir na interface."""
    return pd.DataFrame(
        [
            {
                "Setor": s.nome,
                "Beta desalavancado": s.beta_desalavancado,
                "D/E tipico": s.divida_pl_tipico,
                "Margem EBITDA tipica": s.margem_ebitda_tipica,
                "Observacao": s.observacao,
            }
            for s in SETORES
        ]
    ).set_index("Setor")


def buscar_setor(nome: str) -> Setor:
    """Encontra um setor pelo nome, com busca tolerante a maiusculas e acentos."""
    if nome in POR_NOME:
        return POR_NOME[nome]

    from .importacao.esquema import normalizar

    alvo = normalizar(nome)
    for setor in SETORES:
        if normalizar(setor.nome) == alvo:
            return setor
    for setor in SETORES:
        if alvo and alvo in normalizar(setor.nome):
            return setor
    raise ValueError(
        f"Setor {nome!r} nao encontrado. Disponiveis: {sorted(POR_NOME)}"
    )


def premissas_do_setor(
    nome_setor: str,
    pais: str = "Brasil",
    divida_pl_alvo: float | None = None,
    **extras,
):
    """Monta ``PremissasCustoCapital`` a partir do setor e do pais escolhidos.

    Usa o beta desalavancado do setor e o D/E da propria empresa (ou o tipico do
    setor, se nao informado) -- que e a ordem correta: o beta do setor descreve o
    risco do *negocio*, e a alavancagem que o converte em risco do *acionista* e
    a da empresa avaliada.
    """
    from .premissas import PremissasCustoCapital

    setor = buscar_setor(nome_setor)
    dados_pais = PAISES_POR_NOME.get(pais)
    if dados_pais is None:
        raise ValueError(
            f"Pais {pais!r} nao encontrado. Disponiveis: {sorted(PAISES_POR_NOME)}"
        )

    alvo = setor.divida_pl_tipico if divida_pl_alvo is None else divida_pl_alvo
    return PremissasCustoCapital(
        rf_usd=extras.pop("rf_usd", 0.045),
        erp_maduro=extras.pop("erp_maduro", ERP_MADURO_REFERENCIA),
        risco_pais=extras.pop("risco_pais", dados_pais.risco_pais),
        beta_desalavancado=setor.beta_desalavancado,
        beta_alavancado_setor=None,
        divida_pl_alvo=alvo,
        instituicao_financeira=setor.financeiro,
        **extras,
    )


def macro_do_pais(pais: str = "Brasil"):
    """Monta ``PremissasMacro`` com inflacao e aliquota do pais escolhido."""
    from .premissas import PremissasMacro

    dados = PAISES_POR_NOME.get(pais)
    if dados is None:
        raise ValueError(f"Pais {pais!r} nao encontrado.")
    eua = PAISES_POR_NOME["Estados Unidos"]
    return PremissasMacro(
        inflacao_brl=dados.inflacao_longo_prazo,
        inflacao_usd=eua.inflacao_longo_prazo,
        aliquota_ir=dados.aliquota_ir,
    )


# ---------------------------------------------------------------------------
# Carga das planilhas oficiais do Damodaran
# ---------------------------------------------------------------------------


def carregar_betas_damodaran(caminho: str | Path) -> pd.DataFrame:
    """Le a planilha de betas por setor publicada pelo Damodaran.

    O arquivo oficial tem varias linhas de cabecalho antes da tabela; a leitura
    localiza a linha que contem a coluna de nome do setor e a de beta
    desalavancado, em vez de assumir uma posicao fixa que muda a cada edicao.

    Devolve um DataFrame indexado pelo setor, com as colunas encontradas.
    """
    caminho = Path(caminho)
    if not caminho.exists():
        raise FileNotFoundError(f"Planilha de betas nao encontrada: {caminho}")

    # **A tabela nao esta na primeira aba.** Na edicao de 2026-01 a planilha
    # abre em "Explanation & FAQs" e a tabela mora em "Industry Averages" -- e
    # este carregador lia so a aba 0, entao o caminho que o modulo recomenda
    # para trabalho formal **nunca carregou** a planilha oficial. Procurar o
    # cabecalho em todas as abas aguenta a proxima troca de ordem tambem.
    abas = pd.read_excel(caminho, sheet_name=None, header=None, dtype=object)
    aba_da_tabela = linha_cabecalho = None
    for nome_aba, bruto in abas.items():
        for indice in range(min(len(bruto), 30)):
            textos = [
                str(v).strip().lower() for v in bruto.iloc[indice] if pd.notna(v)
            ]
            if any("industry name" in t for t in textos) and any(
                "beta" in t for t in textos
            ):
                aba_da_tabela, linha_cabecalho = nome_aba, indice
                break
        if aba_da_tabela is not None:
            break
    if aba_da_tabela is None:
        raise ValueError(
            f"{caminho.name} nao parece a planilha de betas do Damodaran: nao "
            "encontrei, em aba nenhuma, um cabecalho com 'Industry Name' e 'Beta'."
        )

    tabela = pd.read_excel(caminho, sheet_name=aba_da_tabela, header=linha_cabecalho)
    tabela.columns = [str(c).strip() for c in tabela.columns]
    coluna_setor = next(c for c in tabela.columns if "industry name" in c.lower())
    tabela = tabela.dropna(subset=[coluna_setor]).set_index(coluna_setor)
    return tabela


def carregar_risco_pais_damodaran(caminho: str | Path) -> pd.DataFrame:
    """Le a planilha de premios de risco-pais publicada pelo Damodaran."""
    caminho = Path(caminho)
    if not caminho.exists():
        raise FileNotFoundError(f"Planilha de risco-pais nao encontrada: {caminho}")

    bruto = pd.read_excel(caminho, sheet_name=0, header=None, dtype=object)
    linha_cabecalho = None
    for indice in range(min(len(bruto), 30)):
        textos = [str(v).strip().lower() for v in bruto.iloc[indice] if v is not None]
        if any(t == "country" for t in textos):
            linha_cabecalho = indice
            break
    if linha_cabecalho is None:
        raise ValueError(
            f"{caminho.name} nao parece a planilha de risco-pais do Damodaran: "
            "nao encontrei uma coluna 'Country'."
        )

    tabela = pd.read_excel(caminho, sheet_name=0, header=linha_cabecalho)
    tabela.columns = [str(c).strip() for c in tabela.columns]
    coluna_pais = next(c for c in tabela.columns if c.lower() == "country")
    return tabela.dropna(subset=[coluna_pais]).set_index(coluna_pais)


def beta_de(tabela: pd.DataFrame, setor: str) -> float:
    """Extrai o beta desalavancado de um setor em uma tabela oficial carregada."""
    candidatas = [
        c
        for c in tabela.columns
        if "unlevered" in str(c).lower() and "beta" in str(c).lower()
    ]
    if not candidatas:
        raise ValueError(
            "A tabela nao tem coluna de beta desalavancado ('Unlevered beta')."
        )
    coluna = candidatas[0]
    if setor not in tabela.index:
        aproximados = [i for i in tabela.index if setor.lower() in str(i).lower()]
        if not aproximados:
            raise ValueError(f"Setor {setor!r} nao encontrado na tabela carregada.")
        setor = aproximados[0]
    valor = float(tabela.loc[setor, coluna])
    if not np.isfinite(valor):
        raise ValueError(f"Beta invalido para {setor!r} na tabela carregada.")
    return valor

# Contexto do projeto

App e biblioteca de **valuation de empresas** com foco no mercado brasileiro,
em português. Este arquivo é o que uma sessão nova precisa saber antes de mexer
em qualquer coisa.

## O que é

Um app Streamlit em dez telas, por cima de um motor de valuation em Python.
Importa demonstrações financeiras, analisa o histórico, projeta o futuro, monta
o custo de capital, desconta os fluxos, decompõe o retorno esperado, testa
sensibilidade, critica o próprio modelo e exporta uma planilha Excel com
fórmulas vivas.

Serve dois públicos ao mesmo tempo: o analista experiente, que segue direto
pelas telas, e o analista em formação, que lê os blocos explicativos. **Isso não
é enfeite — é requisito.** Cada tela explica o que calcula, por que aquilo afeta
o valor e qual é o erro comum naquele ponto.

## Como rodar

```bash
python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[app,dev]"

streamlit run app/main.py     # o app
pytest                        # 542 testes
valuation dcf exemplos/empresa_exemplo.yaml --excel modelo.xlsx   # a CLI
```

Python 3.11+.

## Arquitetura

```
src/valuation/          motor, sem nenhuma dependência do Streamlit
  premissas.py          estruturas de entrada e suas validações
  importacao/           leitura de DFs de qualquer origem → vocabulário canônico
    esquema.py          contas canônicas, sinônimos e códigos CVM
    leitura.py          números, cabeçalhos de ano, coluna de códigos
    importador.py       orquestra e devolve Demonstracoes
    cvm.py              baixa os Dados Abertos da CVM; formato longo → anos
    template.py         gera o template preenchível
  historico.py          indicadores, DuPont, ROIC, premissas sugeridas
  custo_capital.py      beta, CAPM com risco-país, Kd, WACC
  projecao.py           projeção explícita, FCFF, FCFE, prejuízo fiscal
  dcf.py                desconto, valor terminal, ponte EV → equity
  retorno.py            TIR, TSR e decomposição, ponte com desalavancagem
  multiplos.py          avaliação relativa
  sensibilidade.py      tabelas, cenários, Monte Carlo
  diagnostico.py        verificações de consistência do modelo
  qualidade.py          o lucro vira caixa? veredito com o porquê
  casos_especiais.py    P&D, ciclicidade, leasing
  dados_setoriais.py    betas e prêmios por setor e país
  mercado.py            curva de NTN-B e Focus; risco-país implícito
  projeto.py            salvar e retomar um valuation inteiro
  comparacao.py         ponte do que moveu o valor entre duas versoes
  biblioteca.py         pasta local de valuations, desligada por padrão
  excel.py              exportação com fórmulas vivas
  modelo.py             orquestração e substituição de premissas
app/                    interface Streamlit
  paginas/              uma tela por etapa do fluxo
  tema.py graficos.py componentes.py textos.py estado.py
```

**O motor não conhece o Streamlit.** Toda regra de negócio fica em
`src/valuation/`; `app/` só apresenta. Não mova lógica para as telas.

## Convenções que não devem ser quebradas

**Taxas são decimais.** `0.12` é 12%. Na interface o usuário digita pontos
percentuais (12,5) e a tela converte — pedir 0,125 é convite a erro de ordem de
grandeza.

**Premissas são dataclasses `frozen=True`.** Alterações vão por
`substituir_varios(objeto, {"caminho.pontilhado": valor})`, que aplica tudo numa
operação só. Aplicar uma de cada vez passa por estados intermediários inválidos.

**`CombinacaoInviavel` versus `ValueError`.** Premissa economicamente impossível
(g acima do WACC) vira `NaN` na tabela e rodada descartada no Monte Carlo. Nome
de premissa digitado errado **levanta erro** — uma tabela inteira de `NaN` por
causa de um typo é pior que nenhuma tabela, porque parece resultado.

**Nada é descartado em silêncio.** O importador devolve linhas não reconhecidas,
contas derivadas e divergências contábeis como campos do resultado, e a tela
mostra tudo.

**O app não grava nada em disco — exceto quando mandam.** O estado vive na
sessão, e é isso que permite publicar num servidor compartilhado sem revisar o
código inteiro. A única exceção é `biblioteca.py`, que **nasce desligada**: só
existe quando `VALUATION_BIBLIOTECA` aponta para uma pasta, o que é escolha de
quem roda o app na própria máquina. Num deploy a variável não é definida e não
há caminho de código em que o servidor comece a guardar valuations por acidente.
Ao mexer ali, mantenha essa propriedade: o botão não existe quando desligada, em
vez de existir e falhar.

**Os arquivos da CVM têm armadilhas que já custaram caro.** `ORDEM_EXERC` traz
`ÚLTIMO` e `PENÚLTIMO` no mesmo arquivo — o zip de 2024 já contém 2023, e
empilhar anos sem filtrar duplica o ano do meio. `ESCALA_MOEDA` diz se os
valores estão em `MIL` ou em `UNIDADE`, e **varia entre empresas do mesmo
arquivo**; ignorá-lo erra a empresa por mil vezes. Todas estão travadas por
teste em `tests/test_importacao_cvm.py`, contra recorte do arquivo real.

**O código CVM só vale dentro do plano em que foi escrito.** A CVM publica
planos de contas distintos para indústria, bancos e seguradoras, e o mesmo
código muda de conta entre eles: `3.06` é "Resultado Financeiro" em 450
companhias e "IR e CSLL" em 17. O plano é detectado uma vez por companhia pelo
topo da DRE; fora do industrial o reconhecimento passa a ser só pelo rótulo e a
tela avisa. Confiar no código sem isso põe número errado na conta certa, calado.

**Capex, juros pagos e dividendos pagos não existem como linha única.** A CVM
padroniza só os totais de seção da DFC (`6.01`, `6.02`, `6.03`); abaixo é conta
livre. Cada um chega partido em várias rubricas e é remontado por soma em
`REGRAS_SOMADAS`, que declara o que **exclui** — "Dividendos recebidos" aparece
em 80 companhias e não é dividendo pago; venda de imobilizado fala de
imobilizado e não é capex. A direção é o que separa, não o assunto.

**Textos em português acentuado, números no padrão brasileiro** (milhar com
ponto, decimal com vírgula). Use os formatadores existentes; não escreva
`f"{x:.1%}"` em texto de usuário.

**Gráficos** seguem `app/graficos.py`: nenhum eixo secundário, cor por
identidade em ordem fixa, escala sequencial de um tom só, tabela de dados ao
lado de todo gráfico. A paleta em `app/tema.py` foi validada para daltonismo e
contraste em modo claro e escuro — **não troque cor por gosto**.

## Decisões de modelagem

Estas afetam o número final. Não as altere sem entender o porquê.

- **Ke montado em USD nominal** (`rf + β × ERP + λ × risco-país`) e convertido
  para BRL por diferencial de inflação. Somar prêmio americano a taxa brasileira
  contaria risco soberano duas vezes.
- **Perpetuidade com reinvestimento normalizado**: `NOPAT_n × (1+g) × (1 − g/ROIC)`.
- **Retornos sobre capital médio** (abertura + fechamento) / 2, como o CFA manda.
- **Capital de giro é estoque**; a variação é derivada. Só recebíveis, estoques e
  fornecedores — caixa e dívida já estão na ponte.
- **Imposto sobre o EBIT**, porque o FCFF é desalavancado. Prejuízo fiscal segue
  a **trava dos 30%** brasileira.
- **Kd vem do juro pago na DFC, não da despesa financeira da DRE.** A linha
  `3.06.02` da CVM chama-se "Despesas Financeiras" mas junta variação cambial e
  monetária de todo o passivo: na WEG de 2024 dá 48% da dívida, contra 4,5% de
  juro efetivamente pago. Pela DRE, 28% das 467 companhias de 2024 recebiam Kd
  acima de 25% — WACC inflado, valor derrubado, sem aviso. Com o juro pago, zero.
  Acima de `KD_MAXIMO_PLAUSIVEL` o Kd é descartado e montado sinteticamente.
- **Múltiplos de EV e de equity não se misturam** na ponte da dívida.
- **TSR decomposto pela identidade exata**, com o termo cruzado explícito:
  `g_lucro + g_múltiplo + (g_lucro × g_múltiplo) + dividendos`. A regra de bolso
  do mercado omite o termo cruzado.
- **Monte Carlo com semente fixa** — resultado que muda a cada execução é
  indefensável em revisão.

## Como testar

`pytest` roda tudo. As regras que valem:

- **Contas conferidas na mão** onde é possível (trava dos 30%, capitalização de
  P&D, valor presente do leasing, casos isolados do TSR).
- **Identidades que precisam fechar**: DuPont multiplica de volta ao ROE; as
  parcelas do TSR somam a TIR; a ponte EV fecha exatamente; empresa sem dívida
  comprada pelo valor do DCF devolve exatamente o Ke.
- **As fórmulas do Excel são validadas célula a célula** contra o motor Python
  (`tests/test_excel_formulas.py`, usando o pacote `formulas`). Planilha que
  calcula diferente do motor é pior que planilha nenhuma.
- **O app é verificado no navegador**, com Playwright, percorrendo o fluxo real.
  Vários bugs sérios só apareceram assim — colisão de URL entre telas, markdown
  cru na tela, eixo do mapa de calor reinterpretado como número. **Rode o app e
  olhe antes de dar por pronto.**

## Estado atual

542 testes passando. Verificado de verdade: contas financeiras, identidades,
equivalência Excel/Python, as origens de importação, fluxo completo no
navegador.

O leitor da CVM foi construído **a partir dos arquivos baixados**, não de
memória: encoding, separador, colunas e domínios foram conferidos no arquivo
real antes de existir código. Os testes rodam contra recortes em bytes desses
mesmos arquivos (`tests/dados/cvm`), e o fluxo foi percorrido no navegador
importando a WEG de 2019 a 2025 pela tela nova.

**A importação foi rodada em lote nas 467 companhias com DFP consolidada de
2024**, e as identidades fecham em 100% delas: ativo = passivo; operacional +
investimento + financiamento + câmbio = variação de caixa; arrendamento e
debênture nunca excedem a dívida de que são parte. São 62 contas canônicas por
companhia, ante 26 antes.

**Não verificado, e é honesto dizer:**

1. A planilha nunca foi aberta no Excel de verdade (validada com o pacote
   `formulas`, que é independente mas não é o Excel).
2. Betas e prêmios de risco-país embarcados são **valores de referência de ordem
   de grandeza**, não a base oficial do Damodaran. O app rotula isso na tela.
3. Da CVM, só a **DFP** (anual) é lida. O ITR trimestral tem estrutura parecida
   e não foi tocado.
4. Bancos e seguradoras (19 das 467) são detectados e avisados, mas o
   reconhecimento só por rótulo cobre bem menos contas, e o FCFF/WACC não se
   aplica a eles de qualquer forma.
5. As contas somadas por regra — capex, juros pagos, dividendos pagos — cobrem
   88%, 80% e 74% das companhias. O resto usa rótulo que nenhuma regra alcança
   e cai na lista de não reconhecidas, para mapeamento manual.

## Estressar macro, e o efeito que eu previ errado

Prática do dono do projeto, hoje representada no modelo: **IPCA de 5%** e **PIB
real de 1,5%** como base, com o **g perpétuo ancorado em IPCA ou em PIB
nominal** — `(1,05 × 1,015) − 1 = 6,58%`, composto e não somado.

Implementado: `PremissasMacro.pib_real` e `pib_nominal`;
`PremissasPerpetuidade.ancora` (`livre` / `ipca` / `pib_nominal`), resolvida em
`Empresa.__post_init__` porque é ali que macro e perpetuidade se encontram; o
teto do diagnóstico passou a sair de `macro.pib_nominal` em vez de
`inflacao_brl + 0.02` fixos; eixos e cenários macro na tela de Sensibilidade.

**Duas regras que existem para não criar armadilha silenciosa:**

1. Mexer no `g` por caminho pontilhado **solta a âncora**
   (`modelo.substituir_varios`). Sem isso, uma tabela de sensibilidade sobre o
   `g` ancorado sairia inteira igual — sem erro, sem aviso, sem nada na tela.
2. `macro.pib_real` **não altera o valuation** a menos que a âncora seja
   `pib_nominal`; fora disso ele só desloca o teto do diagnóstico. O eixo avisa.

### O que eu escrevi antes, e por que estava errado

Registrei aqui que estressar inflação seria "quase neutro em valor", e que o
pouco de efeito viria do spread `WACC − g` **abrindo**. Medido no modelo, com
choque de +2 p.p. de IPCA e `g` ancorado em PIB nominal:

| | g livre | g ancorado, sem ROIC | g ancorado, com ROIC 15% |
|---|---|---|---|
| Equity value | −56,5% | −3,2% | −47,5% |
| EV | −20,6% | −1,8% | −18,8% |

Dois erros no que eu tinha escrito:

- **O spread não abre, fecha.** `(1+g)` escala pelo fator cheio de inflação;
  `(1+WACC)` escala por menos, porque o Kd entra no WACC depois do benefício
  fiscal e o `(1−t)` não acompanha a inflação. No caso medido: WACC +1,92 p.p.
  contra g +2,03 p.p.
- **"Quase neutro" vale só sem normalização de reinvestimento.** Ligado o
  `roic_perpetuidade`, o fluxo perpétuo é `NOPAT × (1+g) × (1 − g/ROIC)`. Subir
  o `g` nominal sobe `g/ROIC` — de 37,1% para 50,6% do NOPAT no caso medido —
  enquanto o ROIC fica parado. O reinvestimento come mais do que o spread
  devolve, e o valor terminal cai 22,7%.

Não é defeito da âncora: é o modelo cobrando capital para sustentar crescimento
nominal maior. Mas **o padrão do app tem `roic_perpetuidade` ligado**, então o
caso "quase neutro" é a exceção, não a regra. A tela lê o modelo que está na
frente do usuário em vez de repetir a teoria — `_leitura_do_estresse` em
`app/paginas/sensibilidade.py`.

### Não há regra geral de sinal, e é por isso que a tela mede

Tentei salvar a conclusão dizendo "então ancorar amortece o choque". Também não
se sustenta. Medido com choque de +2 p.p. de IPCA, ROIC 15% ligado nos dois:

| | fixture (dívida líquida 650 sobre equity 487) | WEG 2024 (caixa líquido) |
|---|---|---|
| g livre | −56,5% | −17,9% |
| g ancorado em PIB nominal | −47,5% | −19,9% |

Ancorar **melhora** na empresa alavancada e **piora** na de caixa líquido. Na
WEG o choque de IPCA chega a bater mais forte que +2 p.p. de risco-país
(−17,9% contra −17,0% com g livre) — o oposto do que eu tinha registrado.

O que sobrevive como afirmação é só o mecanismo, e os testes em
`tests/test_macro.py` pinam ele e não as magnitudes: **risco-país entra só no
desconto; a inflação, ancorada, entra no desconto e no fluxo.** Qual dói mais é
propriedade da empresa, não do modelo. Nenhum texto de tela deve afirmar o sinal
— eles reportam o número medido.

**Ainda em aberto:** se o `g` é indexado à inflação, o ROIC marginal deveria ser
também — capital novo é comprado a preços novos. Deixar o ROIC nominal fixo
enquanto o `g` sobe embute uma piora real de intensidade de capital que ninguém
pediu. Não foi mexido: seria inventar uma premissa que o dono do projeto não
pediu, e o efeito é grande demais para entrar sem decisão dele.

Consequência prática que sobrevive: **prêmio de risco é o estresse macro mais
duro**, porque sobe o desconto sem contrapartida nenhuma no fluxo.

## Fontes de mercado já verificadas em campo (não implementadas)

Três APIs públicas foram confirmadas contra o endpoint real, com formato e
nomes exatos. Falta o módulo; a parte que costuma custar mais já está feita.

- **Focus / Expectativas de Mercado** (`olinda.bcb.gov.br/olinda/servico/Expectativas/versao/v1/odata`):
  IPCA, Selic, PIB e Câmbio por ano de referência, com mediana, desvio e nº de
  respondentes. Nomes dos indicadores acentuados: `"PIB Total"`, `"Câmbio"`.
- **SGS do BCB** (`api.bcb.gov.br/dados/serie/bcdata.sgs.{serie}/dados`):
  série 432 Selic meta, 13522 IPCA 12 meses. Aceita `/ultimos/N`.
- **Tesouro Transparente** — preço e taxa diários de todos os títulos, incluindo
  a curva NTN-B. Latin-1, `;`, decimal com vírgula: **as mesmas convenções da
  CVM**, então o tratamento existente serve.

**O uso mais valioso da NTN-B não é virar `rf`, é calibrar `risco_pais`.** O Ke
é montado em USD por decisão documentada acima, e trocar isso pela curva local
esbarra num ERP local que a série brasileira não sustenta. Mas a curva permite
medir o parâmetro que hoje é chutado: NTN-B 2035 a 8,0% real, nominalizada pelo
IPCA longo do Focus (3,5%), dá `rf` BRL de 11,8%; o `rf_usd` de 4,5% convertido
por diferencial de inflação dá 6,2%. A diferença — perto de 5,5 pontos — é o que
o mercado cobra de risco Brasil, contra os **2,5% embarcados** como padrão.

Não é risco soberano puro: carrega o descasamento entre a inflação assumida no
app e a do Focus, mais prêmio de liquidez do título. A ordem de grandeza é
informativa; o número exige separar essas parcelas. Antes de mudar o padrão,
medir o efeito nas 467 companhias — taxa de desconto errada só aparece no
número final.

## Para onde isto vai

O objetivo declarado pelo dono do projeto é automatizar **a primeira camada da
análise de empresas** — a parte braçal: do dado bruto da CVM a um **relatório
estruturado**, aplicando os frameworks de sempre (Porter, Damodaran, qualidade
de earnings, margem de segurança), e que se atualiza quando sai balanço novo.
A decisão de investir continua humana; o que sai da mão é a transcrição.

Isso reordena as lacunas. Medido contra esse objetivo:

- **Ler a CVM** — feito, e conferido conta a conta contra a linha publicada.
- **Montar valuation** — o motor já fazia.
- **Atualizar quando sai resultado** — existe, detecta exercício novo.
- **Comparar com pares** — parcial: `SETOR_ATIV` é classificação de registro e
  não dá peer group econômico.
- **Qualidade dos lucros** — as peças existem (conversão FCO/EBITDA, juro pago
  contra competência, giro pelo caixa) mas **espalhadas como indicadores**.
  Qualidade de earnings é uma tese com veredito, não uma linha de tabela.
- **Relatório estruturado** — **não existe**. O app são dez telas interativas;
  o objetivo termina num documento que alguém lê sem abrir o app. É a maior
  lacuna, e a base para fechá-la já está pronta.
- **Margem de segurança** — o motor calcula valor; falta a distância até o
  preço, que é o que fecha a decisão.

## Lacunas conhecidas

Em ordem de valor:

1. **Capitalização de P&D e de leasing sem tela** — existem e são testados em
   `casos_especiais.py`, mas só a normalização cíclica chegou à interface. Agora
   que o arrendamento é lido do balanço (`2.01.04.03`, `2.02.01.03`) e o direito
   de uso também (`1.02.03.02`), a tela tem de onde partir.
2. **FCFE sem editor de cronograma de dívida** — o motor suporta, a tela de Valor
   oferece a opção, mas não há onde informar a dívida ano a ano.
3. **A ponte de valor ainda ignora o arrendamento.** Ele é lido do balanço e
   entra na dívida bruta (é filho de `2.01.04`), mas não há tela para tratá-lo à
   parte — e em Petrobras ele é 49% da dívida. `casos_especiais.py` já sabe
   capitalizar leasing; falta ligar as duas pontas.
4. **Bancos e seguradoras** — FCFF/WACC não se aplica; precisaria de lucro
   residual ou FCFE com capital regulatório.
5. **Comparar duas versões do mesmo valuation** — diff de premissas com ponte
   mostrando o que moveu o valor.

## Como trabalhar neste projeto

- **Teste contra dado real antes de dar por pronto.** Os piores bugs desta base
  vieram de código de importação que nunca tinha visto o arquivo de verdade.
- **Diga o que não verificou.** Vale mais que parecer confiante.
- **Comentários explicam o porquê, não o quê.** O código diz o que faz.
- Commits em português, descrevendo a decisão e não só a mudança.

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
pytest                        # 621 testes
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
  margem.py             margem de segurança e DCF reverso
  pares.py              peer group por perfil econômico, e não por rótulo
  referencias.py        onde cada indicador cai na base brasileira, medido
  qualitativo.py        evidência para as perguntas de framework, sem respondê-las
  relatorio.py          o material todo em um markdown diffável
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

**A D&A não estava sendo lida, e isso era o maior erro da base.** O rótulo da
CVM vem no plural ("Depreciações e Amortizações") e o vocabulário declarava no
singular; e `reconhecer` escolhia o candidato **antes** de conferir a
demonstração, então a conta da DRE ganhava sempre e `depreciacao_dfc` era
inalcançável — apesar de a maioria das companhias só divulgar D&A no ajuste da
DFC. Resultado medido em 150 companhias de 2024: **8 tinham D&A reconhecida.
Depois da correção, 116.** As outras 142 tinham EBITDA igual ao EBIT, com a
mediana da base tendo D&A valendo 24% do EBIT. Na Raia Drogasil escondia R$ 1,85
bi; na WEG, R$ 812 mi.

Três correções, todas medidas antes de entrar: `singularizar()` reduz plurais
dos dois lados da comparação (1.085 linhas novas reconhecidas na base, 20 linhas
mudando de conta — e essas 20 eram correções); `reconhecer(..., demonstracao=)`
busca dentro da demonstração certa em vez de rejeitar depois; e
`Derivacao.substitui_zero` deixa a derivação passar por cima de uma série que a
DRE publica como zero.

**IFRS 16: as duas leituras não se misturam.** Desde 2019 o aluguel saiu do
resultado e virou depreciação mais juros, então o EBITDA subiu sem nada melhorar.
Medido: Raia Drogasil com margem EBITDA de 10,8% reportada e **6,5% ex-IFRS 16**;
Pague Menos 8,6% → 3,3%; Smart Fit **48,0% → 21,8%**. `ver_ex_ifrs16` monta as
duas visões a partir do desembolso na DFC (`EBITDA_ex = EBITDA − aluguel`,
`EBIT_ex = EBIT − juros`, `dívida_ex = dívida − arrendamento`).

A regra que a tela repete e os testes travam: **ou dívida com arrendamento sobre
EBITDA com aluguel, ou dívida sem sobre EBITDA sem.** Cruzar infla a alavancagem;
ao contrário, esconde. Cobertura: 258 das 467 companhias publicam o principal,
184 os juros — sem os juros o ajuste é declarado como **piso**. A depreciação do
direito de uso viria mais direto, mas só 10% a publicam.

**Corte de leitura sem medição vira ruído.** O sinal de juro descolado usava
2 p.p. de diferença entre a despesa financeira da DRE e o juro pago da DFC.
Medido em 368 companhias: **a mediana brasileira descola 8,2 p.p.**, porque a
linha `3.06.02` junta variação cambial e monetária de todo o passivo. O corte
antigo acusava **82,3% da base** — sinal que dispara em quatro de cada cinco não
dirige atenção, gasta. Os cortes agora são o P75 (16,9 p.p.) e o P90 (34,5 p.p.),
e acima de `KD_MAXIMO_PLAUSIVEL` o sinal se recusa a medir: com pouca dívida, a
razão deixa de ser custo de dívida (WEG dá 45%). Ver `referencias.py`.

**O arrendamento não fica onde o plano diz que fica.** A CVM reserva
`2.01.04.03` e `2.02.01.03` para "Financiamento por Arrendamento", dentro da
subárvore de empréstimos. **190 das 467 companhias de 2024 não usam esse lugar**:
põem o passivo do IFRS 16 em "Outras Obrigações" (`2.01.05`, `2.02.02`), fora da
dívida. São R$ 194,9 bilhões no total — 62,6% do que deveria ser a dívida bruta
da TIM, 55,8% da Claro, R$ 13,2 bi da GOL. Ler só o código fixo devolve dívida
menor que a real, e dívida menor vira equity value maior, **em silêncio**, porque
a árvore publicada continua fechando. `_somar_arrendamento_fora_da_divida` em
`cvm.py` devolve essas linhas à dívida bruta e ao arrendamento, contando só as
mais externas para não somar pai e filha, e avisa que corrigiu.

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

693 testes passando. Verificado de verdade: contas financeiras, identidades,
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
- **Comparar com pares** — feito em `pares.py`. `SETOR_ATIV` é classificação de
  registro; o critério agora é o do Damodaran — comparável é a empresa com
  risco, crescimento e fluxo de caixa parecidos —, medido em seis dimensões com
  z-score robusto (mediana e IQR, não média e desvio: a base tem margem de 300%
  e um único extremo definiria a escala inteira). Exige 4 das 6 dimensões, senão
  companhia sem dado aparece no topo por falta de dado. Universo de 447
  companhias em `~/.cache/valuation/universo`, construído por
  `python -m valuation.pares`.

  Medido: os pares da WEG passaram a ser Intelbras (0,28), Mahle Metal Leve
  (0,34) e Solar Bebidas (0,41) — indústrias com ROIC alto. Intelbras está
  registrada como "Comércio" e o filtro por setor nunca a encontraria.
- **Qualidade dos lucros** — feito. `qualidade.py` transforma os indicadores
  dispersos em veredito, e o veredito é o **pior** sinal, não a média deles:
  média é como um alerta some. Aba própria em Histórico.
- **Relatório estruturado** — feito. `relatorio.py` monta em markdown o que a
  empresa entregou, o que o modelo assume, quanto vale, o que o preço embute e
  o que pode dar errado. Markdown de propósito: rodar de novo em três meses e
  comparar com um diff mostra o que mudou no raciocínio; um PDF novo só mostra
  que mudou alguma coisa. **A seção final lista o que ele não verifica**, e as
  seções ausentes aparecem escritas — quem lê precisa distinguir "verificado e
  está bem" de "não foi verificado".
- **Margem de segurança** — feito, em `margem.py` e tela própria. Junto veio o
  **DCF reverso**: para cada premissa, o valor que faria o modelo dar exatamente
  o preço pedido. É o que troca "acho caro" por uma afirmação conferível.
- **Risco-país observado** — a medição pela curva de NTN-B ganhou tela (aba em
  Custo de capital). Não busca nada sem o usuário pedir, e o padrão continua sem
  mudar sozinho.

## Lacunas conhecidas

Em ordem de valor:

1. **Capitalização de P&D e de leasing sem tela** — existem e são testados em
   `casos_especiais.py`, mas só a normalização cíclica chegou à interface. Agora
   que o arrendamento é lido do balanço (`2.01.04.03`, `2.02.01.03`) e o direito
   de uso também (`1.02.03.02`), a tela tem de onde partir.
2. **FCFE sem editor de cronograma de dívida** — o motor suporta, a tela de Valor
   oferece a opção, mas não há onde informar a dívida ano a ano.
3. **Arrendamento fechado nas três pontas.** O estoque é lido certo (inclusive
   fora da subárvore de dívida), a leitura ex-IFRS 16 existe, e a projeção agora
   faz o passivo crescer: `arrendamento_pct_receita` em `PremissasOperacionais`
   transforma a adição anual em saída de caixa, porque contrato novo de aluguel
   não passa pelo capex. Nasce desligado e `sugerir_premissas` só o propõe
   quando o arrendamento passa de 2% da receita. Medido: Raia Drogasil perde
   10,2% de equity value com a linha ligada; Smart Fit, 48,7%.

   O que ainda **não** está fechado: a perpetuidade cresce o FCFF já líquido da
   adição, o que assume implicitamente que a razão arrendamento/receita fica
   constante para sempre. É defensável e não foi verificado contra alternativa.
4. **Bancos e seguradoras** — FCFF/WACC não se aplica; precisaria de lucro
   residual ou FCFE com capital regulatório.
5. **Comparar duas versões do mesmo valuation** — diff de premissas com ponte
   mostrando o que moveu o valor.
6. **O ROIC indexado é opcional e nasce desligado.** Marcar a caixa não muda o
   valor de hoje — só a resposta ao estresse de inflação —, mas ligar por padrão
   mudaria o resultado de todo estresse já salvo. O diagnóstico avisa quando a
   combinação que exagera (g ancorado + ROIC nominal fixo) está montada.
7. **Os cortes de leitura agora têm as duas leituras** — absoluta e percentil.
   `referencias.py` guarda a distribuição medida em 447 companhias, e a
   qualidade dos lucros cita onde o número cai. Falta estender aos demais
   cortes: `ALAVANCAGEM_ALTA = 3.5` fica entre o P50 (2,83) e o P75 (5,35) da
   base, ou seja, dispara em ~40% das companhias, e ninguém verificou se isso é
   o pretendido.
8. **A seção qualitativa reúne evidência, não responde.** `qualitativo.py` traz
   as cinco forças mais a pergunta do fosso, cada uma com o que foi medido, o
   que os dados não alcançam e o campo do analista em branco. Ameaça de
   substitutos aparece **sem nenhum número** — omiti-la faria parecer que a
   pergunta não existe.
9. **A projeção não modela adições de arrendamento** (ver acima), e o universo
   de pares precisa ser reconstruído quando sai DFP nova — não há detecção
   automática.

## Como trabalhar neste projeto

- **Teste contra dado real antes de dar por pronto.** Os piores bugs desta base
  vieram de código de importação que nunca tinha visto o arquivo de verdade.
- **Diga o que não verificou.** Vale mais que parecer confiante.
- **Comentários explicam o porquê, não o quê.** O código diz o que faz.
- Commits em português, descrevendo a decisão e não só a mudança.

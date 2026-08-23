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
pytest                        # 991 testes
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
  auditoria.py          de-para da leitura: identidades, contenção e origem
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

**E o plano financeiro também não é um só.** Medido nas 20 companhias que o usam
em 2024: `2.07` é "Patrimônio Líquido Consolidado" em 10 delas e **"Passivos
sobre Ativos Não Correntes a Venda" nas outras 7** — Itaú, BTG, Pine e as demais
que abrem o passivo por critério de mensuração IFRS 9, onde o patrimônio está em
`2.08`. O mapa de códigos punha **zero no patrimônio líquido do maior banco do
país**, e nenhuma identidade denunciava, porque zero é um número tão válido
quanto qualquer outro.

A regra agora é que **o código só vale com o aval do rótulo**: quando o rótulo
reconhece outra conta, ele ganha; quando não reconhece nada, a linha fica sem
conta — que é o erro visível, porque ela aparece na lista de não reconhecidas em
vez de preencher a conta errada calada. Para o aval não derrubar a cobertura, o
vocabulário ganhou os rótulos que o plano financeiro usa: "Receitas de/da
Intermediação Financeira" (17 companhias), "Despesas de/da Intermediação
Financeira", "Resultado Bruto de Intermediação Financeira" e "Lucro ou Prejuízo
Líquido Consolidado do Período" (10).

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

**As duas bases não coincidem no valuation, e a diferença tem nome.** Escrevi
que deveriam, já que IFRS 16 é apresentação. Errado: o balanço reconhece o
aluguel do **prazo contratado**, e quem aluga ponto renova. Medido num caso sem
crescimento, aluguel de 10/ano e passivo de 37,9 — o VP perpétuo do aluguel após
imposto ao WACC é **49,4**. Na Raia Drogasil: passivo de R$ 4,4 bi contra R$ 9,3
bi de aluguel perpétuo. A distância é quanto do valor vem de supor que o aluguel
acaba, e a aba IFRS 16 mostra as duas avaliações lado a lado.

`empresa_ex_ifrs16` converte as quatro pontas de uma vez (margem, depreciação,
adições projetadas, ponte). **O D/E alvo não é convertido** — quem o escolheu
escolheu com a dívida cheia em mente.

**O juro pago é padronizado para o operacional, abaixo do capital de giro.** O
IFRS deixa a companhia escolher onde classificar juro pago, e a base se divide:
**223 companhias no operacional, 121 no financiamento** (13 em ambos). Duas
empresas idênticas com classificações diferentes têm FCO diferente, e todo
indicador que divide por FCO passa a comparar apresentação em vez de negócio.
Pior: a WEG mudou a própria classificação entre 2022 e 2023 — a série dela não
era comparável nem consigo mesma.

`_padronizar_juros_no_fco` traz o juro de 6.03 para o operacional, **abaixo da
variação do capital de giro e junto dos impostos pagos**, que é onde o analista
espera vê-lo: o FCO passa a ser caixa depois de servir a dívida, para todo mundo.
A alternativa — somar de volta o juro de quem já o tem dentro — produziria um
FCO antes de juros que companhia nenhuma publica. A identidade da DFC sobrevive
por construção (o que sai do financiamento entra no operacional); verificado em
175 de 175 companhias mensuráveis, zero quebras. O ajuste vira conta visível
(`juros_pagos_no_financiamento`) e aviso — número que muda sozinho, sem
aparecer, é o pior tipo de correção.

Efeito medido: o impacto sobre o FCO das 121 companhias afetadas tem mediana de
**28%**, e passa de 30% em quase metade delas.

**Dentro do FCO também há coisa no lugar errado.** A seção `6.01.02` é
"variações nos ativos e passivos" — capital de giro. Muita companhia lança ali o
que não é movimento de saldo: medido em 2024, **127 companhias põem imposto de
renda pago dentro do giro (R$ 44,7 bi) e 69 põem juros pagos (R$ 23,4 bi)**. O
FCO não muda com isso, mas o *investimento em giro* que se lê da DFC vira outra
coisa — e ele é premissa de projeção. Na WEG o giro aparentava consumir
R$ 2.310 mi e consome **R$ 774 mi**.

A separação que importa é entre **pagamento e saldo**: "Impostos a recuperar" e
"Tributos a recolher" são giro de verdade e ficam; "Imposto de renda e
contribuição social pagos" desce para junto do juro. Em amostra de 200
companhias, 69 tiveram pagamentos retirados do giro.

**Outorga de concessão é capex e vai para o investimento** — mas o padrão é
estreito **de propósito**. Na DFC a palavra "outorga" aparece sobretudo em
"Opções outorgadas" e "Instrumentos patrimoniais outorgados", que são
remuneração em ações: com padrão largo são 38 companhias e a maioria é plano de
opções; com o padrão de `poder concedente|ônus da outorga|outorga fixa|...`, são
**9 companhias e R$ 3,4 bilhões**, todas concessão. A identidade da DFC se
preserva: o que sai do operacional entra no investimento.

**Três coisas que pareciam juro pago e não eram**, achadas ao examinar as 13
companhias que classificam juro nas duas seções:

- `exceto juros` — "Pagamento de empréstimos e arrendamentos (exceto juros)" é
  amortização de principal. Contava R$ 2,2 bi na Porto Seguro e R$ 2,7 bi na
  Ambev como juro.
- `principal e juros` — linha que mistura os dois não dá para separar, e
  contá-la inteira infla o Kd. São 18 linhas e **R$ 21,5 bi**, com R$ 12,4 bi só
  na Motiva.
- JCP com grafia variante — "Juros sobre capital **prório**" escapava. O padrão
  agora casa por "juros sobre … capital" e não pela grafia de "próprio", para
  não excluir "Juros de instrumento elegível a capital principal", que é juro.

As duas leituras do juro (a conta somada que alimenta o Kd e a reclassificação)
usam **o mesmo padrão de exclusão**, e há teste que quebra se alguém separá-los.

**Os cortes de conversão são os quartis medidos, não convenção.** Medidos de
novo depois das correções de sinal e da D&A da DFC: P25 = **15,0%**, mediana =
**51,4%**, P75 = **75,5%**. Os cortes são 0,15 e 0,76, e o de baixo acusa 25,2%
da base — um quarto, que é o que um corte no quartil deve acusar. O 90%/60% de
convenção não transfere: o FCO
brasileiro é líquido de imposto (34%) e de juro, e o EBITDA é antes dos dois —
90% era referência de um mercado de imposto e juro baixos. Histórico das
calibrações, porque cada uma corrigiu um erro: 0,60 acusava 47,3% da base antes
da correção da D&A; depois dela, ainda 30%; a padronização do juro derrubou a
mediana de 64% para 54%; e trazer a D&A da DFC subiu o EBITDA da cauda, o que
baixou a conversão de 53,9% para 51,4% e o P75 de 77,6% para 75,5%.

**Corte de leitura sem medição vira ruído — e a medição envelhece.** O sinal de
juro descolado usava 2 p.p. de diferença entre a despesa financeira da DRE e o
juro pago da DFC, e isso acusava **82,3% da base**: a linha `3.06.02` junta
variação cambial e monetária de todo o passivo, então a mediana brasileira
descola sem nada de anormal. Sinal que dispara em quatro de cada cinco não dirige
atenção, gasta.

Recalibrado para os quartis, o corte passou a acertar — **e depois errou para o
outro lado**, sozinho, quando a safra mudou:

| | 2020-2024 (n=368) | 2021-2025 (n=260) |
|---|---|---|
| Mediana | 8,2 p.p. | **5,9 p.p.** |
| P75 → `JURO_DESCOLADO` | 16,9 p.p. | **10,0 p.p.** |
| P90 → `JURO_MUITO_DESCOLADO` | 34,5 p.p. | **13,8 p.p.** |

Mantidos os cortes antigos, o primeiro acusaria **4,2%** da amostra nova e o
segundo, **zero**. Sinal que nunca dispara é tão inútil quanto o que dispara
sempre — é o mesmo defeito, do lado oposto. Duas causas plausíveis para o
encolhimento, nenhuma medida em separado: **2020 saiu da janela** (ano de
desvalorização forte do real) e as correções de leitura do juro pago entraram.

Acima de `KD_MAXIMO_PLAUSIVEL` o sinal se recusa a medir: com pouca dívida a
razão deixa de ser custo de dívida (WEG dá 45%). São 90 das 435 companhias
excluídas por isso, e 85 por não abrirem juro pago.

**Os testes deixaram de pinar os números.** Dois deles travavam `8,2 p.p.` e
`0,22` como literais, e viraram falha sozinhos quando a calibração mudou sem que
nada estivesse errado. Agora montam o caso **a partir das constantes** — o que
se trava é a propriedade (descolamento na mediana não acusa; entre P75 e P90 é
atenção), não o valor da safra.

**As três leituras do tempo, e o erro de misturá-las.** O app lia duas — o
exercício fechado e um ano móvel, o do último trimestre. Faltava a terceira e
faltava a **série**: quem acompanha uma empresa quer ver o trimestre isolado ao
longo do tempo e o ano móvel se movendo, não um ponto.

| Leitura | O que responde | O que custa |
|---|---|---|
| **Anual** | o exercício auditado, comparável entre empresas | fecha só uma vez por ano |
| **Trimestral isolado** | inflexão — margem que virou no 3T aparece aqui e some no acumulado | **carrega sazonalidade**: o par é 3T contra 3T |
| **Ano móvel rolante** | tendência, sem esperar o exercício fechar | não é exercício social |

O trimestre isolado é **leitura direta e não diferença entre acumulados**: medido
no ITR de 2025, **100% das companhias publicam a linha isolada** em toda data de
referência, ao lado do acumulado. A escolha entre as duas é por **duração** e não
por posição — no primeiro trimestre há uma linha só, e as duas coincidem.

O ano móvel rolante **não é a soma dos quatro trimestres isolados**: o quarto
trimestre do exercício anterior não existe no ITR — seria o exercício fechado
menos o acumulado de nove meses. Cada coluna reusa `importar_ltm` com o
`data_refer` daquele trimestre, em vez de reimplementar a fórmula: duas
implementações da mesma conta divergem no dia em que uma delas muda.

Contas de **balanço** não somam em nenhuma das três — são um saldo numa data.

Conferido na WEG: os três trimestres isolados de 2025 somam 30.558 contra os
30.557 do acumulado de nove meses, e o ano móvel sobe de 40.032 para 41.380 ao
longo do ano.

**O ITR tem uma pegadinha própria, e ela é de período.** Para `DT_REFER` de
30/09, a DRE traz **duas linhas da mesma conta**: o acumulado do exercício
(01/01–30/09, R$ 30,5 bi de receita na WEG) e o trimestre isolado
(01/07–30/09, R$ 10,3 bi). Somar as duas infla um terço; pegar a errada muda o
número pela metade. E no **primeiro** trimestre há uma linha só — então "pegar a
última" acerta em março e erra em setembro. A regra que funciona sempre: o
acumulado é a linha de **período mais longo**. Medidas as durações em 2025, só
existem três faixas (89–91, 180–183, 272–274 dias).

Duas diferenças em relação ao DFP: o `PENÚLTIMO` do ITR **é dado útil** (o mesmo
período do exercício anterior, a metade que falta do ano móvel), e no balanço ele
é o fim do exercício anterior, não o mesmo trimestre — comparar os dois casaria
saldo de setembro com saldo de dezembro.

**O ITR lia três demonstrações; o anual lê seis.** O zip trimestral traz as
mesmas seis, e ficavam de fora **sete contas canônicas que só existem na DVA** —
receita bruta, pessoal, impostos e taxas, aluguel, juros e o valor adicionado.
Medido no ITR de 2025: DVA com 116.854 linhas de 460 companhias, DRA com 32.114
e DMPL com 623.847. Na WEG o ano móvel agora traz receita bruta de R$ 45.211,7 mi
contra líquida de R$ 41.379,6 — os **9,3%** de impostos sobre vendas, contra os
9,0% do exercício fechado: a conta atravessa o ano móvel sem perder o sentido.

**O ITR nunca tinha passado pela varredura que a DFP passou, e três coisas
faltavam.** O leitor é o mesmo, mas o caminho do ano móvel nunca fora medido:

| | Antes | Depois |
|---|---|---|
| Ponte da DRE fecha (de 454) | 419 | **430** |
| Método direto detectado | 3 | **12** |
| Quebras no lucro líquido | 16 | **4** |

- **`grupo` não viajava na `LinhaCVM` do ITR**, então `detectar_metodo_da_dfc`
  não via o `DFC_MD` do trimestral e a DFC direta era lida com os códigos do
  indireto — o mesmo defeito que o anual já corrigira.
- **Faltava a guarda de linha duplicada**, que o anual ganhou.
- **A ponte preferia a abertura do imposto mesmo quando ela não fecha com o
  total.** No ano móvel a Magalu soma `3.08.01` e `3.08.02` de três fontes, e na
  de 2024 elas vêm **zeradas** com o imposto todo no pai: a soma perdia
  R$ 361,3 mi. A condição era "as duas filhas são zero", que não alcança a
  mistura de fontes; agora **vale o par que reconcilia**.

**E uma coisa que não se conserta, só se declara.** Das 24 que ainda não fecham,
**18 quebram no lucro dos controladores**: a Melhoramentos de São Paulo
reconcilia no exercício fechado e não no ano móvel, porque a divisão com
minoritários mudou entre os trimestres. Não dá para saber qual atribuição
descreve o período móvel — derivar por diferença esconderia que a soma não fecha,
e **a conta que não fecha é a informação**. O app avisa, **com o tamanho**:
"não fecha" sem tamanho não ajuda a decidir, e quem lê precisa saber se o
problema vale 0,3% ou 78% do resultado. Na Melhoramentos são R$ 46,0 mi, ou
**78% do lucro consolidado**; na Azul, **690%**.

Junto, **6 das 454 companhias trocam de método da DFC entre o anual e o
trimestre** — todas de direto para indireto, entre elas Santander, BRB e Axia
Energia Nordeste. Caixa gerado, variação de giro e D&A da DFC só existem no
indireto, então o ano móvel dessas contas não tem as duas metades para subtrair e
sai vazio. Também vira aviso, em vez de `NaN` calado.

`importar_ltm` monta o ano móvel: `exercício fechado + acumulado − mesmo período
do ano anterior`, para contas de resultado e de caixa; balanço é o **saldo do
trimestre**, não uma soma. O exercício-base é o anterior ao que o ITR acumula, e
não "o DFP mais recente" — usar o mais recente contava os mesmos meses duas
vezes e inflava a receita da WEG em R$ 2,8 bi. Verificado contra o arquivo: WEG
37.987 + 30.557 − 27.165 = 41.380; São Martinho (exercício fecha em março)
7.162 + 5.188 − 5.424 = 6.926.

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

**A demonstração publicada é uma árvore, e a tela tinha de mostrar isso.** O
nível do plano de contas já estava na tabela — era o recuo —, mas "Ativo Total" e
"JSCP a receber" saíam com o mesmo peso, e achar os totais exigia ler os 210
rótulos. Agora: cabeçalho grudado no topo, níveis 1 e 2 com fundo e negrito,
níveis 4 e 5 menores e mais fracos, negativo em vermelho, primeira coluna grudada
na esquerda.

Vai como **HTML** (`componentes.tabela_de_demonstracao`), e não como
`st.dataframe`: o Styler do pandas só atravessa cor para o canvas do Streamlit,
não peso nem tamanho de fonte — que são justamente o que separa um total de um
item folha. Efeito colateral bem-vindo: o número passa a existir no DOM, então
teste e navegador conseguem lê-lo; dentro do canvas nunca deu.

O CSS sai da paleta em `tema.tabela_css()`, e os fundos são **opacos**: a
primeira coluna é `position: sticky`, e com fundo translúcido os números
passariam por trás do rótulo durante a rolagem.

**E 37,1% das linhas publicadas são zero em todos os anos.** Medido em 40
companhias de 2019 a 2025 — 51,6% no balanço, 47,8% na DMPL, 8,8% no fluxo de
caixa. A companhia entrega o plano de contas inteiro e marca com zero o que não
tem. Na WEG o balanço cai de 188 para 96 linhas. Somem por padrão, com o número
do que sumiu escrito na legenda e uma alavanca para trazê-las de volta: linha
escondida sem aviso é o app decidindo pelo analista o que ele pode ver.

A regra olha a **subárvore**, e não a linha. A mesma medição achou 97 linhas
zeradas com filha viva, e **todas são o bloco `3.99`** — o pai é título sem valor
próprio e o número mora em `3.99.01.01`. Esconder pela leitura da própria linha
apagaria o lucro por ação junto com o caminho até ele.

**O lucro por ação estava mil vezes maior, e foi a tela nova que mostrou.** A CVM
declara `ESCALA_MOEDA = MIL` para o arquivo inteiro e escreve o lucro por ação em
reais na mesma linha — o rótulo diz, "Lucro por Ação - (Reais / Ação)". O R$ 1,44
da WEG virava R$ 1.440,26, e a conversão para R$ milhões depois o achatava em 0,0
na tela.

Medido no DRE consolidado de 2024: **889 linhas de 384 companhias**, mediana de
|valor| bruto em **1,31** e 99% abaixo de 1.000 — ordem de grandeza de reais por
ação, não de milhares deles. No ITR de 2025, 3.858 linhas de 388 companhias.
`cvm.e_conta_por_acao` tira o bloco `3.99` da escala do arquivo **e** da troca de
unidade, e a tabela marca a linha com "R$/ação" — um "1,4" sem marca, na coluna
de um balanço em R$ milhões, se lê errado. Nenhuma conta canônica sai de `3.99`,
então nada disso move valuation nenhum: o que muda é o número que estava errado
na tela.

**Textos em português acentuado, números no padrão brasileiro** (milhar com
ponto, decimal com vírgula). Use os formatadores existentes; não escreva
`f"{x:.1%}"` em texto de usuário.

## O balanço em T, e as fórmulas por escrito

**O balanço não é uma lista, é uma igualdade.** Empilhado numa tabela só, ele se
lê como 96 linhas, e a única coisa que ele afirma — que os dois lados fecham no
mesmo número — só aparece para quem rolar até o fim e lembrar do total lá de
cima. `separar_o_balanco` divide por raiz de código (`1` = ativo, `2` = passivo
e PL, que é a numeração da própria CVM e a mesma que separa os arquivos BPA e
BPP), e a tela põe os dois lado a lado com a conferência **antes** das tabelas:
se os lados não fecham, isso muda como se lê tudo o que vem abaixo.

Custo medido: sete anos em cada metade não cabem em 1.440px, e as duas tabelas
rolavam na horizontal — exatamente o que a leitura em T existe para evitar. A
variante `.compacta` aperta rótulo e recuo, e o container do app foi de 1.440
para 1.600px. A 2.150px (a tela do dono do projeto) cabe inteiro; abaixo de
1.600px cada lado rola dentro do próprio quadro, e a página não.

**As fórmulas passaram a ser publicadas, porque há vários jeitos de chegar no
ROIC.** O denominador pode ser capital de abertura, de fechamento ou médio; o
numerador pode usar alíquota nominal ou efetiva; o capital investido pode ou não
incluir o caixa. Mostrar "ROIC: 34,0%" sem dizer qual dos jeitos foi usado
obriga quem lê a confiar ou a refazer a conta — as duas coisas piores que
mostrar a fórmula.

`formulas.py` guarda, por indicador, a **conta** e a **convenção que ela
embute** — é a segunda que carrega a informação. As três escolhas do ROIC estão
escritas: alíquota efetiva (não os 34% nominais), capital investido pela ótica
do financiamento (dívida líquida + PL) e **capital médio** entre abertura e
fechamento. Fica no motor, e não na tela, porque descreve o que o motor calcula;
e `test_formulas.py` refaz a conta do ROIC à mão a partir do verbete e exige o
mesmo número, além de exigir verbete para todo indicador publicado. Texto que
descreve código envelhece calado se nada os amarrar.

## EBITDA → CGO → FCO: três perguntas que a conversão juntava numa só

A conversão FCO/EBITDA respondia ao mesmo tempo "o resultado virou caixa?", "o
giro prendeu caixa?" e "quanto saiu para imposto e juro?" — e só a primeira fala
da operação. Medido no consolidado de 2024, em 374 companhias com EBITDA
positivo:

Medido primeiro num ano só, e **depois na safra 2021-2025** — a mesma de
`referencias.BASE`, com a mesma metodologia (mediana por companhia, quantis
entre companhias). Os dois números importam, e o segundo é o que vale:

| | 2024, n=374 | **Safra 2021-2025, n=398** |
|---|---|---|
| CGO / EBITDA — P25 | 88,6% | **85,9%** |
| CGO / EBITDA — mediana | 105,9% | **102,9%** |
| CGO / EBITDA — P75 | 126,0% | **115,9%** |
| FCO / EBITDA — mediana | 59,2% | **53,0%** |
| Distância mediana | 42,4 p.p. | **48,9 p.p.** |

A mediana passa de 100% no CGO e isso não é anomalia: o caixa gerado devolve ao
lucro despesas que não foram caixa e o EBITDA não captura — provisão,
impairment. Na base, juro pago vale **25,8% do EBITDA na mediana** (P75 = 42,7%)
e imposto pago 6,3% — juntos, quase toda a distância.

**A medição da safra confirmou que `CONVERSAO_BOA` e `CONVERSAO_FRACA` não
precisavam mudar.** Ela reproduziu a distribuição do FCO que já estava em
`referencias.BASE` (P25 0,164 contra 0,166; P75 0,791 contra 0,785), o que é a
melhor validação possível da metodologia: separar CGO de FCO não mudou a
distribuição do FCO — mudou o que se **conclui** de um FCO baixo.

**Os cortes do CGO foram recalibrados na safra**, porque tinham saído de um ano
só — o defeito que este projeto já pagou duas vezes:

| | Antes (2024) | Depois (safra) | Acusa |
|---|---|---|---|
| `CGO_BOM` | 0,89 | **0,86** (P25) | 27% da base fica abaixo |
| `CGO_FRACO` | 0,60 | **0,54** (P10) | 10% |

Os quantis foram **conferidos contra uma segunda medição independente** — uma
amostra aleatória de 180 companhias da mesma safra (n=161 depois dos descartes),
que chega a P10 = 54,0%, P25 = 86,8% e mediana 104,2%: dentro de 1,5 ponto da
medição completa em todos os quantis, com a distância mediana até o FCO em 49,6%
contra 48,9%. Os cortes não são artefato de amostragem.

`CGO_BOM` é o **P25**, e não o P75 como `CONVERSAO_BOA`, e a diferença é
proposital: ele não pergunta "está entre as melhores?", pergunta "a operação
converte?". Estar acima do quarto inferior já responde que sim — e é por isso que
ele alcança 73% da base. O sinal cita o percentil junto do número, porque numa
distribuição cuja mediana passa de 100% um "90%" parece ótimo e é quartil
inferior.

**204 das 393 companhias com os dois números — 52% da base — têm CGO acima de
89% do EBITDA e FCO abaixo de 78%.** Nelas o resultado vira caixa e o consumo
está abaixo da operação; dizer "o EBITDA não vira caixa" ali manda o analista
procurar receita fictícia onde o que há é dívida cara. O sinal passa a olhar o
degrau de cima antes de culpar a operação, e nomeia o maior consumo **com o
tamanho** — "está no juro pago: 40% do EBITDA" dirige atenção, "está no giro, no
imposto ou no juro" não.

**Os três diagnósticos são distintos, e cada um manda o analista a um lugar
diferente:**

| O que se vê | O que é | Onde procurar |
|---|---|---|
| CGO alto, FCO baixo | o consumo está abaixo da operação | giro, imposto ou juro — a ponte diz qual, com o tamanho |
| CGO baixo | a operação não converte | resultado que não se realiza em caixa |
| os dois altos | o EBITDA vira caixa | — |

O ramo do CGO baixo entra **antes** dos que olham só o FCO: com CGO em 40% e FCO
em 25%, o ramo antigo ganhava e mandava procurar no capital de giro, que é o
lugar errado. `CGO_FRACO` existia sem disparar nunca — constante que não acusa
nada é o mesmo defeito de um corte não calibrado, do lado oposto.

A ponte entra no **relatório** e o achado do **diagnóstico** muda de título, de
detalhe e de ação conforme o CGO. O relatório omite a ponte quando ela não fecha:
uma tabela que não reconstrói o FCO publicado descreveria outra companhia.

`qualidade.ponte_do_caixa` monta a identidade que a DFC indireta publica:

```
FCO = CGO + variação do giro + outros − imposto pago − juro pago
```

Com o termo `6.01.03` ela fecha em 96,8% da base; **sem ele fechava em 59%** — a
mesma diferença que a auditoria já tinha achado, reconfirmada aqui. Na WEG de
2024: EBITDA 8.503,0 → CGO 9.562,3 (112,5%) → giro −774,4 → imposto −1.375,4 →
juro −160,3 → FCO 7.252,3 (85,3%), fechando exato.

## O revamp de UI/UX, e o que o benchmark mostrou

Comparado com stockanalysis.com, Koyfin, Fiscal.ai e com as práticas de
tipografia financeira (algarismo tabular, número à direita, cor reservada para
estado). Três achados, e os três estavam no app.

**A identidade visual vem dos tokens nativos, não de CSS por cima.** O Streamlit
1.61 expõe um sistema de design completo — `[theme.light]` e `[theme.dark]`
separados, fonte, escala de título, raio, borda, cores de gráfico —, e usá-lo
alcança todo componente, inclusive os que o CSS do app não pega. Sobra para o
CSS o que token nenhum resolve: medida de linha, os blocos próprios e densidade.

O achado mais caro: **a cor primária era o vermelho padrão do Streamlit**. Ele
pintava a aba ativa, o radio e o botão enquanto todo gráfico usava azul — a tela
dizia duas coisas diferentes sobre qual é "a cor daqui". Junto vieram Inter
(algarismo tabular, que é o que faz coluna de número alinhar), h1 de 2,75rem
para 2rem — tamanho de landing page numa tela de análise empurra o dado para
baixo da dobra — e `chartCategoricalColors` apontando para a paleta, para um
`st.line_chart` cru não discordar do Plotly do app.

`tests/test_tema.py` trava as duas cópias juntas: cor do `config.toml` e cor da
`Paleta` têm de bater, nos dois modos. **A paleta continua não se trocando por
gosto** — o teste é o que impede que ela se troque por descuido.

**O caminho é uma lista só, e virou navegável.** A ordem das doze telas estava
em três lugares — o menu, a lista do Início e a cabeça de quem usa — e quem
terminava uma tela voltava ao menu para lembrar qual era a próxima.
`navegacao.PASSOS` é a fonte única: dela saem as páginas do `st.navigation`, os
cartões do Início (cada um linkando para a própria etapa) e o rodapé "próximo
passo", que mora no `main` depois do `run` porque a mesma peça em doze cópias
diverge na primeira mudança. `textos.PASSOS` foi apagada.

Ícones do conjunto Material no lugar de emoji: emoji renderiza com a fonte do
sistema operacional, muda de desenho entre Windows e macOS, não herda a cor do
tema e desalinha da altura do texto.

**Número de demonstração se lê à direita.** A DRE gerencial era `st.dataframe`,
que desenha em canvas e alinha texto à esquerda: "13.347,4" e "9.394,2" não
compartilhavam posição de casa decimal, e comparar dois anos virava trabalho de
leitura. `componentes.tabela_financeira` é a mesma peça da árvore publicada —
número à direita em algarismo tabular, subtotal em negrito com fundo, negativo
em vermelho ao lado do sinal que já estava lá (reforço redundante, não a única
pista). Efeito colateral: o texto passa a existir no DOM, e a varredura do
navegador leu 4.360 caracteres na tela de Histórico contra 2.824 antes.

**Dois defeitos saíram do revamp, e nenhum era de layout:**

- **A unidade dentro do número truncava o número.** "930,0 R$ milhões" não cabe
  num cartão e o Streamlit corta em "930,0 R$ mil…" — pior que sem unidade,
  porque parece um número inteiro. A unidade foi para o rótulo, abreviada
  ("R$ mi"). É a convenção da própria demonstração: unidade no cabeçalho, uma
  vez. **E eu repeti o mesmo erro dentro do componente novo** — a primeira
  versão de `tabela_financeira` escrevia "R$ milhões" nas 154 células e cortava
  três anos de coluna. Há teste travando as duas pontas.
- **A barra lateral dizia "Nova empresa" com a WEG importada.** E `empresa.nome`
  alimenta o título da planilha e o cabeçalho do relatório: o app **exportava**
  um valuation da WEG assinado como "Nova empresa". `definir_demonstracoes`
  passa a adotar o nome da companhia, e só por cima do nome padrão — quem
  renomeou à mão escolheu aquele nome.

Os testes de tela deixaram de pinar o rótulo inteiro da métrica: o que eles
verificam é **que a métrica existe**, não como a unidade é escrita.

**O modo escuro foi ao navegador, e o contraste reprovou três pares.** O teste de
cor passava — as cores eram "as da paleta" —, mas **contraste é propriedade de
renderização**: só aparece medindo frente contra fundo no navegador, com o tema
que o usuário tem. É a mesma família de defeito que o markdown cru e a unidade
repetida, e o `AppTest` não alcança nenhum dos três.

| Par | Antes | Depois |
|---|---|---|
| Cabeçalho da tabela (branco sobre azul) | 4,42 | **5,39** claro / **8,10** escuro |
| Nível 5 da árvore, no claro | 3,70 | **7,73** |
| Negativo sobre a tinta do subtotal | 3,24 | **5,09** claro / **6,27** escuro |

A WCAG pede 4,5:1 para texto normal, e a tabela usa corpos de 0,74rem a 0,9rem —
vale o limite de texto normal, não o de texto grande. O cabeçalho e o negativo
passaram a usar **passos mais escuros da própria rampa sequencial**, escolha por
contraste medido e não cor nova; o nível 5 trocou `texto_suave` por
`texto_secundario`, porque a hierarquia sobrevive no tamanho e no peso. Três
testes em `test_tema.py` travam os limites — a função de contraste está lá, então
qualquer cor nova passa a ser conferível sem abrir o navegador.

**Não verificado:** a fonte é remota (Google Fonts), com fallback declarado para
`sans-serif`: sem rede o app cai na fonte do sistema, o que degrada bem mas muda
a métrica do texto.

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
- **Múltiplos de EV e de equity não se misturam** na ponte da dívida — e isso
  vale para o **múltiplo de saída**, que agora pode ser EV/EBITDA ou **P/L**
  (`PremissasPerpetuidade.base_do_multiplo`). O múltiplo carrega a moeda da
  conta em que incide: EV/EBITDA devolve valor de firma, P/L devolve valor de
  equity, porque o lucro líquido já é depois do juro.

  Somar um ao outro na mesma série não aparece como número absurdo — a ponte
  roda, o valor sai, e a dívida foi contada duas vezes ou nenhuma.
  `_terminal_na_moeda_do_fluxo` converte, e **avisa**. Medido no fixture, o caso
  que já existia e ninguém tinha visto — **FCFE com múltiplo de EV/EBITDA**, em
  que a dívida líquida nunca era subtraída — valia **50,7% do equity value**.

  Duas coisas que a implementação exige e que são fáceis de errar:

  1. **O P/L incide sobre o lucro líquido, não sobre o NOPAT.** O NOPAT é
     desalavancado por construção (imposto sobre o EBIT, como o FCFF pede). No
     fixture, NOPAT de 124,7 contra lucro de 72,4 — usar o NOPAT inflaria o
     terminal em **72%**, e ainda antes de somar a dívida de volta.
     `Projecao.lucro_liquido` é `NOPAT − juros × (1 − t)`; sem cronograma de
     dívida o saldo fica no de partida, que é a única hipótese que os números na
     mesa sustentam — e é declarada, porque a alternativa (fingir que não há
     dívida) é hipótese pior, calada.
  2. **A conversão usa a dívida líquida de hoje**, porque o modelo não projeta
     balanço. Vira aviso na tela de Valor e linha no relatório, em vez de sumir
     dentro do número.

  A identidade que trava tudo isso: o P/L que produz o mesmo valor de firma que
  um dado EV/EBITDA tem de chegar **exatamente** ao mesmo equity. Fecha com
  diferença zero, e sem a conversão a igualdade se perde em silêncio.
- **TSR decomposto pela identidade exata**, com o termo cruzado explícito:
  `g_lucro + g_múltiplo + (g_lucro × g_múltiplo) + dividendos`. A regra de bolso
  do mercado omite o termo cruzado.
- **Monte Carlo com semente fixa** — resultado que muda a cada execução é
  indefensável em revisão.

## Como testar

`pytest` roda tudo, em ~100 s, e **nenhum teste alcança a rede**. No CI
(`.github/workflows/testes.yml`) ele roda em todo push; **a varredura no
navegador não**, e a distinção é deliberada: ela sobe o app e baixa dados da CVM,
então serviço de terceiro fora do ar reprovaria código que está certo.

Ela roda **por agendamento** (segunda de manhã) e por disparo manual, guardando
as imagens das telas como artefato. As duas coisas juntas resolvem o dilema:
depender de alguém lembrar de disparar é o mesmo que não ter, e torná-la condição
de merge trava quem não devia ser travado.

As regras que valem:

- **Contas conferidas na mão** onde é possível (trava dos 30%, capitalização de
  P&D, valor presente do leasing, casos isolados do TSR).
- **Identidades que precisam fechar**: DuPont multiplica de volta ao ROE; as
  parcelas do TSR somam a TIR; a ponte EV fecha exatamente; empresa sem dívida
  comprada pelo valor do DCF devolve exatamente o Ke.
- **As fórmulas do Excel são validadas célula a célula** contra o motor Python
  (`tests/test_excel_formulas.py`, usando o pacote `formulas`). Planilha que
  calcula diferente do motor é pior que planilha nenhuma.
- **Nenhum teste alcança a rede.** O da comparação com o Focus alcançava, e a
  suíte passou de 100 s para **237 s** numa execução em que o Banco Central
  demorou — e falhou. Teste que depende de terceiro não está testando o app: ele
  serve o mesmo recorte real do Olinda que os testes do módulo já usam.
- **O app é verificado no navegador**, com Playwright, percorrendo o fluxo real:
  `python tools/navegador.py <porta>`, com o app rodando. Ele importa a WEG pela
  própria interface, percorre as doze telas e todas as abas de cada uma, e acusa
  exceção desenhada na página, markdown cru e rolagem horizontal.

  **Isso não é redundante com o `AppTest`.** O `AppTest` executa a tela em
  processo e pega exceção, widget que não monta e tipo que o Arrow recusa; o que
  ele não vê é o que só existe depois do render. Dois defeitos da aba de DRE
  saíram daí e nenhum teste os pegaria: a unidade repetida em **cada uma das 154
  células** (22 linhas × 7 anos), empurrando o número para fora da largura útil,
  e o rótulo cortado — "(+/−) Equivalência patrimonial" virava "(+/−)
  Equivalência" e "(−) Itens não recorrentes" virava "(−) Itens não reco",
  justamente as duas linhas que precisam ser distinguidas das vizinhas.

  Duas armadilhas do próprio script, custaram tempo: **navegue pelo menu, nunca
  por `goto`** — recarregar a página abre outra sessão do Streamlit e o histórico
  importado se perde, e toda tela aparece vazia; e **`st.dataframe` desenha em
  canvas**, então `inner_text()` não lê o conteúdo da tabela. Para conferir
  número em tabela, tire foto do elemento e olhe. **Rode o app e olhe antes de
  dar por pronto.**

**`R$` é cifrão, e o Streamlit lê cifrão como LaTeX.** A unidade brasileira é
`R$ milhões`, então **duas** aparições dela no mesmo markdown fecham um par
`$…$` e o trecho entre as duas vira fórmula. Visto no navegador: "Saldo de dívida
bruta ao fim de cada ano, em R _milhões. O saldo de partida é 400,0 R_ milhões"
— o meio em itálico de matemática, e os dois cifrões sumidos.

`componentes.em_texto()` escapa o `$`; `formatar()` não, porque também alimenta
tabela, e ali o `\$` apareceria literal. **A distinção é por destino:** número
que vai para texto passa por `em_texto`, número que vai para célula não. Onze
frases já estavam quebradas — em Múltiplos, Retorno e na aba de IFRS 16 — e
nenhum teste as pegaria, porque o markdown só é interpretado no navegador.

## A auditoria de leitura, e o que ela achou

`auditoria.py` varre a base inteira e pergunta, conta por conta, de onde o
número veio e se ele fecha com os que deveriam limitá-lo. Rodar é
`python -m valuation.auditoria` sobre o cache, ou `auditar_base(...)`. São três
famílias: **identidades** (ativo = passivo, seções da DFC, decomposição do FCO),
**contenção** (conta filha não excede a que a contém) e **origem** — o de-para
de qual código CVM alimentou cada conta canônica, em quantas companhias.

A terceira é a que pega o erro que nenhuma soma denuncia. Conta que vem de
`3.01` em 400 companhias e de outro código em duas não quebra identidade
nenhuma, e está errada.

**Resultado das cinco rodadas: 726 → 230 → 14 → 7 → 2 achados em 467
companhias.** Os 2 que sobraram são companhias que publicam **receita líquida
negativa**, e isso é leitura fiel do que elas publicaram. **Não resta nenhum
defeito de leitura conhecido na base.**

As 5 últimas a cair tinham todas a mesma causa, e a auditoria vinha apontando
para ela sem que ninguém tivesse ligado o fio: eram as únicas onde
`geração + giro` não explicava o FCO, e **todas publicam a DFC pelo método
direto** (ver abaixo).

O que a auditoria corrigiu, medido:

| Achado | Companhias | O que era |
|---|---|---|
| D&A com sinal negativo | 48 → 0 | D&A é magnitude; `EBITDA = EBIT + D&A` não admite negativo. 43 eram industriais |
| D&A não reconhecida | 106 | **R$ 121 bi** invisíveis — cauda de rótulos ("Depreciações, amortizações e desvalorizações") que listar sinônimo a sinônimo não termina |
| D&A partida em várias linhas | 127 | Mais R$ 4 bi: a disputa por confiança ficava com uma linha e descartava o resto |
| `6.01.03` nunca lido | 459 | A decomposição do FCO fechava em 47%; com o termo, **96,8%** |
| Arrendamento longo na conta de curto | 2 | Rótulos idênticos nos dois códigos; nenhuma identidade pegaria |

D&A virou **regra somada** sobre `6.01.01` — na seção de ajustes ao lucro, linha
que fala de depreciação **é** depreciação, sem precisar de verbo. Cobertura de
`depreciacao_amortizacao` foi de 366 para 434 companhias.

**E entre as duas fontes, a da DFC tem prioridade — não é preferência, é
estrutura.** A linha da DRE mora em `3.04.02.x`, **dentro de "Despesas Gerais e
Administrativas"**: ela captura só a depreciação que correu pelo SG&A, e a que
correu pelo CPV — que numa indústria ou concessionária é a maior parte — não está
ali. O ajuste da DFC (`6.01.01.x`) devolve ao lucro **toda** a D&A que o reduziu,
que é exatamente o que `EBITDA = EBIT + D&A` pede.

Medido nas 467 de 2024: 368 já vinham da DFC e 61 da DRE. Entre as **56 que
publicam as duas, a da DFC nunca é menor** — 34 coincidem exatamente e em 22 a da
DFC é maior:

| Companhia | D&A na DRE | D&A na DFC | Razão |
|---|---|---|---|
| Axia Energia Norte | R$ 5,1 mi | R$ 1.568,6 mi | **310x** |
| CPFL Energias Renováveis | R$ 11,0 mi | R$ 690,2 mi | 63x |
| CPFL Energia | R$ 142,0 mi | R$ 2.303,1 mi | 16x |

O efeito na margem EBITDA tem mediana zero — a maioria já vinha da DFC ou coincide
— e **P90 de +11,2 pontos**: CPFL Energias Renováveis vai de 48,8% para 67,5%, a
Eneva de 23,7% para 34,3%. Quando só a DRE tem o número (5 companhias), ela fica.

`_preferir_a_da_do_fluxo_de_caixa` faz a troca, registra em `derivadas` **nomeando
as duas linhas**, e **corrige o de-para**: origem registrada apontando para
`3.04.02.x` num número que veio de `6.01.01.x` é o tipo de erro que soma nenhuma
denuncia, e é o que a auditoria de origem existe para pegar.

**A DFC pelo método direto usa os mesmos códigos para outras contas.** É o mesmo
problema do plano financeiro, num lugar onde ninguém esperava. A CVM publica os
dois métodos em arquivos separados (`DFC_MI` e `DFC_MD`), o app lia os dois no
mesmo grupo `dfc`, e só a numeração do indireto estava mapeada:

| Código | Método indireto | Método direto |
|---|---|---|
| `6.01.01` | Caixa Gerado pelas Operações | **Recebimento de Consumidores** |
| `6.01.02` | Variações nos Ativos e Passivos | **Fornecedores — Materiais e Serviços** |
| `6.01.03` | Outros | **Fornecedores — Energia Elétrica** |

São **16 das 467 companhias de 2024**, e nelas o app punha recebimento de
clientes em `caixa_das_operacoes` e pagamento a fornecedores em
`variacao_capital_giro`. Nenhuma identidade denunciava, porque `6.01` continua
sendo o total do operacional nos dois métodos — mas **as 5 únicas companhias em
que a decomposição do FCO não fechava eram todas do método direto.**

`detectar_metodo_da_dfc` decide **pelo arquivo, não pelo rótulo**: das 16, só 9
abrem com "Recebimento de Consumidores", e uma regra por nome perderia as outras
7. O arquivo é a declaração da própria companhia. Detectado o direto,
`caixa_das_operacoes`, `variacao_capital_giro`, `outros_operacionais` e
`depreciacao_dfc` ficam **em branco** — elas descrevem a reconciliação do lucro
com o caixa, e a DFC direta não reconcilia nada, ela lista recebimentos e
pagamentos. Não há equivalente, e inventar um seria pior que a ausência: é a
mesma decisão tomada para bancos. O total do operacional, o investimento e o
financiamento continuam válidos, e a tela avisa.

**A margem sugerida parte da recorrente, e não da reportada.** Impairment, venda
de ativo e ganho tributário entram na DRE do SG&A para baixo e contaminam EBIT e
EBITDA por igual — a D&A não muda com eles, então a subtração é a mesma nos dois.
`sugerir_premissas` passou a usar `Margem EBITDA recorrente`, e o ajuste vai nos
**dois sentidos**: na Vale a mediana 2020-2024 vai de 38,7% reportada para
**51,9% recorrente** (o item foi impairment, uma perda), e na CESP vai de 72,5%
para **52,9%** (foi ganho). Na WEG, 19,9% → 21,4%; na Raia Drogasil, 11,1% →
10,9%. Diferença de 2 p.p. ou mais vira alerta, porque trocar a base da projeção
sem avisar é mudar o número em silêncio.

**O app abre todas as demonstrações, e o vocabulário é uma camada de nomes.**
Medido na WEG de 2024, o zip traz **574 linhas consolidadas**; DRE, BP e DFC
somam 276. As outras 298 estavam em **DMPL, DVA e DRA**, que não eram abertas —
mais da metade do que a companhia publica. Das que eram abertas, nada se perdia:
a árvore (`detalhe`) tinha as 276, e as ~70 contas canônicas são a camada que o
motor consome, não um filtro.

Agora as seis entram. A DMPL tem uma dimensão a mais (`COLUNA_DF`, o componente
do patrimônio) e entra **somada pelas colunas**: sem isso a árvore repetiria o
mesmo código cinco vezes. Quem precisa da abertura por componente vai ao arquivo,
e o vocabulário não promete tê-la.

**A DVA responde o que a DRE padronizada não abre**, em 450 das 467 companhias:

| Código | O que é | Por que importa |
|---|---|---|
| `7.01.01` | Receita **bruta** | Contra a líquida do `3.01`, a diferença são impostos sobre vendas e devoluções — 9,0% na WEG, 21,2% na Vivara, 5,5% na Raia |
| `7.08.01` | Pessoal | Folha e benefícios; não existe em linha nenhuma da DRE |
| `7.08.02` | Impostos, taxas e contribuições | Tudo que foi ao governo, não só IR e CSLL |
| `7.08.03.02` | Aluguéis | **Não é o aluguel total** — ver abaixo |

**Cuidado com `7.08.03.02`.** Escrevi no vocabulário que ela seria a medida
direta do aluguel, melhor que a aproximação pelo desembolso da DFC. Medi: vale
**0,19x** o desembolso na mediana de 81 companhias. Depois do IFRS 16 quase todo
aluguel saiu dessa linha e virou depreciação mais juros; sobra ali o
arrendamento de curto prazo e de baixo valor, que a norma dispensa. Usá-la na
leitura ex-IFRS 16 subestimaria o aluguel em cerca de 80%. Há teste travando.

**Demonstração sem receita operacional é de holding, e ali margem não quer dizer
nada.** Receita ~zero com lucro relevante significa resultado vindo de
equivalência patrimonial das investidas — margem, giro e capex sobre receita não
descrevem coisa alguma, e um FCFF projetado a partir de margem também não. O
corte é `|receita| ≤ 10% do |lucro|`, medido: pega **11 das 467 companhias
(2,4%)**, entre elas BB Seguridade (lucro de R$ 8,7 bi **sem nenhuma linha de
receita**) e Caixa Seguridade. A 20% já entrariam empresas em recuperação com
receita encolhida, que é outro caso e pede outro texto.

Receita **ausente** conta como zero ali, e não como "não dá para saber" — é o
caso mais forte do mesmo sinal, e tratá-la como dado faltante deixaria passar
justamente a companhia em que o aviso mais importa. A Itaúsa **não** dispara: o
consolidado dela tem R$ 8,2 bi de receita de verdade, das controladas
operacionais, e ela é coberta pelo sinal de item não recorrente.

**Lucro líquido acima do lucro bruto é contábil, e é um sinal.** Reversão de
impairment, venda de ativo, ganho tributário e ganho judicial entram na DRE **do
SG&A para baixo** e podem levar EBIT, LAIR e lucro líquido acima do lucro bruto.
Não é erro; é resultado que não se repete. A CVM padroniza os códigos, então a
separação não depende de adivinhar rótulo:

```
3.04.03  Perdas pela não recuperabilidade de ativos (impairment)
3.04.04  Outras receitas operacionais
3.04.05  Outras despesas operacionais

EBIT recorrente = EBIT − (3.04.03 + 3.04.04 + 3.04.05)
```

Com o **sinal publicado**, não com magnitude: reversão entra positiva, perda
entra negativa, e a subtração cuida dos dois casos. As três contas não existiam
no vocabulário — somam R$ 511 bi em 2024 e não eram lidas.

Medido: **165 de 172 companhias** têm item não recorrente diferente de zero, com
peso mediano de **17,4% do EBIT** e acima de 20% em quase metade. CESP tem
margem EBIT de 134% reportada e **21,5% recorrente**. E o ajuste vai nos dois
sentidos: na Vale o item foi impairment, então a recorrente (33,8%) é **maior**
que a reportada (26,9%).

A equivalência patrimonial (`3.04.06`) fica **fora da subtração**, de propósito:
para uma holding ela é o negócio, para uma indústria é resultado de coligada que
não gera caixa na controladora. Excluir por padrão acertaria numa e erraria na
outra, então ela aparece separada.

## A DRE gerencial, e os dois erros de sinal que ela revelou

A árvore da CVM serve para fiscalizar; para modelar é preciso outra forma, que
é a do dono do projeto e está em `Demonstracoes.dre_gerencial()`:

```
ROL − custos = LB
LB − SG&A + equivalência + outras receitas/despesas = EBIT
EBIT + D&A = EBITDA
EBITDA + ajustes = EBITDA ajustado
EBIT ± resultado financeiro = LAIR
LAIR − impostos = LL consolidado → controladores
```

São 22 linhas, com o resultado financeiro aberto em receitas, despesas e
derivativos/câmbio, e o imposto aberto em corrente e diferido. Aba **DRE** em
Histórico, em valores ou em percentual da receita.

**Duas coisas saem por subtração, e é decisão e não atalho.** O SG&A vem do
bloco `3.04` menos o que não é SG&A — as contas `3.04.01` e `3.04.02` só existem
em 297 e 454 das 467 companhias, e `3.04` existe em todas. Derivativos e câmbio
vêm do resíduo do resultado financeiro: não há código padronizado para eles, e
quando a companhia abre a linha ela cai num código livre dentro de `3.06`.

**`conferir_dre_gerencial()` anda junto e aparece na tela.** Ponte montada por
subtração com sinal trocado produz uma DRE que parece certa e não fecha; foi
exatamente o que aconteceu **três** vezes, e nenhuma outra verificação da
auditoria pegava:

- **`imposto_corrente` estava guardado como magnitude.** Na WEG de 2023 o
  diferido foi **crédito** de R$ 404,8 mi; somado como despesa, a ponte dava
  R$ 1.532,7 mi de imposto contra os R$ 723,2 mi publicados. `sinal_invertido`
  saiu da conta.
- **O bloco `3.04` também.** Numa holding ele é **positivo** — na Itaúsa,
  +R$ 14 bi, porque a equivalência supera as despesas —, e a magnitude jogava
  essa ordem de grandeza no SG&A. O bloco passa a vir de `EBIT − lucro bruto`,
  que é identidade e não depende de sinal publicado.
- **E `impostos` (`3.08`) também, com o alcance maior dos três.** Medido: **118
  das 467 companhias publicam `3.08` positivo**, R$ 71 bi de crédito lidos como
  despesa. Na DRE isso quase não aparecia, porque a ponte prefere `3.08.01` e
  `3.08.02`; onde doía era na **alíquota efetiva**, que é `impostos / LAIR`
  clipada em [0, 1] — crédito lido como despesa sobe a alíquota em vez de zerá-la,
  e com R$ 6,1 bi de crédito sobre LAIR de R$ 328,9 mi a razão passa de 1, é
  clipada em 100% e **zera o NOPAT**.

**O sinal do imposto não se decide por convenção de fonte, se mede.** `3.08` foi
mantido com magnitude porque planilhas de terminal publicam despesa positiva e a
CVM publica negativa. Mas a identidade que a própria companhia publica desempata:
**432 das 467 fecham `LAIR + 3.08 = 3.09` com o sinal publicado, e nenhuma fecha
com a convenção invertida.** `_corrigir_sinal_dos_impostos` passa a tirar o sinal
dali — da companhia, não da fonte —, mantendo a convenção de despesa positiva que
a derivação e a alíquota efetiva já usavam. Corrige **só o sinal**: quando as
magnitudes divergem a conta fica como foi lida, porque plug que absorve diferença
esconde erro de leitura, que é o que a ponte existe para achar. A correção entra
em `derivadas` e aparece na tela.

**Corrente e diferido não são duas metades do mesmo sinal.** Cada um pode ser
crédito por conta própria, e discordar é o caso comum. Medido no DFP consolidado
de 2024:

| | Companhias |
|---|---|
| Crédito no **diferido** (`3.08.02` > 0) | **221** de 467 |
| Crédito no corrente (`3.08.01` > 0) | 16 |
| Crédito nos dois | 8 |
| **Sinais opostos entre corrente e diferido** | **204** |
| `3.08.01 + 3.08.02 = 3.08` com o sinal publicado | **440 de 440** |
| … com magnitude | 0 |

Conferido conta a conta contra o arquivo bruto: **449 das 467 batem com sinal**
nas duas contas. As 18 que divergem são banco ou seguradora — Itaú, BTG, Pine, BB
Seguridade —, que publicam em outro plano e já eram detectadas e avisadas.

**O template mandava o usuário fazer errado.** A instrução dizia "custos,
despesas, **impostos** e capex podem ser positivos ou negativos: o app usa a
magnitude e padroniza o sinal sozinho" — verdade para custo, falsa para IR desde
que corrente e diferido passaram a guardar o sinal publicado. Quem seguisse
transformaria em despesa o crédito de 47% da base. O texto agora abre a exceção
com o número medido, e `_corrigir_sinal_do_ir_aberto` recupera o caso em que a
soma tem a magnitude do total e o sinal oposto. Quando corrente e diferido têm
sinais opostos e vieram como magnitude, **a informação se perdeu na origem e o app
não a inventa** — `_conferir` avisa que os dois não reconstroem o total.

Medido na base inteira depois das três correções, passo a passo:

| Passo da ponte | Fecha exato | Fecha até 1% | Não fecha |
|---|---|---|---|
| `ROL − custos = LB` | **467** | **467** | **0** |
| `LB − SG&A + equiv. + outros = EBIT` | **467** | **467** | **0** |
| `EBIT + D&A = EBITDA` | **467** | **467** | **0** |
| `EBITDA − não recorrentes = EBITDA aj.` | **467** | **467** | **0** |
| `EBIT ± resultado financeiro = LAIR` | 465 | 465 | 2 |
| `LAIR − IR = continuadas` | **467** | **467** | **0** |
| `continuadas + descontinuadas = LL` | 463 | 463 | 4 |
| `LL − não controladores = controladores` | 444 | 459 | 8 |
| **Cadeia inteira** | **440** | **455** | **12** |

Não há mais nenhum "sem dado": **identidade que fecha exatamente é aprovação, e
não ausência**, mesmo quando o subtotal é zero e não há denominador para o desvio
relativo. Eram 9 no lucro bruto — holdings e seguradoras sem linha de receita,
onde `0 − 0 = 0` é a resposta certa — e 2 nos controladores. Reportar `NaN` ali
dava impressão de cobertura faltando onde havia identidade trivialmente
verdadeira.

Duas leituras da mesma coisa: **440 fecham na aritmética exata** e 455 admitindo
1% (a diferença é arredondamento de demonstração publicada). Das 455, duas não
têm subtotal mensurável nenhum — então **453 são verificadas fechando**, contra
413 antes das correções de sinal.

**Os seis primeiros passos não falham em ninguém.** Tudo que sobra está nas duas
últimas linhas, e nenhuma é defeito de leitura:

- **8 publicam `3.11.01 + 3.11.02 ≠ 3.11`** — a árvore da própria companhia não
  fecha. A Azul publica R$ 9.190 mi de lucro aos controladores com consolidado de
  −R$ 9.151 mi; Cyrela, R$ 1.649 + (−R$ 272) contra R$ 1.921; Tupy e RCI zeram
  `3.11.02` com `3.11.01` diferente de `3.11`.
- **3 são banco ou seguradora** (Daycoval, BB Seguridade, IRB), onde `3.06` não é
  resultado financeiro. Já eram detectadas e avisadas antes desta ponte.
- **1 não está no cadastro** pelo nome, e não foi identificada.

**A tela acusa e não conserta**: consertar esconderia do analista que a companhia
publicou algo inconsistente.

**O passo dos controladores tinha 107 companhias sem denominador, e era bug.**
O valor apurado dava zero, e a conferência não tinha como dar desvio relativo.
Medida a causa: **102 das 467 publicam `3.11.01 = 0` e `3.11.02 = 0` com `3.11`
diferente de zero.** Não é que os controladores não tenham ganhado nada — é que a
companhia não tem minoritário e não repete o total na filha. Lido ao pé da letra,
o lucro dos controladores da CESP era **zero em vez dos R$ 1.077,9 mi** que ela
ganhou; na Axia Energia Nordeste, R$ 2.914,6 mi.

É o mesmo caso da D&A: **zero publicado que quer dizer "não abri", não "não
tem"** — e a correção é a mesma peça, uma `Derivacao` com `substitui_zero`.
Depois dela o passo vai de 337 para **442 fechando exato** e os 107 sem
denominador viram 2 (Rio Paranapanema e TIM S.A., que publicam `3.11` zerado — ali
zero é zero mesmo). A cadeia inteira não muda, porque conta que não fecha por
falta de denominador nunca era contada como falha; o que muda é que **102
companhias passam a ter lucro dos controladores correto** onde antes tinham zero.

**Duas verificações minhas estavam erradas, e a auditoria mostrou.** "Lucro
líquido não supera o bruto" acusou 29 companhias e as 29 estavam certas — Itaúsa
tem lucro líquido de R$ 14 bi sobre lucro bruto de R$ 2,4 bi porque vive de
equivalência patrimonial. E a decomposição do FCO acusava 126 companhias porque
eu não descontava o juro trazido do financiamento: em Panatlântica a diferença
era exatamente os R$ 59,75 mi reclassificados. Verificação que acusa o legítimo
não é verificação.

**O que sobrou, e por quê:** 2 companhias que publicam receita líquida negativa
— leitura fiel do que a companhia publicou, não defeito do app. Um caso do de-para que parece erro e não
é: `caixa_equivalentes` vindo de `1.01` em 20 companhias são **bancos**, onde
`1.01` é caixa mesmo e não ativo circulante.

## Estado atual

991 testes passando. Verificado de verdade: contas financeiras, identidades,
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

**E a verificação mais forte foi estendida da amostra para a base inteira.**
`test_cada_conta_bate_com_a_linha_publicada` volta ao CSV bruto, acha a linha
pelo código que o app registrou no de-para, aplica escala e sinal à mão e
compara — mas rodava só nas 6 companhias do fixture. Rodada nas 467:

| | |
|---|---|
| Pares conta × linha publicada conferidos | **29.096** |
| Batem exatamente (até 1e-9 relativo) | **29.095 — 99,997%** |
| Companhias sem nenhuma divergência | **466 de 467** |

A única que sobra é `fluxo_financiamento` de uma concessionária onde o app move
R$ 840,4 mi de outorga para o investimento — reclassificação deliberada, que o
app **anuncia em aviso na tela**, e que o verificador é que não tinha listado.

Fora da conferência ficam, de propósito: 400 contas derivadas (não vêm de linha
nenhuma), 6.243 reclassificadas por decisão documentada (juro no FCO, arrendamento
fora da subárvore de dívida, D&A da DFC, sinal do IR pela identidade) e 1.065 cujo
código não existe naquele arquivo.

**Não verificado, e é honesto dizer:**

1. A planilha nunca foi aberta no Excel de verdade (validada com o pacote
   `formulas`, que é independente mas não é o Excel).
2. Betas e prêmios de risco-país embarcados são **valores de referência de ordem
   de grandeza**, não a base oficial do Damodaran. O app rotula isso na tela.
3. Do ITR, só o **consolidado** é lido, e o ano móvel exige o exercício anterior
   fechado — companhia que abriu capital há menos de um ano não o tem.

   **Ler o consolidado não é limitação, é a escolha certa — e agora medida.**
   Das 467 companhias de 2024, **462 publicam os dois escopos**, e a individual é
   outra entidade: a receita individual é **0,40x a consolidada na mediana**,
   fica abaixo de 10% dela em **173 companhias** e é **zero** em boa parte. Na
   WEG a individual não tem receita nenhuma, e o lucro de R$ 6,0 bi vem todo de
   equivalência patrimonial — a entidade legal é uma holding, e a operação está
   nas controladas. Só 20% das companhias têm as duas dentro de 5% uma da outra.

   O app prefere o consolidado e só cai na individual quando ela falta, avisando.
   O aviso agora carrega o número, porque "não somam as controladas" subestima:
   elas podem ser **zero**.
4. Bancos e seguradoras (19 das 467) são detectados e avisados, mas o
   reconhecimento só por rótulo cobre bem menos contas, e o FCFF/WACC não se
   aplica a eles de qualquer forma.
5. **A cobertura das contas somadas estava sendo medida com o denominador
   errado.** Dividir "quantas têm a conta" pelo total da base conta como falha da
   regra a companhia que **não tem o conceito** — e em dividendos pagos isso é
   quase todo o problema. Medido em 2024, separando "ausente de verdade" (nenhuma
   linha da DFC menciona) de "escapou" (há linha e a regra não pegou):

   | Conta | Aparente | **Real** | O que explica a diferença |
   |---|---|---|---|
   | `capex` | 88% | **96%** | 35 companhias sem capex nenhum |
   | `juros_pagos` | 76% | **86%** | 55 não abrem juro pago |
   | `dividendos_pagos` | 61% | **96%** | **172 não pagaram dividendo** |

   E **a maior parte do que ainda escapa é a regra recusando certo**: venda de
   imobilizado não é capex, JCP não é juro, dividendo recebido não é dividendo
   pago. Dos 12 escapes de dividendos, 10 são "recebidos".

   O que sobra de fixável é pequeno e arriscado. Em juros, os rótulos sem verbo
   de pagamento ("Juros sobre empréstimos") são tentadores — mas **104 das 131
   linhas assim estão em `6.01.01`**, a seção de ajustes ao lucro, onde juro é
   **competência e não caixa**. Somá-las contaria despesa que nunca virou
   desembolso, e o total em jogo nas seções de caixa é de R$ 0,17 bi. Em capex os
   escapes reais são linhas **líquidas** ("Variação do Ativo Imobilizado",
   "(Aquisição) Alienação de imobilizado"), e valem R$ 0,00 bi.

   `auditoria.medir_cobertura_somada` repete a medição, e **uma armadilha ficou
   travada em teste**: linha publicada com valor **zero** não é escape. Muita
   companhia publica "Dividendos pagos" zerado no ano em que não pagou, e
   contá-la repõe o mesmo erro por outro caminho — sem o filtro, os escapes de
   dividendos passam de 12 para 90.

   **A mesma distinção está na tela de conferência**, por companhia:
   `conferir_contas_somadas` responde a pergunta que o analista faz olhando a
   empresa dele — o app achou capex, e se não achou, é porque a companhia não tem
   ou porque a regra não alcançou? Os dois pedem coisas diferentes: **ausente não
   pede nada**, e mandar procurar o que não existe gasta o tempo de quem lê;
   **escapou** pede mapeamento manual, e a tela lista as linhas da seção.

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

## Fontes de mercado, e a pegadinha do Focus

Três APIs públicas, em `mercado.py`, todas confirmadas contra o endpoint real:

- **Focus / Expectativas de Mercado** (`olinda.bcb.gov.br/olinda/servico/Expectativas/versao/v1/odata`):
  IPCA, Selic, PIB e Câmbio por ano de referência, com mediana, desvio e nº de
  respondentes. Nomes dos indicadores acentuados: `"PIB Total"`, `"Câmbio"`.
- **SGS do BCB** (`api.bcb.gov.br/dados/serie/bcdata.sgs.{serie}/dados`):
  série 432 Selic meta, 13522 IPCA 12 meses. Aceita `/ultimos/N`.
- **Tesouro Transparente** — preço e taxa diários de todos os títulos, incluindo
  a curva NTN-B. Latin-1, `;`, decimal com vírgula: **as mesmas convenções da
  CVM**, então o tratamento existente serve.

**O Focus publica o mesmo ano duas vezes, e isso passou despercebido.** O campo
`baseCalculo` vale 0 (respostas dos últimos 30 dias) ou 1 (últimos 5 dias úteis),
e sem filtrar cada ano volta duplicado — o código pegava um dos dois por ordem de
linha. Medido na coleta de 14/08/2026: IPCA de 2027 com mediana **4,2402** na
base 0 (148 casas) e **4,2060** na base 1 (69 casas). O padrão é a base 0, que é
a do relatório publicado e tem mais que o dobro de respondentes.

**`macro_do_focus()` traz o bloco inteiro** — IPCA, PIB real, Selic e câmbio —
usando o **ano mais distante** da janela, e não o próximo: a projeção curta
carrega o choque corrente, e premissa de perpetuidade quer regime. A diferença
não é pequena: 5,02% para 2026 contra **3,50%** para 2029.

Na tela de Premissas a comparação **nasce desligada e não troca nada sozinha** —
mesma regra do risco-país da NTN-B. Medido em 19/08/2026, o consenso é mais
otimista com inflação e menos com crescimento que a prática do dono do projeto:
IPCA de 3,5% contra 5%, PIB real de 2,0% contra 1,5%. Aplicar é um segundo
clique.

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
  Desde agora inclui o **ITR trimestral**, com o ano móvel plugando na mesma
  série anual que o motor já consome.
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

   **A perpetuidade foi verificada contra a alternativa, e a hipótese não é
   barata.** O `fluxo_final` do Gordon já vem líquido da adição; como a adição
   acompanha a receita e a receita cresce a `g`, isso supõe que a razão
   arrendamento/receita fica constante **para sempre** — a rede continua abrindo
   ponto no mesmo ritmo, eternamente. É internamente consistente, e é o padrão
   por isso. A leitura alternativa é a rede parar de crescer em área no fim do
   horizonte explícito:

   | Companhia | Adição / FCFF terminal | Equity se a expansão parasse |
   |---|---|---|
   | Lojas Renner | 8,1% | **+6,9%** |
   | Raia Drogasil | 13,1% | **+13,9%** |
   | Pague Menos | 21,5% | **+27,9%** |
   | Grupo SBF | 39,2% | **+96,7%** |

   O diagnóstico `arrendamento_cresce_para_sempre` mostra o número acima de 10%
   do FCFF terminal. **Não diz qual está certa** — diz quanto custa a que está
   montada, que é o que o analista precisa para escolher.
4. **Bancos e seguradoras têm caminho próprio.** FCFF/WACC não se aplica a
   eles: para uma indústria a dívida financia o ativo; para um banco ela **é o
   insumo**, e descontar um "fluxo para a firma" ao WACC soma o que ele ganha
   por tomar dinheiro e depois desconta por ele tomar dinheiro. `lucro_residual.py`
   implementa Ohlson — `equity = PL contábil + VP do lucro acima do Ke sobre esse
   patrimônio` — e a tela de Valor **desvia antes de qualquer número aparecer**.

   Duas identidades travadas em teste, porque uma implementação distraída quebra
   as duas sem avisar: **ROE igual ao Ke devolve exatamente o valor de livro**
   (se o custo do capital incidir sobre o patrimônio de fechamento em vez do de
   abertura, deixa de valer e nada mais denuncia), e **lucro residual dá o mesmo
   que desconto de dividendos** sob clean surplus.

   `roe_perpetuo` nasce igual ao Ke, o que **zera o valor terminal**. Não é
   omissão: é dizer que a vantagem não sobrevive para sempre, o padrão da
   literatura para instituição madura. E é aí que o modelo mostra a que veio —
   no DCF o terminal costuma valer 60% a 80% do total; aqui a âncora contábil
   carrega **83% a 105%**, e erro na perpetuidade custa menos.

   Medido com Ke de 13,35%: Itaú sai a **1,20x** o valor de livro, Bradesco a
   **0,97x** — com ROE de 12,6% abaixo do Ke, o lucro residual contribui
   **negativo**, e a tela diz isso. Não modela capital regulatório, e o alerta
   está onde o modelo é usado.

   A barra lateral também desvia: anunciar ali um Equity Value e um WACC que a
   tela de Valor acabou de recusar seria contradizer, no canto do olho, o que a
   tela principal explica. **E o relatório também** — ele é o que sobra depois
   que a tela fecha, e descrever ali um Enterprise Value, um WACC e uma ponte que
   ninguém calculou contradiria o número que o usuário viu.

   Duas seções do relatório industrial saíram do caminho do banco porque
   **descreviam outra companhia**, e a substituta diz o que ficou de fora em vez
   de simplesmente sumir com ele:

   - a **evidência qualitativa** citava percentis do universo de comparáveis, que
     **exclui bancos e seguradoras de propósito** — comparar contra 445
     companhias a que a instituição não pertence produz um percentil que parece
     informação e não é;
   - o **diagnóstico automático** verifica a coerência do DCF, e o DCF não foi
     usado. Ele chegava a reclamar de "margem EBITDA projetada abaixo do pior ano
     histórico" num modelo que não projeta margem nenhuma.

   O histórico também trocou de indicadores: patrimônio, lucro, ROE e payout no
   lugar de margem EBITDA e capex sobre receita. A seção industrial mostrava
   **margem EBITDA de −8,3% para o Bradesco**, número que não descreve nada.

   **E o beta de um banco não se realavanca.** Hamada supõe que a dívida é
   escolha de financiamento que acrescenta risco ao acionista; num banco o
   depósito é a **matéria-prima**, e o risco dele já está dentro do beta
   observado do equity. Medido nas 18 instituições com balanço legível em 2024:

   | | |
   |---|---|
   | Passivo de terceiros / PL, mediana | **11,2x** |
   | Beta de 0,95 realavancado por esse D/E | **8,0** |
   | Ke que sairia daí | **41% em dólar** |

   Banco nenhum tem isso — os betas observados ficam perto de 1.
   `PremissasCustoCapital.instituicao_financeira` desliga o realavancamento, o
   setor "Bancos e serviços financeiros" já vem marcado, e a tela de Valor
   **recalcula o Ke com a marca ligada e avisa quando isso muda o número** —
   porque o usuário pode ter escolhido um setor industrial antes de importar um
   banco. Medido no Bradesco: Ke de 13,35% realavancado contra **12,40%** sem, e
   o P/VP vai de 0,97x para 1,01x.

   **E aí o beta passa a carregar o Ke sozinho, num modelo em que o Ke decide o
   sinal do resultado.** O beta embarcado é valor de referência, não medido
   contra série de preços — então a tela mostra o **beta de indiferença**: aquele
   em que o Ke iguala o ROE e o lucro residual zera. Não conserta a origem do
   beta, **expõe o que ela decide** — é a ideia do DCF reverso aplicada ao
   parâmetro que aqui manda em tudo. Medido:

   | Instituição | ROE | Beta de indiferença | Conclusão |
   |---|---|---|---|
   | Daycoval | 22,3% | 2,95 | robusta |
   | BTG | 18,6% | 2,15 | robusta |
   | Itaú | 18,0% | 2,01 | robusta |
   | Banco do Brasil | 17,8% | 1,97 | robusta |
   | **Santander** | 12,3% | **0,78** | **frágil** |
   | **Bradesco** | 12,1% | **0,72** | **frágil** |
   | BMG | 5,4% | −0,74 | robusta (destrói) |
   | IRB | −9,7% | −4,03 | robusta (destrói) |

   A leitura que importa é a das duas pontas. Itaú e BTG precisariam de beta
   **acima de 2** para deixar de criar valor, e BMG e IRB precisariam de beta
   **negativo** para deixar de destruir — nos dois casos a conclusão sobrevive à
   incerteza do parâmetro. Já Bradesco e Santander viram com beta de 0,72-0,78,
   que é **plausível para banco grande**: ali o app não deve afirmar destruição
   de valor, e a tela diz isso em vez de mostrar só o P/VP.

   Um erro que a tela cometeu e que valeu a lição: "beta em uso" mostrava o campo
   bruto da premissa (1,00) e não o que entrou no Ke (0,77, desalavancado pelo
   D/E dos comparáveis). Como o veredito sai da comparação entre os dois betas,
   ele saía **contradizendo o P/VP mostrado logo acima**. Há teste travando que
   as duas leituras concordam.
5. **Comparar duas versões do mesmo valuation** — diff de premissas com ponte
   mostrando o que moveu o valor.
6. **O ROIC indexado é opcional e nasce desligado.** Marcar a caixa não muda o
   valor de hoje — só a resposta ao estresse de inflação —, mas ligar por padrão
   mudaria o resultado de todo estresse já salvo. O diagnóstico avisa quando a
   combinação que exagera (g ancorado + ROIC nominal fixo) está montada.
7. **Os cortes de leitura agora têm as duas leituras** — absoluta e percentil.
   `referencias.py` guarda a distribuição medida em 447 companhias, e a
   qualidade dos lucros cita onde o número cai. **Os cortes que faltavam foram
   medidos**, e um deles estava errado por confusão de grandeza:

   | Corte | Valor | P75 da base | Dispara em |
   |---|---|---|---|
   | `DIVIDA_EBITDA_ALTA` | 3,5 | 3,40 | 23,4% |
   | `DIVIDA_PL_ALTA` | 2,0 | 1,79 | 21,0% |
   | `LEASING_RELEVANTE` | 0,20 | 0,206 | 26,3% |
   | `NAO_RECORRENTE_RELEVANTE` | 0,20 | 0,266 | 31,9% |

   **`ALAVANCAGEM_ALTA` media duas grandezas diferentes com o mesmo 3,5**: D/E
   alvo (dívida sobre patrimônio) e dívida líquida/EBITDA (dívida sobre geração
   de caixa). Que os dois números calhassem de ser iguais era coincidência, não
   calibração. Em D/E o 3,5 disparava em **8,6%** — não era um corte alto, era um
   corte que quase nunca disparava, mascarado por parecer calibrado. Virou
   `DIVIDA_PL_ALTA = 2.0`, que é o quartil.

   `NAO_RECORRENTE_RELEVANTE` fica em 0,20 e não no quartil de propósito — "um
   quinto do EBIT" é limiar com significado próprio e a distância para o P75 é
   pequena. O que não podia ficar era o comentário citando "47%", que media outra
   coisa: só as companhias que tinham item, e num ano só.
8. **A seção qualitativa reúne evidência, não responde.** `qualitativo.py` traz
   as cinco forças mais a pergunta do fosso, cada uma com o que foi medido, o
   que os dados não alcançam e o campo do analista em branco. Ameaça de
   substitutos aparece **sem nenhum número** — omiti-la faria parecer que a
   pergunta não existe.
9. **O universo de pares e os percentis avisam quando ficam para trás.** Eles são
   construídos uma vez e lidos muitas, e não se atualizam sozinhos: quando sai
   DFP nova o app passava a comparar contra uma base antiga **com a mesma
   aparência de atual**, que é o pior tipo de número desatualizado — o que não se
   anuncia. `pares.safra_do_universo` e `referencias.safra` comparam a safra com
   os exercícios já baixados no cache, e a aba de qualidade mostra a idade.

   A verificação olha o **cache e não o portal**: ela roda a cada abertura de
   tela, e por um alerta de safra não se põe a rede no caminho crítico. E **zip
   vazio não conta** — em janeiro o arquivo do exercício já existe sem companhia
   nenhuma, e contá-lo anunciaria atraso por um exercício que ainda não saiu. É
   a mesma armadilha de `_itr_vazio`.

   O aviso pegou um caso real na primeira execução — a própria medição estava um
   exercício atrás —, e a safra foi refeita para **2021-2025, com 421
   companhias**. O que se moveu:

   | | 2020-2024 | 2021-2025 |
   |---|---|---|
   | Crescimento da receita, mediana | 15,1% | **9,3%** |
   | ROIC, P75 | 18,0% | **16,5%** |
   | Conversão de caixa, mediana | 51,4% | 53,0% |
   | Margem EBITDA, mediana | 19,9% | 20,8% |

   A queda do crescimento é o exercício de 2025 entrando e o de 2020 saindo, e
   ela move o teto que o diagnóstico usa. Os cortes de conversão passaram a
   0,17 e 0,78 (os quartis novos); `DIVIDA_EBITDA_ALTA = 3.5` segue sendo o P75
   (3,55) e dispara em 25,4%.

   **Uma linha ficou de fora e está declarada:** `DESCOLAMENTO_DO_JURO` ainda é
   da safra 2020-2024. Safra parcial que se apresenta como inteira é exatamente
   o problema que `safra()` existe para evitar.

## Como trabalhar neste projeto

- **Teste contra dado real antes de dar por pronto.** Os piores bugs desta base
  vieram de código de importação que nunca tinha visto o arquivo de verdade.
- **Diga o que não verificou.** Vale mais que parecer confiante.
- **Comentários explicam o porquê, não o quê.** O código diz o que faz.
- Commits em português, descrevendo a decisão e não só a mudança.

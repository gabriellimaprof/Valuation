"""Abre a planilha exportada no **Excel de verdade** e confere contra o motor.

`tests/test_excel_formulas.py` já valida as fórmulas célula a célula, mas com o
pacote `formulas`, que é um interpretador independente — não é o Excel. A
distinção importava: a planilha é o que sai da mão do usuário, e uma fórmula que
o `formulas` avalia de um jeito e o Excel de outro só apareceria com o arquivo já
entregue. Por anos essa foi a linha em "não verificado" do CLAUDE.md.

Este script fecha a lacuna, e é o análogo do `navegador.py`: roda fora do
`pytest` porque **depende de Excel instalado** e do Windows. Pôr isso no CI
reprovaria código correto na primeira máquina sem Office.

Uso::

    python tools/conferir_no_excel.py

Sai com código 1 se alguma célula divergir do motor.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
for caminho in (str(RAIZ), str(RAIZ / "src")):
    if caminho not in sys.path:
        sys.path.insert(0, caminho)

from valuation import (  # noqa: E402
    Empresa,
    PonteValor,
    PremissasCustoCapital,
    PremissasMacro,
    PremissasOperacionais,
    PremissasPerpetuidade,
    avaliar,
    exportar_excel,
)

# Tolerância de ponto flutuante, e não de modelagem: o Excel e o Python fazem as
# mesmas contas em ordens ligeiramente diferentes. As diferenças observadas
# ficam na casa de 1e-15; 1e-9 já é folga de seis ordens de grandeza.
TOLERANCIA = 1e-9

# O PowerShell é quem fala COM. Fica aqui, e não num .ps1 solto, para o script
# ser um arquivo só — o número que ele confere vem do Python logo acima, e
# separar os dois convida a que um mude sem o outro.
ROTEIRO = r"""
param([string]$Arquivo, [string]$Alvos, [string]$Destino)
# **O nome nao pode ser `$alvos`.** O `param([string]$Alvos)` acima fixa o tipo
# da variavel, e no PowerShell maiuscula nao distingue: atribuir o array a
# `$alvos` o converteria de volta para string, e `$a.aba` devolvia todos os
# valores concatenados ("Custo de Capital DCF") em vez de um por vez.
$lista = ConvertFrom-Json (Get-Content $Alvos -Raw)
if ($lista -isnot [System.Array]) { $lista = ,$lista }
$excel = New-Object -ComObject Excel.Application
$excel.Visible = $false
$excel.DisplayAlerts = $false
$wb = $excel.Workbooks.Open($Arquivo)
# O openpyxl grava a formula sem valor em cache; sem o rebuild o Excel devolve
# vazio e a conferencia passaria comparando nada com nada.
$excel.CalculateFullRebuild()
# As abas sao indexadas por nome uma vez so. `Worksheets.Item($nome)` devolvia
# DISP_E_BADINDEX com o nome vindo do JSON -- comparar `$_.Name` resolve e nao
# depende de como o COM interpreta a string que recebe.
$abas = @{}
foreach ($ws in $wb.Worksheets) { $abas[[string]$ws.Name] = $ws }

$lidos = @{}
foreach ($a in $lista) {
    $ws = $abas[[string]$a.aba]
    if (-not $ws) {
        $lidos[$a.chave] = $null
        [Console]::Error.WriteLine("aba '$($a.aba)' nao existe; ha: " + ($abas.Keys -join ' | '))
        continue
    }
    $linha = $null
    for ($i = 1; $i -le 400; $i++) {
        if ($ws.Cells.Item($i, 1).Value2 -eq $a.rotulo) { $linha = $i; break }
    }
    if ($linha) { $lidos[$a.chave] = $ws.Cells.Item($linha, 2).Value2 }
    else {
        $lidos[$a.chave] = $null
        [Console]::Error.WriteLine("nao achei '$($a.rotulo)' em '$($a.aba)'")
    }
}
$wb.Close($false)
$excel.Quit()
[void][Runtime.InteropServices.Marshal]::ReleaseComObject($excel)
$lidos | ConvertTo-Json | Set-Content -Path $Destino -Encoding utf8
"""


def _empresa_de_conferencia() -> Empresa:
    """Uma empresa com dívida, caixa, minoritários e contingências.

    Todas as pontas da ponte preenchidas de propósito: uma linha zerada esconde
    um erro de sinal, que é o defeito mais provável numa fórmula de planilha.
    """
    return Empresa(
        nome="Teste S.A.",
        macro=PremissasMacro(inflacao_brl=0.04, inflacao_usd=0.023, aliquota_ir=0.34),
        custo_capital=PremissasCustoCapital(
            rf_usd=0.045,
            erp_maduro=0.045,
            risco_pais=0.025,
            beta_alavancado_setor=1.05,
            divida_pl_setor=0.45,
            divida_pl_alvo=0.50,
            spread_credito=0.025,
        ),
        operacionais=PremissasOperacionais(
            receita_base=1000.0,
            crescimento_receita=[0.10, 0.08, 0.06],
            margem_ebitda=[0.20] * 3,
            depreciacao_pct_receita=[0.05] * 3,
            capex_pct_receita=[0.06, 0.055, 0.05],
            capital_giro_pct_receita=[0.10] * 3,
        ),
        perpetuidade=PremissasPerpetuidade(
            metodo="gordon", crescimento_perpetuo=0.045, roic_perpetuidade=0.15
        ),
        ponte=PonteValor(
            divida_bruta=900.0,
            caixa=250.0,
            minoritarios=30.0,
            contingencias=60.0,
            acoes_em_circulacao=150.0,
        ),
        data_base="2025-12-31",
    )


def conferir() -> int:
    empresa = _empresa_de_conferencia()
    resultado = avaliar(empresa)
    cc, dcf = resultado.custo_capital, resultado.dcf

    esperado = {
        "ke": ("Custo de Capital", "Ke em BRL nominal", cc.ke_brl),
        "kd": ("Custo de Capital", "Kd bruto em BRL nominal", cc.kd_bruto_brl),
        "kd_liquido": (
            "Custo de Capital",
            "Kd apos IR",
            cc.kd_bruto_brl * (1 - empresa.macro.aliquota_ir),
        ),
        "wacc": ("Custo de Capital", "WACC (BRL nominal)", cc.wacc_brl),
        "vp_explicito": (
            "DCF",
            "VP dos fluxos do periodo explicito",
            dcf.valor_presente_explicito,
        ),
        "vt": ("DCF", "Valor terminal (fim do ano n)", dcf.valor_terminal),
        "vp_vt": ("DCF", "VP do valor terminal", dcf.valor_presente_terminal),
        "ev": ("DCF", "Enterprise Value", dcf.enterprise_value),
        "equity": ("DCF", "Equity Value", dcf.equity_value),
        "por_acao": ("DCF", "Valor por acao", dcf.valor_por_acao),
    }

    with tempfile.TemporaryDirectory(prefix="excel_") as pasta:
        pasta = Path(pasta)
        planilha = pasta / "modelo.xlsx"
        exportar_excel(resultado, planilha)

        alvos = pasta / "alvos.json"
        alvos.write_text(
            json.dumps(
                [
                    {"chave": chave, "aba": aba, "rotulo": rotulo}
                    for chave, (aba, rotulo, _) in esperado.items()
                ]
            ),
            encoding="utf-8",
        )
        script = pasta / "abrir.ps1"
        script.write_text(ROTEIRO, encoding="utf-8")
        saida = pasta / "lidos.json"

        print(f"abrindo {planilha.name} no Excel…")
        processo = subprocess.run(
            [
                "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                "-File", str(script),
                "-Arquivo", str(planilha),
                "-Alvos", str(alvos),
                "-Destino", str(saida),
            ],
            capture_output=True,
            text=True,
        )
        if processo.stderr.strip():
            print(processo.stderr.strip()[:1200])
        if processo.returncode != 0 or not saida.exists():
            print("nao consegui usar o Excel:")
            print(processo.stdout[-800:])
            print(processo.stderr[-800:])
            return 1

        # `utf-8-sig`: o `Set-Content -Encoding utf8` do PowerShell 5.1 grava BOM,
        # e o `json` do Python recusa o arquivo por causa dele.
        lidos = json.loads(saida.read_text(encoding="utf-8-sig"))

    print(f"\n{'conta':38s} {'Excel':>16s} {'motor':>16s}  desvio")
    problemas = []
    for chave, (aba, rotulo, do_motor) in esperado.items():
        no_excel = lidos.get(chave)
        if no_excel is None:
            print(f"{rotulo[:38]:38s} {'NAO ACHOU':>16s} {do_motor:16,.6f}")
            problemas.append(f"{aba}!{rotulo}: celula nao encontrada")
            continue
        escala = abs(do_motor) if do_motor else 1.0
        desvio = abs(no_excel - do_motor) / escala
        marca = "" if desvio <= TOLERANCIA else "  <-- DIVERGE"
        print(f"{rotulo[:38]:38s} {no_excel:16,.6f} {do_motor:16,.6f}  {desvio:.1e}{marca}")
        if desvio > TOLERANCIA:
            problemas.append(f"{aba}!{rotulo}: Excel {no_excel} contra motor {do_motor}")

    if problemas:
        print(f"\nDIVERGENCIAS ({len(problemas)}):")
        for p in problemas:
            print(f"   {p}")
        return 1

    print(
        f"\nas {len(esperado)} contas conferem com o motor dentro de {TOLERANCIA:.0e}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(conferir())

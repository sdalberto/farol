# ============================================================================
#  Instalador do Farol para Windows (PowerShell)
#  Uso: clique duas vezes em install.bat  (ou: powershell -ExecutionPolicy Bypass -File install.ps1)
#  A SENHA de acesso é definida durante a instalação.
# ============================================================================
$ErrorActionPreference = "Stop"
$Src = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Src

function Ok($m)   { Write-Host "OK  $m" -ForegroundColor Green }
function Info($m) { Write-Host ">>  $m" -ForegroundColor Cyan }

# ---- 1. Encontrar Python 3.9+ ----------------------------------------------
$py = $null
foreach ($cand in @("py -3", "python", "python3")) {
    try {
        $v = & cmd /c "$cand -c ""import sys;print(sys.version_info>=(3,9))"" 2>nul"
        if ($v -eq "True") { $py = $cand; break }
    } catch {}
}
if (-not $py) {
    Write-Host "Python 3.9+ nao encontrado." -ForegroundColor Red
    Write-Host "Instale em https://www.python.org/downloads/ (marque 'Add python.exe to PATH') ou: winget install Python.Python.3.12"
    Read-Host "Enter para sair"; exit 1
}
Ok "Python encontrado ($py)"

# ---- 2. Ambiente virtual + dependências ------------------------------------
Info "Criando ambiente virtual..."
& cmd /c "$py -m venv .venv"
& .\.venv\Scripts\python.exe -m pip install --upgrade pip -q
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt -q
Ok "Dependencias instaladas"

# ---- 3. Configuração (idioma, modo, pastas, SENHA) --------------------------
Info "Configuracao inicial:"
& .\.venv\Scripts\python.exe -m farol setup

# ---- 4. Atalhos -------------------------------------------------------------
$bat = Join-Path $Src "Farol.bat"
@"
@echo off
rem Inicia o Farol e abre o navegador
cd /d "$Src"
".venv\Scripts\python.exe" -m farol run
"@ | Set-Content -Encoding ASCII $bat

$desktop = [Environment]::GetFolderPath("Desktop")
$wsh = New-Object -ComObject WScript.Shell
$lnk = $wsh.CreateShortcut((Join-Path $desktop "Farol.lnk"))
$lnk.TargetPath = $bat
$lnk.WorkingDirectory = $Src
$lnk.WindowStyle = 7   # minimizado
$lnk.Description = "Farol - buscador offline"
$lnk.Save()
Ok "Atalho 'Farol' criado na Area de Trabalho"

Write-Host ""
Ok "Instalacao concluida! Abra pelo atalho 'Farol' ou rode Farol.bat"
Read-Host "Enter para sair"

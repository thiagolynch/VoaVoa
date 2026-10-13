# VOAVOA - acorda, sobe o Docker, deixa o bot processar mensagens de
# WhatsApp pendentes e (so na janela da manha) roda motor_busca.py.
#
# Chamado pelas tarefas agendadas "VOAVOA Acordar ..." (ver README/DEPLOY).
# -RodarMotorBusca so deve ser usado numa das janelas do dia, pra nao
# triplicar o consumo de cota da SerpApi.

param(
    [switch]$RodarMotorBusca
)

$ErrorActionPreference = "Continue"
$projeto = "C:\Users\thiag\Downloads\VOAVOA"
$logFile = Join-Path $projeto "acordar.log"
Set-Location $projeto

function Log($mensagem) {
    $linha = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') | $mensagem"
    Add-Content -Path $logFile -Value $linha
    Write-Output $linha
}

Log "===== Acordou (RodarMotorBusca=$RodarMotorBusca) ====="

$dockerPronto = $false
docker ps *> $null
if ($LASTEXITCODE -eq 0) {
    $dockerPronto = $true
} else {
    Log "Docker Desktop nao esta rodando - iniciando..."
    Start-Process "shell:AppsFolder\Docker.DockerForWindows.Settings"
    for ($i = 0; $i -lt 24; $i++) {
        Start-Sleep -Seconds 5
        docker ps *> $null
        if ($LASTEXITCODE -eq 0) { $dockerPronto = $true; break }
    }
}

if ($dockerPronto) {
    Log "Docker pronto. Subindo containers (docker compose up -d)..."
    docker compose up -d *>> $logFile
    Log "Aguardando a Evolution API reconectar e o bot processar mensagens pendentes..."
    Start-Sleep -Seconds 120
} else {
    Log "Docker NAO ficou pronto a tempo - pulando a etapa do WhatsApp nesta janela."
}

if ($RodarMotorBusca) {
    Log "Rodando motor_busca.py..."
    & "$projeto\venv\Scripts\python.exe" "$projeto\motor_busca.py" *>> $logFile
} else {
    Log "Janela so de WhatsApp - motor_busca.py nao roda agora (evita gastar cota 3x/dia)."
}

Log "Concluido. O Windows volta a suspender sozinho depois do tempo de inatividade configurado."

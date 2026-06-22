param(
  [Alias("Host")]
  [string]$HostName = "",

  [string]$User = "",

  [string]$RemoteRoot = "~/mobile",

  [switch]$FrontendOnly,
  [switch]$BackendOnly,
  [switch]$InstallServices,
  [switch]$InstallCaddy,
  [switch]$RestartServices,
  [switch]$RestartFrontend,
  [switch]$RestartBackend,
  [switch]$InstallBackendDeps,
  [string]$CaddyDomain = "",
  [string]$CaddyAppPort = "8444",
  [string]$Caddyfile = "~/caddy/Caddyfile"
)

$ErrorActionPreference = "Stop"

function Require-Command($Name) {
  if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
    throw "Required command '$Name' was not found on PATH."
  }
}

function Invoke-Checked($Command, $Arguments) {
  Write-Host "> $Command $($Arguments -join ' ')" -ForegroundColor DarkGray
  & $Command @Arguments
  if ($LASTEXITCODE -ne 0) {
    throw "$Command failed with exit code $LASTEXITCODE"
  }
}

Require-Command "ssh"
Require-Command "scp"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$localConfig = Join-Path $repoRoot "deploy/local.ps1"
if (Test-Path $localConfig) {
  . $localConfig
}

if ([string]::IsNullOrWhiteSpace($HostName) -and (Get-Variable -Name JaradDeployHost -ErrorAction SilentlyContinue)) {
  $HostName = $JaradDeployHost
}
if ([string]::IsNullOrWhiteSpace($User) -and (Get-Variable -Name JaradDeployUser -ErrorAction SilentlyContinue)) {
  $User = $JaradDeployUser
}
if (-not $PSBoundParameters.ContainsKey("RemoteRoot") -and (Get-Variable -Name JaradRemoteRoot -ErrorAction SilentlyContinue)) {
  $RemoteRoot = $JaradRemoteRoot
}
if ([string]::IsNullOrWhiteSpace($CaddyDomain) -and (Get-Variable -Name JaradCaddyDomain -ErrorAction SilentlyContinue)) {
  $CaddyDomain = $JaradCaddyDomain
}
if (-not $PSBoundParameters.ContainsKey("CaddyAppPort") -and (Get-Variable -Name JaradCaddyAppPort -ErrorAction SilentlyContinue)) {
  $CaddyAppPort = $JaradCaddyAppPort
}
if (-not $PSBoundParameters.ContainsKey("Caddyfile") -and (Get-Variable -Name JaradCaddyfile -ErrorAction SilentlyContinue)) {
  $Caddyfile = $JaradCaddyfile
}
if ([string]::IsNullOrWhiteSpace($HostName) -or [string]::IsNullOrWhiteSpace($User)) {
  throw "-HostName and -User are required unless deploy/local.ps1 provides `$JaradDeployHost and `$JaradDeployUser."
}

$frontendPath = Join-Path $repoRoot "frontend"
$backendPath = Join-Path $repoRoot "backend"
$serverScriptsPath = Join-Path $repoRoot "scripts/server"
$systemdPath = Join-Path $repoRoot "deploy/systemd"
$caddyPath = Join-Path $repoRoot "deploy/caddy"
$remote = "${User}@${HostName}"

if (-not (Test-Path $frontendPath)) {
  throw "Missing frontend directory: $frontendPath"
}
if (-not (Test-Path $backendPath)) {
  throw "Missing backend directory: $backendPath"
}
if ($InstallCaddy -and [string]::IsNullOrWhiteSpace($CaddyDomain)) {
  throw "-InstallCaddy requires -CaddyDomain <device.tailnet.ts.net>."
}

Invoke-Checked "ssh" @($remote, "mkdir -p $RemoteRoot/frontend $RemoteRoot/backend $RemoteRoot/scripts/server $RemoteRoot/deploy/systemd $RemoteRoot/deploy/caddy")

if (-not $BackendOnly) {
  Write-Host "Deploying frontend..." -ForegroundColor Cyan
  Invoke-Checked "scp" @(
    "-r",
    (Join-Path $frontendPath "*"),
    "${remote}:$RemoteRoot/frontend/"
  )
}

if (-not $FrontendOnly) {
  Write-Host "Deploying backend..." -ForegroundColor Cyan
  Invoke-Checked "scp" @(
    "-r",
    (Join-Path $backendPath "jarad_backend"),
    (Join-Path $backendPath "requirements.txt"),
    (Join-Path $backendPath "README.md"),
    "${remote}:$RemoteRoot/backend/"
  )
  Invoke-Checked "scp" @(
    (Join-Path $serverScriptsPath "restart-backend.sh"),
    "${remote}:$RemoteRoot/scripts/server/restart-backend.sh"
  )
  Invoke-Checked "scp" @(
    (Join-Path $serverScriptsPath "install-systemd.sh"),
    "${remote}:$RemoteRoot/scripts/server/install-systemd.sh"
  )
  Invoke-Checked "scp" @(
    (Join-Path $serverScriptsPath "install-caddy-route.sh"),
    "${remote}:$RemoteRoot/scripts/server/install-caddy-route.sh"
  )
  Invoke-Checked "scp" @(
    (Join-Path $serverScriptsPath "jarad-dns-access"),
    "${remote}:$RemoteRoot/scripts/server/jarad-dns-access"
  )
  Invoke-Checked "scp" @(
    (Join-Path $systemdPath "jarad-backend.service"),
    (Join-Path $systemdPath "jarad-frontend.service"),
    "${remote}:$RemoteRoot/deploy/systemd/"
  )
  Invoke-Checked "scp" @(
    (Join-Path $caddyPath "jarad.Caddyfile"),
    "${remote}:$RemoteRoot/deploy/caddy/jarad.Caddyfile"
  )
  Invoke-Checked "ssh" @($remote, "chmod +x $RemoteRoot/scripts/server/restart-backend.sh $RemoteRoot/scripts/server/install-systemd.sh $RemoteRoot/scripts/server/install-caddy-route.sh $RemoteRoot/scripts/server/jarad-dns-access")
}

if ($InstallCaddy -and $FrontendOnly) {
  Write-Host "Deploying Caddy installer..." -ForegroundColor Cyan
  Invoke-Checked "scp" @(
    (Join-Path $serverScriptsPath "install-caddy-route.sh"),
    "${remote}:$RemoteRoot/scripts/server/install-caddy-route.sh"
  )
  Invoke-Checked "scp" @(
    (Join-Path $caddyPath "jarad.Caddyfile"),
    "${remote}:$RemoteRoot/deploy/caddy/jarad.Caddyfile"
  )
  Invoke-Checked "ssh" @($remote, "chmod +x $RemoteRoot/scripts/server/install-caddy-route.sh")
}

if ($InstallBackendDeps) {
  Write-Host "Installing backend dependencies..." -ForegroundColor Cyan
  Invoke-Checked "ssh" @(
    $remote,
    "cd $RemoteRoot/backend && python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt"
  )
}

if ($InstallServices) {
  Write-Host "Installing systemd services..." -ForegroundColor Cyan
  Invoke-Checked "ssh" @(
    "-tt",
    $remote,
    "$RemoteRoot/scripts/server/install-systemd.sh $RemoteRoot $User"
  )
}

if ($InstallCaddy) {
  Write-Host "Installing Caddy route..." -ForegroundColor Cyan
  Invoke-Checked "ssh" @(
    "-tt",
    $remote,
    "$RemoteRoot/scripts/server/install-caddy-route.sh $RemoteRoot $CaddyDomain $CaddyAppPort $Caddyfile"
  )
}

if ($RestartBackend) {
  Write-Host "Restarting backend..." -ForegroundColor Cyan
  Invoke-Checked "ssh" @(
    "-tt",
    $remote,
    "sudo systemctl restart jarad-backend.service"
  )
}

if ($RestartFrontend) {
  Write-Host "Restarting frontend..." -ForegroundColor Cyan
  Invoke-Checked "ssh" @(
    "-tt",
    $remote,
    "sudo systemctl restart jarad-frontend.service"
  )
}

if ($RestartServices) {
  Write-Host "Restarting frontend and backend services..." -ForegroundColor Cyan
  Invoke-Checked "ssh" @(
    "-tt",
    $remote,
    "sudo systemctl restart jarad-backend.service jarad-frontend.service"
  )
}

Write-Host "Deploy complete." -ForegroundColor Green

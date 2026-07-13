# Builds a functionality-structured integration workspace for NIFTY-PILOT-SOVEREIGN.
# Existing clones (root + libs) are linked via directory junctions (no copy, git pull
# still works through the link). Genuinely-missing high-value repos are cloned fresh.
$ErrorActionPreference = "Continue"
$base = "d:\INDIAN MARKET"
$root = $base
$libs = Join-Path $base "libs"
$work = Join-Path $base "integrations"

# category => list of repo folder names (resolved against root, then libs)
$map = [ordered]@{
  "01-broker-connectivity" = @("openalgo","openengine","smartapi-python","DhanHQ-py","DhanHQ-js","dhanhq-skills","pykiteconnect","ib_insync")
  "02-market-data-nse"     = @("nsepython","jugaad-data","nse-oi-visualizer","Python-NSE-Option-Chain-Analyzer","express-option-chain","kite-option-chain","india-stock-mcp","StockmarketDB","yfinance")
  "03-options-analytics"   = @("optopsy","ZerodhaStrikesAllowedToTrade")
  "04-backtesting-engines" = @("vectorbt","backtrader","backtesting.py","zipline-reloaded","qstrader","pybroker","bt","moonshot","hftbacktest")
  "05-live-trading-frameworks" = @("nautilus_trader","freqtrade","jesse","vnpy","lumibot","rqalpha","pyalgotrade")
  "06-indicators-ta"       = @("ta-lib-python","pandas-ta","ta","finta","stock-indicators-python","technical","bta-lib")
  "07-ml-quant-research"   = @("qlib","FinRL","FinGPT","tensortrade","agentic-equity-research-system","Nifty-500-Live-Sentiment-Analysis","TrendMaster")
  "08-strategy-references" = @("fully-automated-nifty-options-trading","nifty-options-analysis","NSE-Stock-Scanner","RRG-Sector-Rotation-India","AlgoApp","indian-trading-skills","freqtrade-strategies","example-strategies")
  "09-dashboards-ui"       = @("steadfast-monorepo")
  "10-data-research-terminal" = @("OpenBB")
}

# repos NOT present locally that are worth cloning fresh: category => url
$cloneFresh = [ordered]@{
  "03-options-analytics" = @("https://github.com/vollib/py_vollib.git")
}

if (-not (Test-Path $work)) { New-Item -ItemType Directory -Path $work | Out-Null }

$linked = 0; $missing = @(); $cloned = 0; $cloneFail = @()

function Resolve-Repo($name) {
  $r = Join-Path $script:root $name
  if (Test-Path $r -PathType Container) { return $r }
  $l = Join-Path $script:libs $name
  if (Test-Path $l -PathType Container) { return $l }
  return $null
}

foreach ($cat in $map.Keys) {
  $catDir = Join-Path $work $cat
  if (-not (Test-Path $catDir)) { New-Item -ItemType Directory -Path $catDir | Out-Null }
  foreach ($repo in $map[$cat]) {
    $target = Resolve-Repo $repo
    $link = Join-Path $catDir $repo
    if ($null -eq $target) { $script:missing += "$cat/$repo"; continue }
    if (Test-Path $link) { continue }
    New-Item -ItemType Junction -Path $link -Target $target -ErrorAction SilentlyContinue | Out-Null
    if (Test-Path $link) { $script:linked++ } else { $script:missing += "$cat/$repo (junction failed)" }
  }
}

foreach ($cat in $cloneFresh.Keys) {
  $catDir = Join-Path $work $cat
  if (-not (Test-Path $catDir)) { New-Item -ItemType Directory -Path $catDir | Out-Null }
  foreach ($url in $cloneFresh[$cat]) {
    $repo = ($url -split '/')[-1] -replace '\.git$',''
    $dest = Join-Path $catDir $repo
    if (Test-Path $dest) { continue }
    git clone --depth 1 $url "$dest" 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0 -and (Test-Path $dest)) { $script:cloned++ } else { $script:cloneFail += $url }
  }
}

Write-Output "Junctions created: $linked"
Write-Output "Fresh clones: $cloned"
if ($missing.Count)   { Write-Output "MISSING/skip:"; $missing   | ForEach-Object { Write-Output "  $_" } }
if ($cloneFail.Count) { Write-Output "CLONE FAILED:"; $cloneFail | ForEach-Object { Write-Output "  $_" } }

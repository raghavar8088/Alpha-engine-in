$ErrorActionPreference = "Continue"
$base = "d:\INDIAN MARKET"
$libs = Join-Path $base "libs"
if (-not (Test-Path $libs)) { New-Item -ItemType Directory -Path $libs | Out-Null }

# Indian / India-specific repos -> cloned at workspace root
$rootUrls = @(
  "https://github.com/marketcalls/openalgo.git",
  "https://github.com/marketcalls/openengine.git",
  "https://github.com/dhan-oss/DhanHQ-py.git",
  "https://github.com/angel-one/smartapi-python.git",
  "https://github.com/zerodha/pykiteconnect.git",
  "https://github.com/aeron7/nsepython.git",
  "https://github.com/jugaad-py/jugaad-data.git",
  "https://github.com/hi-imcodeman/pyNSE.git",
  "https://github.com/Akhilgovind02/india-stock-mcp.git",
  "https://github.com/VarunS2002/Python-NSE-Option-Chain-Analyzer.git",
  "https://github.com/anshuthopsee/nse-oi-visualizer.git",
  "https://github.com/anurag-roy/kite-option-chain.git",
  "https://github.com/pramakrishn/express-option-chain.git",
  "https://github.com/srikar-kodakandla/fully-automated-nifty-options-trading.git",
  "https://github.com/TechfaneTechnologies/ZerodhaStrikesAllowedToTrade.git",
  "https://github.com/sunnywilson93/nifty-options-analysis.git",
  "https://github.com/deshwalmahesh/NSE-Stock-Scanner.git",
  "https://github.com/suhas2090/StockmarketDB.git",
  "https://github.com/AdroitAnandAI/RRG-Sector-Rotation-India.git",
  "https://github.com/hemangjoshi37a/TrendMaster.git",
  "https://github.com/goldspanlabs/optopsy.git",
  "https://github.com/joesinghh/AlgoApp.git",
  "https://github.com/ajeeshworkspace/indian-trading-skills.git",
  "https://github.com/narenkram/steadfast-monorepo.git",
  "https://github.com/Shubxam/Nifty-500-Live-Sentiment-Analysis.git",
  "https://github.com/nabojyoti/agentic-equity-research-system.git"
)

# General quant / backtesting / crypto / AI repos -> cloned into libs/
$libUrls = @(
  "https://github.com/polakowo/vectorbt.git",
  "https://github.com/mementum/backtrader.git",
  "https://github.com/kernc/backtesting.py.git",
  "https://github.com/pmorissette/bt.git",
  "https://github.com/mhallsmoore/qstrader.git",
  "https://github.com/quantopian/zipline.git",
  "https://github.com/stefan-jansen/zipline-reloaded.git",
  "https://github.com/AI4Finance-Foundation/FinRL.git",
  "https://github.com/AI4Finance-Foundation/FinGPT.git",
  "https://github.com/microsoft/qlib.git",
  "https://github.com/tensortrade-org/tensortrade.git",
  "https://github.com/edtechre/pybroker.git",
  "https://github.com/twopirllc/pandas-ta.git",
  "https://github.com/bukosabino/ta.git",
  "https://github.com/mementum/bta-lib.git",
  "https://github.com/facioquo/stock-indicators-python.git",
  "https://github.com/peerchemist/finta.git",
  "https://github.com/freqtrade/freqtrade.git",
  "https://github.com/freqtrade/freqtrade-strategies.git",
  "https://github.com/nautechsystems/nautilus_trader.git",
  "https://github.com/jesse-ai/jesse.git",
  "https://github.com/ranaroussi/yfinance.git",
  "https://github.com/OpenBB-finance/OpenBB.git",
  "https://github.com/vnpy/vnpy.git",
  "https://github.com/ricequant/rqalpha.git",
  "https://github.com/gbeced/pyalgotrade.git",
  "https://github.com/bmoscon/cryptofeed.git",
  "https://github.com/ccxt/ccxt.git",
  "https://github.com/hummingbot/hummingbot.git",
  "https://github.com/Superalgos/Superalgos.git",
  "https://github.com/Drakkar-Software/OctoBot.git",
  "https://github.com/QuantConnect/Lean.git",
  "https://github.com/stellar/kelp.git",
  "https://github.com/butor/blackbird.git",
  "https://github.com/DeviaVir/zenbot.git",
  "https://github.com/hyperliquid-dex/hyperliquid-python-sdk.git",
  "https://github.com/drift-labs/protocol-v2.git",
  "https://github.com/freqtrade/technical.git",
  "https://github.com/freqtrade/ftui.git",
  "https://github.com/nkaz001/hftbacktest.git",
  "https://github.com/erdewit/ib_insync.git",
  "https://github.com/polakowo/vectorbt-pro-docs.git",
  "https://github.com/jesse-ai/example-strategies.git",
  "https://github.com/hummingbot/deploy.git",
  "https://github.com/hummingbot/quants-lab.git",
  "https://github.com/quantrocket-llc/quantrocket.git",
  "https://github.com/quantrocket-llc/moonshot.git",
  "https://github.com/tradingstrategy-ai/trade-executor.git",
  "https://github.com/tradingstrategy-ai/web3-ethereum-defi.git",
  "https://github.com/tradingstrategy-ai/trading-strategy.git",
  "https://github.com/enarjord/passivbot.git",
  "https://github.com/gunthercox/Chandler.git",
  "https://github.com/femtotrader/pynance.git",
  "https://github.com/quantmind/ta-lib-python.git",
  "https://github.com/flashbots/simple-arbitrage.git",
  "https://github.com/flashbots/searcher-sponsored-tx.git",
  "https://github.com/Uniswap/examples.git",
  "https://github.com/aave/aave-v3-core.git",
  "https://github.com/yearn/yearn-vaults.git"
)

# Build set of folder names already present (root + libs), case-insensitive
$existing = New-Object System.Collections.Generic.HashSet[string] ([System.StringComparer]::OrdinalIgnoreCase)
Get-ChildItem $base -Directory -Force | ForEach-Object { [void]$existing.Add($_.Name) }
Get-ChildItem $libs -Directory -Force | ForEach-Object { [void]$existing.Add($_.Name) }

# Folder-name overrides for generic / colliding names: "repo" => "newFolderName"
$overrides = @{ "examples" = "uniswap-examples" }

$report = New-Object System.Collections.Generic.List[string]
$cloned = 0; $skipped = 0; $failed = 0

function Clone-One($url, $destRoot) {
  $owner = ($url -split '/')[-2]
  $repo  = ($url -split '/')[-1] -replace '\.git$',''
  $folder = $repo
  if ($script:overrides.ContainsKey($repo.ToLower())) { $folder = $script:overrides[$repo.ToLower()] }

  if ($script:existing.Contains($folder) -or $script:existing.Contains($repo)) {
    Write-Host "SKIP (exists): $owner/$repo"
    $script:report.Add("SKIP   $owner/$repo")
    $script:skipped++
    return
  }
  $target = Join-Path $destRoot $folder
  Write-Host "CLONING: $owner/$repo -> $target"
  git clone --depth 1 $url "$target" 2>&1 | Out-Null
  if ($LASTEXITCODE -eq 0 -and (Test-Path $target)) {
    Write-Host "OK: $owner/$repo"
    $script:report.Add("OK     $owner/$repo")
    [void]$script:existing.Add($folder)
    $script:cloned++
  } else {
    Write-Host "FAIL: $owner/$repo (exit $LASTEXITCODE)"
    $script:report.Add("FAIL   $owner/$repo  ($url)")
    if (Test-Path $target) { Remove-Item -Recurse -Force $target -ErrorAction SilentlyContinue }
    $script:failed++
  }
}

foreach ($u in $rootUrls) { Clone-One $u $base }
foreach ($u in $libUrls)  { Clone-One $u $libs }

$summary = "==== CLONE SUMMARY ====`nCloned: $cloned  Skipped: $skipped  Failed: $failed`n=======================`n"
$reportText = $summary + ($report -join "`n")
Set-Content -Path (Join-Path $base "clone_report.txt") -Value $reportText -Encoding UTF8
Write-Host ""
Write-Host $summary

<#
 批量文本提取: docx→pandoc(--track-changes=all 保留批注/修订/高亮), pdf→pdftotext
 用法: powershell -File batch_extract.ps1 -Roots "E:\目录1","E:\目录2" -OutDir "E:\md目录"
 输出: OutDir\<原文件名>.md（重名自动加 __2 后缀）+ manifest.tsv（md文件/源文件/批次）
       批次 = 各 Root 下第一层子目录名；文件直接在 Root 下时用 Root 目录名
 注意: 本文件含中文，必须以 UTF-8 BOM 保存
#>
param(
    [Parameter(Mandatory = $true)][string[]]$Roots,
    [Parameter(Mandatory = $true)][string]$OutDir
)

function Find-Tool([string[]]$candidates) {
    foreach ($c in $candidates) {
        $cmd = Get-Command $c -ErrorAction SilentlyContinue
        if ($cmd) { return $cmd.Source }
    }
    return $null
}

# 定位 pandoc（PATH → 常见安装路径）
$pandoc = Find-Tool @('pandoc')
if (-not $pandoc) {
    $try = @(
        (Join-Path $env:LOCALAPPDATA 'Pandoc\pandoc.exe'),
        'C:\Program Files\Pandoc\pandoc.exe',
        'C:\Program Files (x86)\Pandoc\pandoc.exe'
    ) | Where-Object { Test-Path $_ } | Select-Object -First 1
    $pandoc = $try
}
if (-not $pandoc) { throw "未找到 pandoc，请安装: winget install JohnMacFarlane.Pandoc" }

# 定位 pdftotext（可选，无则跳过 PDF）
$pdftotext = Find-Tool @('pdftotext')
if (-not $pdftotext) {
    $try = @(
        'E:\adaconda\Library\bin\pdftotext.exe',
        'C:\Program Files\poppler\bin\pdftotext.exe'
    ) | Where-Object { Test-Path $_ } | Select-Object -First 1
    $pdftotext = $try
}

New-Item -ItemType Directory -Path $OutDir -Force | Out-Null
$manifest = Join-Path $OutDir 'manifest.tsv'
"md_file`tsource`tbatch" | Set-Content -LiteralPath $manifest -Encoding UTF8

$used = @{}
$pdfSkipped = 0
foreach ($root in $Roots) {
    if (-not (Test-Path -LiteralPath $root)) { continue }
    Get-ChildItem -LiteralPath $root -Recurse -File | Where-Object { $_.Name -notlike '~$*' } | ForEach-Object {
        $ext = $_.Extension.ToLower()
        if ($ext -ne '.docx' -and $ext -ne '.pdf') { return }
        $rel = $_.FullName.Substring($root.Length).Trim('\')
        if ($rel -eq '') { return }
        $parts = $rel -split '\\'
        $batch = if ($parts.Count -ge 2) { $parts[0] } else { Split-Path $root -Leaf }

        $base = $_.BaseName -replace '[\\/:*?"<>|]', '_'
        $mdName = $base + '.md'
        $i = 2
        while ($used.ContainsKey($mdName)) { $mdName = $base + '__' + $i + '.md'; $i++ }
        $used[$mdName] = $true
        $mdPath = Join-Path $OutDir $mdName

        if ($ext -eq '.docx') {
            & $pandoc --track-changes=all $_.FullName -o $mdPath 2>$null
        } else {
            if (-not $pdftotext) { $pdfSkipped++; return }
            & $pdftotext -enc UTF-8 $_.FullName $mdPath 2>$null
        }
        if (Test-Path -LiteralPath $mdPath) {
            "$mdName`t$($_.FullName)`t$batch" | Add-Content -LiteralPath $manifest -Encoding UTF8
        } else {
            Write-Output ("提取失败: " + $_.FullName)
        }
    }
}

$mdCount = (Get-ChildItem -LiteralPath $OutDir -Filter *.md -ErrorAction SilentlyContinue | Measure-Object).Count
"提取完成: $mdCount 个md 文件"
"清单: $manifest"
if ($pdfSkipped -gt 0) { "警告: $pdfSkipped 个PDF因无pdftotext被跳过（已记入缺口）" }


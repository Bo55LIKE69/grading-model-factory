<#
 老格式批量转换 .doc/.wps/伪扩展名docx → .docx
 用法: powershell -File convert_legacy.ps1 -Root "E:\作业根目录" [-OutRoot "输出目录"] [-TimeoutSec 45]
 输出: OutRoot（默认 <Root>_converted，保留子目录结构）；日志 OutRoot\convert_log.txt
 机制: 魔数识别真OLE文件才转换；每文件独立Word进程+看门狗；超时自动用OpenAndRepair重试一次；
       启动前及每次强杀后清理Resiliency注册表键（防"文档恢复"窗格阻塞）
 注意: 本文件含中文，必须以 UTF-8 BOM 保存
#>
param(
    [string]$Root = "",
    [string]$OutRoot = "",
    [int]$TimeoutSec = 45,
    [string]$SingleIn = "",
    [string]$SingleOut = "",
    [switch]$Repair
)

function Clear-Resiliency {
    $reKey = 'HKCU:\Software\Microsoft\Office\16.0\Word\Resiliency'
    if (Test-Path $reKey) { Remove-Item $reKey -Recurse -Force -ErrorAction SilentlyContinue }
}

# ---------- 单文件模式（由驱动器以子进程调用，勿传 -Root）----------
if ($SingleIn -ne '') {
    $word = $null; $doc = $null
    try {
        $word = New-Object -ComObject Word.Application
        $word.Visible = $false
        $word.DisplayAlerts = 0
        try { $word.AutomationSecurity = 3 } catch {}
        if ($Repair) {
            # OpenAndRepair: FileName, ConfirmConversions, ReadOnly, AddToRecentFiles, PasswordDocument,
            # PasswordTemplate, Revert, WritePasswordDocument, WritePasswordTemplate, Format, Encoding, Visible, OpenAndRepair
            $doc = $word.Documents.Open($SingleIn, $false, $true, $false, '', '', $false, '', '', 0, $false, $true)
        } else {
            $doc = $word.Documents.Open($SingleIn, $false, $true)
        }
        $doc.SaveAs2($SingleOut, 12)
        $doc.Close($false)
        Write-Output 'OK'
    } catch {
        Write-Output ('ERR:' + $_.Exception.Message)
        try { if ($doc) { $doc.Close($false) } } catch {}
    } finally {
        try { if ($word) { $word.Quit() } } catch {}
    }
    exit 0
}

# ---------- 驱动模式 ----------
if ($Root -eq '') { throw "必须提供 -Root <作业根目录>" }
if ($OutRoot -eq '') { $OutRoot = "$Root`_converted" }
New-Item -ItemType Directory -Path $OutRoot -Force | Out-Null
$log = Join-Path $OutRoot 'convert_log.txt'
$stageDir = Join-Path ([System.IO.Path]::GetTempPath()) 'convert_legacy_staging'
Clear-Resiliency

# 收集目标：魔数为真OLE的 .doc/.wps/.docx；魔数为ZIP但扩展名是 .doc/.wps 的直接复制
$targets = @()
Get-ChildItem -LiteralPath $Root -Recurse -File | Where-Object { $_.Name -notlike '~$*' } | ForEach-Object {
    if ($_.Extension -notin '.doc', '.docx', '.wps') { return }
    $fs = [System.IO.File]::OpenRead($_.FullName)
    $buf = New-Object byte[] 4
    $n = $fs.Read($buf, 0, 4); $fs.Close()
    if ($n -lt 4) { return }
    $hex = ($buf[0..3] | ForEach-Object { $_.ToString('X2') }) -join ' '
    $isOle = $hex -eq 'D0 CF 11 E0'
    $isZip = $hex -eq '50 4B 03 04'
    $rel = $_.FullName.Substring($Root.Length).Trim('\')
    $outRel = $rel -replace '\.[^.]+$', '.docx'
    if ($isOle) {
        $inPath = $_.FullName
        if ($_.Extension -eq '.docx') {
            # OLE 内容但 .docx 扩展名：Word 拒绝打开，先暂存为 .doc 副本再转
            if (-not (Test-Path -LiteralPath $stageDir)) { New-Item -ItemType Directory -Path $stageDir -Force | Out-Null }
            $staged = Join-Path $stageDir ($_.BaseName + '.doc')
            Copy-Item -LiteralPath $_.FullName -Destination $staged -Force
            $inPath = $staged
        }
        $targets += @{ In = $inPath; Out = (Join-Path $OutRoot $outRel) }
    } elseif ($isZip -and ($_.Extension -eq '.doc' -or $_.Extension -eq '.wps')) {
        $dst = Join-Path $OutRoot $outRel
        New-Item -ItemType Directory -Path (Split-Path -Parent $dst) -Force | Out-Null
        Copy-Item -LiteralPath $_.FullName -Destination $dst -Force
        Add-Content -LiteralPath $log -Value ("COPY-AS-DOCX: " + $_.FullName) -Encoding UTF8
    }
}

Add-Content -LiteralPath $log -Value ("DRIVER-START 待转换 " + $targets.Count + " 个 " + (Get-Date -Format 'HH:mm:ss')) -Encoding UTF8
$ok = 0; $fail = 0; $to = 0

function Invoke-Single([string]$inPath, [string]$outPath, [bool]$repair) {
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = 'powershell.exe'
    $arg = '-NoProfile -ExecutionPolicy Bypass -File "' + $PSCommandPath + '" -SingleIn "' + $inPath + '" -SingleOut "' + $outPath + '"'
    if ($repair) { $arg += ' -Repair' }
    $psi.Arguments = $arg
    $psi.WindowStyle = 'Hidden'
    $psi.UseShellExecute = $false
    return [System.Diagnostics.Process]::Start($psi)
}

foreach ($t in $targets) {
    if (Test-Path -LiteralPath $t.Out) { continue }
    New-Item -ItemType Directory -Path (Split-Path -Parent $t.Out) -Force | Out-Null

    $proc = Invoke-Single $t.In $t.Out $false
    if (-not $proc.WaitForExit($TimeoutSec * 1000)) {
        taskkill.exe /PID $proc.Id /T /F | Out-Null
        Start-Sleep -Milliseconds 500
        Clear-Resiliency
        # 看门狗超时 → 用 OpenAndRepair 重试一次
        $proc2 = Invoke-Single $t.In $t.Out $true
        if (-not $proc2.WaitForExit($TimeoutSec * 1000)) {
            taskkill.exe /PID $proc2.Id /T /F | Out-Null
            Start-Sleep -Milliseconds 500
            Clear-Resiliency
            $to++
            Add-Content -LiteralPath $log -Value ("TIMEOUT(含修复重试): " + $t.In) -Encoding UTF8
        } elseif (Test-Path -LiteralPath $t.Out) {
            $ok++
            Add-Content -LiteralPath $log -Value ("OK(REPAIR): " + $t.In) -Encoding UTF8
        } else {
            $fail++
            Add-Content -LiteralPath $log -Value ("FAIL(REPAIR): " + $t.In) -Encoding UTF8
        }
        try { $proc2.Dispose() } catch {}
    } else {
        if (Test-Path -LiteralPath $t.Out) {
            $ok++
            Add-Content -LiteralPath $log -Value ("OK: " + $t.In) -Encoding UTF8
        } else {
            $fail++
            Add-Content -LiteralPath $log -Value ("FAIL: " + $t.In) -Encoding UTF8
        }
    }
    try { $proc.Dispose() } catch {}
}
Add-Content -LiteralPath $log -Value ("DRIVER-DONE ok=$ok fail=$fail timeout=$to " + (Get-Date -Format 'HH:mm:ss')) -Encoding UTF8
if (Test-Path -LiteralPath $stageDir) { Remove-Item -LiteralPath $stageDir -Recurse -Force -ErrorAction SilentlyContinue }
"转换完成: ok=$ok fail=$fail timeout=$to"
"输出目录: $OutRoot"
"日志: $log"



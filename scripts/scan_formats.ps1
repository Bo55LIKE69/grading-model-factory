<#
 格式扫描盘点：识别老格式(OLE)/扩展名错位/PDF/疑似损坏件
 用法: powershell -File scan_formats.ps1 -Root "E:\作业根目录"
 输出: 扩展名统计 + 异常件清单（供阶段0盘点与阶段1转换前预判）
 注意: 本文件含中文，必须以 UTF-8 BOM 保存
#>
param([Parameter(Mandatory = $true)][string]$Root)

if (-not (Test-Path -LiteralPath $Root)) { throw "目录不存在: $Root" }

$stats = @{}
$anomalies = @()
Get-ChildItem -LiteralPath $Root -Recurse -File | Where-Object { $_.Name -notlike '~$*' } | ForEach-Object {
    $ext = $_.Extension.ToLower()
    if ($stats.ContainsKey($ext)) { $stats[$ext]++ } else { $stats[$ext] = 1 }
    if ($ext -notin '.doc', '.docx', '.wps', '.pdf') { return }
    $fs = [System.IO.File]::OpenRead($_.FullName)
    $buf = New-Object byte[] 8
    $n = $fs.Read($buf, 0, 8); $fs.Close()
    if ($n -lt 4) { $anomalies += ("疑似空/损坏文件 | " + $_.FullName); return }
    $hex = ($buf[0..3] | ForEach-Object { $_.ToString('X2') }) -join ' '
    $isOle = $hex -eq 'D0 CF 11 E0'
    $isZip = $hex -eq '50 4B 03 04'
    if ($ext -eq '.docx' -and $isOle) { $anomalies += ("docx实为doc(老格式,需Word转换) | " + $_.FullName) }
    elseif (($ext -eq '.doc' -or $ext -eq '.wps') -and $isZip) { $anomalies += ("$ext 实为docx(ZIP,可直接复制改名) | " + $_.FullName) }
    elseif ($ext -eq '.doc' -and -not ($isOle -or $isZip)) { $anomalies += ("doc非OLE非ZIP($hex) | " + $_.FullName) }
    elseif ($ext -eq '.docx' -and -not ($isOle -or $isZip)) { $anomalies += ("docx非OLE非ZIP($hex) | " + $_.FullName) }
    elseif ($ext -eq '.wps' -and -not $isOle) { $anomalies += ("wps非OLE($hex) | " + $_.FullName) }
}

"=== 扩展名统计 ==="
$stats.GetEnumerator() | Sort-Object Value -Descending | ForEach-Object { "{0}: {1}" -f $_.Key, $_.Value }
"=== 异常件（共 {0} 个）===" -f $anomalies.Count
$anomalies
"=== 老格式(.doc/.wps)合计: {0} 个（阶段1需转换）===" -f (($stats['.doc'] + $stats['.wps']) -as [int])


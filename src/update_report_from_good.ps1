<#
===============================================================================
Dual-AI Quality Guardian - evidence-driven report update (HTML only)
Author  : Y.TOYODA
Purpose : Update the GOOD displacement and chart from a verified GOOD R1 witness.
Safety  : No API, Gazebo, robot commands, or network; output is a new HTML file.
Notes   : Use Chrome/Edge Print -> Save as PDF. Do not submit the old PDF when
          a new GOOD experiment has been completed unless the numbers agree.
===============================================================================
#>
param()
$ErrorActionPreference='Stop'
try {
    $root=Split-Path -Parent $PSScriptRoot
    $template=Join-Path $root 'report_source.html'
    $out=Join-Path $root 'report_after_good_r1.html'
    $downloads=Join-Path $env:USERPROFILE 'Downloads'
    $match=@(Get-ChildItem -LiteralPath $downloads -Filter 'good_maxstroke_r1_*.witness.json' -File)
    if($match.Count -ne 1){throw 'ONE_GOOD_R1_WITNESS_REQUIRED'}
    if(-not(Test-Path -LiteralPath $template -PathType Leaf) -or
        (Test-Path -LiteralPath $out)){throw 'TEMPLATE_NOT_FOUND_OR_OUTPUT_EXISTS'}
    $w=Get-Content -LiteralPath $match[0].FullName -Raw -Encoding UTF8 | ConvertFrom-Json
    $stem=$match[0].Name.Replace('.witness.json','')
    $video=Join-Path $downloads ($stem+'.mp4')
    $motion=Join-Path $downloads ($stem+'.motion.json')
    if($w.mode -cne 'REAL_GAZEBO_SIMULATION_GOOD_R1' -or
       $w.joint_return_verified -ne $true -or
       $w.status -notin @('PASS_100MM_MEASURED','PASS_BOUNDED_MAX_MEASURED_BELOW_100MM') -or
       -not(Test-Path -LiteralPath $video -PathType Leaf) -or
       -not(Test-Path -LiteralPath $motion -PathType Leaf) -or
       (Get-FileHash -LiteralPath $video -Algorithm SHA256).Hash -cne ([string]$w.video_sha256).ToUpperInvariant() -or
       (Get-FileHash -LiteralPath $motion -Algorithm SHA256).Hash -cne ([string]$w.motion_sha256).ToUpperInvariant()) {
        throw 'GOOD_EVIDENCE_CONTENT_OR_HASH_INVALID'
    }
    $p=[double]$w.peak_cube_dx_mm
    $f=[double]$w.final_cube_dx_mm
    if($p -lt 5 -or $f -lt 5){throw 'GOOD_MOVE_TOO_SMALL_FOR_R1'}
    $newPeak=$p.ToString('0.00',[Globalization.CultureInfo]::InvariantCulture)
    $newFinal=$f.ToString('0.00',[Globalization.CultureInfo]::InvariantCulture)
    $percent=[Math]::Max(0,[Math]::Min(100,$p))
    $pc=$percent.ToString('0.00',[Globalization.CultureInfo]::InvariantCulture)
    $html=Get-Content -LiteralPath $template -Raw -Encoding UTF8
    $edits=@(
      @{Old='<td>+3.05mm<br><span class="quiet">既存R4映像</span></td><td>+3.05mm<br><span class="quiet">長ストローク版は未測定</span></td>';
        New="<td>+$($newPeak)mm<br><span class=`"quiet`">GOOD R1実測</span></td><td>+$($newFinal)mm<br><span class=`"quiet`">GOOD R1実測</span></td>"},
      @{Old='GOOD +3.05mm';New="GOOD +$($newPeak)mm"},
      @{Old='style="width:3.05%"';New="style=`"width:$pc%`""},
      @{Old='<span class="tiny">3.1%</span>';New="<span class=`"tiny`">$($percent.ToString('0.0',[Globalization.CultureInfo]::InvariantCulture))%</span>"},
      @{Old='GOODの100mm長ストローク追加試験は未実施。';New="GOOD側の長ストローク実測は最大+$($newPeak)mm、終了時+$($newFinal)mm。"},
      @{Old='GOODの既存映像は+3.05453mmであり、新しい長ストロークの測定前には100mm達成と表示しない。';
        New="GOOD側は新しいR1試験によりピーク+$($newPeak)mm、終了時+$($newFinal)mmを実測した。"}
    )
    foreach($e in $edits) {
        if(-not $html.Contains([string]$e.Old)){throw "REPORT_TEMPLATE_ANCHOR_MISSING:$($e.Old.Substring(0,[Math]::Min(35,$e.Old.Length)))"}
        $html=$html.Replace([string]$e.Old,[string]$e.New)
    }
    # Output next to source report so its evidence/relative image links still work.
    [IO.File]::WriteAllText($out,$html,[Text.UTF8Encoding]::new($false))
    Write-Host "UPDATED_REPORT_HTML=$out"
    Write-Host "GOOD_R1_PEAK_MM=$newPeak"
    Write-Host "GOOD_R1_FINAL_MM=$newFinal"
    Write-Host 'REPORT_UPDATE_GATE=PASS_HTML_OUTPUT_PRINT_TO_PDF_REQUIRED'
    exit 0
}
catch {
    Write-Host "REPORT_UPDATE_GATE=HOLD; REASON=$($_.Exception.Message)"
    exit 3
}

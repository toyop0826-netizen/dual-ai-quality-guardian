<#
===============================================================================
Dual-AI Quality Guardian - final submission evidence collector
Author  : Y.TOYODA
Version : 1.0 / 2026-11-02

Purpose:
  1. Verify the already rendered GOOD, DEFECT and combined real videos.
  2. Verify camera, AI report, motion JSON and original MP4 evidence hashes.
  3. Copy them into a new folder, create SHA256SUMS.csv, then ZIP it.

Safety:
  READ ONLY on Docker/Gazebo: this script does not use Docker, APIs, or robot.
  Never overwrites an existing target directory or ZIP.
  Does not claim 100 mm unless measured original GOOD evidence proves it.
  On any mismatch: HOLD. Do not delete original evidence.
===============================================================================
#>
param(
    [switch]$AllowPriorGood,
    [string]$UpdatedReportPdf = ''
)
$ErrorActionPreference='Stop'
$dl=Join-Path $env:USERPROFILE 'Downloads'
$package=Split-Path -Parent $PSScriptRoot
$videos=Join-Path $dl 'PAI_Submission_Movies_Final'
$out=Join-Path $dl 'PAI_Final_Evidence_20261102'
$zip=Join-Path $dl 'PAI_Final_Evidence_20261102.zip'
$expectedGoodOld='8F7CDF82A2A17DE9628E81D8E2F69064CEB12DFFD8B25C35CC1865148FA69362'
$expectedNg=@{
    video='A64F3871DBD44A3C8E91256007C5A0855AEF766E3109FE2CB20CCC4ECBADE30D'
    motion='1897A95C916EBF464EBAE63B8613A9B2DE6E18FB423E801ADAE31858CA79568E'
    witness='837A1ACD170906F262E1B2BE70BE81E9A2652FE1BB16F2EE535BF4F5DA0F2A22'
}
$expectedAi='AAAA58D1EE31F148E5AD9FEB01C1F8F5FDDA4C7A048C08497FC0BDD4EAD726F6'
$expectedCamera='655B5472E83CBB58AC42791310F61D0679C17CF279D0A325C687D97A2AD7963E'
$record=New-Object 'System.Collections.Generic.List[object]'
function File-Sha([string]$p) {
    if(-not(Test-Path -LiteralPath $p -PathType Leaf)){throw "MISSING_FILE:$p"}
    return (Get-FileHash -LiteralPath $p -Algorithm SHA256).Hash.ToUpperInvariant()
}
function Verified-Copy([string]$src,[string]$dest,[string]$expected,[string]$note) {
    $hash=File-Sha $src
    if(-not $expected -or $hash -cne $expected.ToUpperInvariant()) {
        throw "INPUT_SHA256_MISMATCH:$src"
    }
    if(Test-Path -LiteralPath $dest){throw "DEST_EXISTS_NO_OVERWRITE:$dest"}
    Copy-Item -LiteralPath $src -Destination $dest -ErrorAction Stop
    if((File-Sha $dest) -cne $hash){throw "OUTPUT_SHA256_MISMATCH:$dest"}
    $script:record.Add([PSCustomObject]@{
        file=[IO.Path]::GetFileName($dest);sha256=$hash;purpose=$note
    })
}
try {
    if((Test-Path -LiteralPath $out) -or (Test-Path -LiteralPath $zip)) {
        throw 'EVIDENCE_DESTINATION_EXISTS_NO_OVERWRITE'
    }
    $vmanifest=Join-Path $videos 'video_build_manifest.json'
    $doc=Get-Content -LiteralPath $vmanifest -Raw -Encoding UTF8 | ConvertFrom-Json
    if($doc.mode -cne 'EVIDENCE_LINKED_GENUINE_GAZEBO_STORY_EDIT' -or
       $doc.legacy_good_fallback -ne ([bool]$AllowPriorGood) -or
       ([string]$doc.source_ng_sha256).ToUpperInvariant() -cne $expectedNg.video) {
        throw 'VIDEO_MANIFEST_INVALID_OR_FALLBACK_NOT_MATCHING'
    }
    $reportSource=Join-Path $package 'report_source.html'
    if($AllowPriorGood) {
        if(-not([string]::IsNullOrWhiteSpace($UpdatedReportPdf))) {
            throw 'UPDATED_REPORT_NOT_APPLICABLE_TO_OLD_GOOD_FALLBACK'
        }
        # Locate the unique provided PDF with the expected course prefix.
        $reportCandidates=@(Get-ChildItem -LiteralPath $package -Filter '*.pdf' -File)
        if($reportCandidates.Count -ne 1){throw 'EXPECTED_ONE_BASELINE_REPORT_PDF'}
        $report=$reportCandidates[0].FullName
        if(([string]$doc.source_good_sha256).ToUpperInvariant() -cne $expectedGoodOld) {
            throw 'LEGACY_GOOD_MANIFEST_SHA256_MISMATCH'
        }
        $goodVideo=Join-Path (Join-Path $package 'media') 'GOOD_previous_real_3mm.mp4'
        $goodMotion=$null
        $goodWitness=$null
        $goodHash=$expectedGoodOld
    }
    else {
        if([string]::IsNullOrWhiteSpace($UpdatedReportPdf)) {
            throw 'UPDATED_GOOD_R1_PDF_REQUIRED_FOR_NEW_MEASUREMENTS'
        }
        $report=$UpdatedReportPdf
        $goodMatches=@(Get-ChildItem -LiteralPath $dl -Filter 'good_maxstroke_r1_*.witness.json' -File)
        if($goodMatches.Count -ne 1){throw 'NEW_GOOD_WITNESS_MISSING_OR_AMBIGUOUS'}
        $goodWitness=$goodMatches[0].FullName
        $stem=$goodMatches[0].Name.Replace('.witness.json','')
        $goodVideo=Join-Path $dl ($stem+'.mp4')
        $goodMotion=Join-Path $dl ($stem+'.motion.json')
        $w=Get-Content -LiteralPath $goodWitness -Raw -Encoding UTF8 | ConvertFrom-Json
        if($w.status -notin @('PASS_100MM_MEASURED','PASS_BOUNDED_MAX_MEASURED_BELOW_100MM') -or
           $w.joint_return_verified -ne $true -or
           ([double]$w.final_cube_dx_mm) -lt 5.0) {
            throw 'NEW_GOOD_MEASUREMENTS_NOT_ACCEPTABLE'
        }
        $goodHash=([string]$w.video_sha256).ToUpperInvariant()
        if($goodHash -cne ([string]$doc.source_good_sha256).ToUpperInvariant()) {
            throw 'NEW_GOOD_VIDEO_MANIFEST_DISAGREES'
        }
    }
    $ngStem='ng_maxstroke_r2_20261101T163442Z_1793550882831717730'
    $ngVideo=Join-Path $dl ($ngStem+'.mp4')
    $ngMotion=Join-Path $dl ($ngStem+'.motion.json')
    $ngWitness=Join-Path $dl ($ngStem+'.witness.json')
    $ai=Join-Path $dl 'dual_ai_v4_defect_result.json'
    $camera=Join-Path $dl 'v4_clearface_defect_camera_v4_640x480.png'
    if((File-Sha $ngVideo) -cne $expectedNg.video -or
       (File-Sha $ngMotion) -cne $expectedNg.motion -or
       (File-Sha $ngWitness) -cne $expectedNg.witness -or
       (File-Sha $ai) -cne $expectedAi -or
       (File-Sha $camera) -cne $expectedCamera) {
        throw 'PINNED_INPUT_EVIDENCE_MISMATCH'
    }
    if($AllowPriorGood) {
        if((File-Sha $goodVideo) -cne $goodHash){throw 'OLD_GOOD_VIDEO_MISMATCH'}
    }
    else {
        if((File-Sha $goodVideo) -cne $goodHash -or
           (File-Sha $goodMotion) -cne ([string]$w.motion_sha256).ToUpperInvariant()) {
            throw 'NEW_GOOD_VIDEO_OR_MOTION_MISMATCH'
        }
    }
    # No input was changed. Create target only after all provenance checks.
    New-Item -ItemType Directory -Path $out -ErrorAction Stop | Out-Null
    foreach($name in @('GOOD_story.mp4','DEFECT_story.mp4','PAI_final_two_cases_story.mp4')) {
        $entry=$doc.output.PSObject.Properties[$name]
        if($null -eq $entry){throw "MISSING_STORY_MANIFEST_ENTRY:$name"}
        $src=Join-Path $videos $name
        Verified-Copy $src (Join-Path $out $name) ([string]$entry.Value.sha256) 'Story video edited from original Gazebo MP4'
        $sec=[double]$entry.Value.duration_sec
        if($sec -lt 60 -or $sec -gt 180){throw "STORY_DURATION_OUT_OF_RANGE:$name"}
    }
    Verified-Copy $vmanifest (Join-Path $out 'video_build_manifest.json') (File-Sha $vmanifest) 'Story provenance manifest'
    Verified-Copy $goodVideo (Join-Path $out 'GOOD_original_Gazebo.mp4') $goodHash 'Unmodified GOOD Gazebo recording'
    if(-not $AllowPriorGood) {
        Verified-Copy $goodMotion (Join-Path $out 'GOOD_original_motion.json') ([string]$w.motion_sha256) 'GOOD actual displacement samples'
        Verified-Copy $goodWitness (Join-Path $out 'GOOD_original_witness.json') (File-Sha $goodWitness) 'GOOD measurement witness'
    }
    Verified-Copy $ngVideo (Join-Path $out 'DEFECT_original_Gazebo.mp4') $expectedNg.video 'Unmodified DEFECT Gazebo R2 recording'
    Verified-Copy $ngMotion (Join-Path $out 'DEFECT_original_motion.json') $expectedNg.motion 'DEFECT actual displacement samples'
    Verified-Copy $ngWitness (Join-Path $out 'DEFECT_original_witness.json') $expectedNg.witness 'DEFECT measurement witness'
    Verified-Copy $ai (Join-Path $out 'DEFECT_AI_V4_real_results.json') $expectedAi 'Actual independent provider responses'
    Verified-Copy $camera (Join-Path $out 'DEFECT_camera_V4.png') $expectedCamera 'Original 640x480 V4 image'
    Verified-Copy $report (Join-Path $out 'PAI_Final_Report.pdf') (File-Sha $report) 'Course PDF report'
    $csv=Join-Path $out 'SHA256SUMS.csv'
    $record | Export-Csv -LiteralPath $csv -NoTypeInformation -Encoding UTF8
    $final=@($record | ForEach-Object {Join-Path $out $_.file})
    if($final.Count -lt 10){throw 'EVIDENCE_COUNT_UNEXPECTED'}
    foreach($r in $record) {
        if((File-Sha (Join-Path $out $r.file)) -cne $r.sha256) {
            throw 'FINAL_EVIDENCE_RECHECK_MISMATCH'
        }
    }
    Compress-Archive -LiteralPath $out -DestinationPath $zip -CompressionLevel NoCompression -ErrorAction Stop
    if(-not(Test-Path -LiteralPath $zip -PathType Leaf)){throw 'FINAL_EVIDENCE_ZIP_MISSING'}
    Write-Host "FINAL_EVIDENCE_FOLDER=$out"
    Write-Host "FINAL_EVIDENCE_ZIP=$zip"
    Write-Host "FINAL_EVIDENCE_ZIP_SHA256=$(File-Sha $zip)"
    Write-Host "FINAL_EVIDENCE_FILE_COUNT=$($record.Count)"
    Write-Host 'EVIDENCE_BUNDLE_GATE=PASS_GENUINE_SOURCES_HASH_CHECKED_NO_MOTION'
    exit 0
}
catch {
    Write-Host "EVIDENCE_BUNDLE_GATE=HOLD; REASON=$($_.Exception.Message)"
    Write-Host 'NO_ROBOT_COMMANDS_SENT_BY_COLLECTOR=True'
    exit 3
}

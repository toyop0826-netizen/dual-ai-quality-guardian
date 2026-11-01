<#
================================================================================
Project : Dual-AI Quality Guardian / Final Submission
Title   : Verified video + evidence packaging (GOOD R1 / DEFECT R2)
Author  : Y.TOYODA
Date    : 2026-11-02

PURPOSE
  1) Verify two GENUINE Gazebo recordings and related movement evidence.
  2) Generate GOOD, DEFECT, and combined story MP4 files with the tested
     original video editor from the previously extracted assignment package.
  3) Produce an evidence ZIP containing videos, measurements and the revised PDF.

IMPORTANT SAFETY CONSTRAINTS
  - No AI API calls. No robot motion, Gazebo world resets, or model pose writes.
  - Explicitly preserves V4 OpenAI=REVIEW / Gemini=DEFECT (human NG demo).
  - Never represents the 100 mm TARGET as a measured displacement.
  - Refuse hash mismatches and previously existing output directories.
  - This script uses the user's local Downloads files; it cannot regenerate
    genuine Gazebo footage, and does not fabricate missing source evidence.

USAGE
  .\FINALIZE_SUBMISSION_R1.ps1 -Action Preflight
  .\FINALIZE_SUBMISSION_R1.ps1 -Action Build
  Use Windows PowerShell 5.1. API keys are NOT needed.
================================================================================
#>
param(
    [ValidateSet('Preflight', 'Build')]
    [string]$Action = 'Preflight',
    [string]$ReportPdf = ''
)
$ErrorActionPreference = 'Stop'

$dl = Join-Path $env:USERPROFILE 'Downloads'
$package = Join-Path $dl 'PAI_Final_Submission_20261102'
$source = Join-Path $package 'source'
$goodStem = 'good_maxstroke_r1_20261101T170844Z_1793552924326072518'
$ngStem = 'ng_maxstroke_r2_20261101T163442Z_1793550882831717730'
$container = 'physicalai_crane'
$remoteStage = '/home/ubuntu/pai_demo/pai_final_story_v1'
$movieDir = Join-Path $dl 'PAI_Submission_Movies_Final'
$evidenceDir = Join-Path $dl 'PAI_Final_Evidence_20261102'
$evidenceZip = Join-Path $dl 'PAI_Final_Evidence_20261102.zip'

if ([string]::IsNullOrWhiteSpace($ReportPdf)) {
    $ReportPdf = Join-Path $dl ([string]'説明資料_PAI最終課題_ACCOUNT_ID.pdf')
}

# SHA-256 values are pinned to actual console-recorded evidence, not AI guesses.
$required = @(
    @{Tag='GOOD_R1_MP4';Path=(Join-Path $dl ($goodStem + '.mp4'));Sha='6ED14310156F6036FE5F0F2A364B148C3659FD10CC1F4A5D89AA62E99DF2EAAB'},
    @{Tag='GOOD_R1_MOTION';Path=(Join-Path $dl ($goodStem + '.motion.json'));Sha='14F6E03DD99224ED05D164C611C67C39221EA97AD5BFCFB9F1C57BBEB986EF9B'},
    @{Tag='GOOD_R1_WITNESS';Path=(Join-Path $dl ($goodStem + '.witness.json'));Sha='9B645FAFFC06AA041318D25716B1E32312A3434431EC535BEF65C72126312065'},
    @{Tag='DEFECT_R2_MP4';Path=(Join-Path $dl ($ngStem + '.mp4'));Sha='A64F3871DBD44A3C8E91256007C5A0855AEF766E3109FE2CB20CCC4ECBADE30D'},
    @{Tag='DEFECT_R2_MOTION';Path=(Join-Path $dl ($ngStem + '.motion.json'));Sha='1897A95C916EBF464EBAE63B8613A9B2DE6E18FB423E801ADAe31858CA79568E'},
    @{Tag='DEFECT_R2_WITNESS';Path=(Join-Path $dl ($ngStem + '.witness.json'));Sha='837A1ACD170906F262E1B2BE70BE81E9A2652FE1BB16F2EE535BF4F5DA0F2A22'},
    @{Tag='AI_V4';Path=(Join-Path $dl 'dual_ai_v4_defect_result.json');Sha='AAAA58D1EE31F148E5AD9FEB01C1F8F5FDDA4C7A048C08497FC0BDD4EAD726F6'},
    @{Tag='CAMERA_V4';Path=(Join-Path $dl 'v4_clearface_defect_camera_v4_640x480.png');Sha='655B5472E83CBB58AC42791310F61D0679C17CF279D0A325C687D97A2AD7963E'},
    @{Tag='FINAL_REPORT';Path=$ReportPdf;Sha='C2278225DDC42E1C93ACB029233D6F94C29201D9B1D45DC62608C7C12EA89C3E'},
    @{Tag='STORY_ASSEMBLER';Path=(Join-Path $source 'assemble_submission_videos.ps1');Sha='BF3E7751ACE431CB7D84D86365CDCFBC0B6652C3C2320E6215C3A80C67B43C3A'},
    @{Tag='EVIDENCE_COLLECTOR';Path=(Join-Path $source 'collect_final_evidence.ps1');Sha='2599BE7C8F66E2C683E70B2688A497FCADC2B393A743A71F7C6EE85DD49A0E6D'}
)

function Assert-File-Hash([string]$File, [string]$Expected, [string]$Tag) {
    # Guard 1: never accept missing files, directories, or SHA-256 mismatches.
    if (-not (Test-Path -LiteralPath $File -PathType Leaf)) {
        throw "MISSING_$($Tag):$File"
    }
    if ($Expected -notmatch '^[A-Fa-f0-9]{64}$') {
        throw "BAD_EXPECTED_SHA_$Tag"
    }
    $actual = (Get-FileHash -LiteralPath $File -Algorithm SHA256).Hash.ToUpperInvariant()
    if ($actual -cne $Expected.ToUpperInvariant()) {
        throw "HASH_MISMATCH_$($Tag):$actual"
    }
    Write-Host "FINAL_INPUT_$($Tag)=PASS_SHA256"
}

function Assert-Bounded-Number([object]$Value,[double]$Nominal,[string]$Tag) {
    # Guard 2: require plausible REAL measurements, not target distances.
    $v = [double]$Value
    if ([double]::IsNaN($v) -or [double]::IsInfinity($v) -or
        [Math]::Abs($v - $Nominal) -gt 0.06) {
        throw "MEASUREMENT_MISMATCH_$($Tag):$v"
    }
}

try {
    if (-not (Test-Path -LiteralPath $package -PathType Container)) {
        throw 'ORIGINAL_SUBMISSION_PACKAGE_NOT_EXTRACTED'
    }
    if ((Test-Path -LiteralPath $movieDir) -or
        (Test-Path -LiteralPath $evidenceDir) -or
        (Test-Path -LiteralPath $evidenceZip)) {
        throw 'OUTPUT_ALREADY_EXISTS_NO_OVERWRITE'
    }

    foreach ($file in $required) {
        Assert-File-Hash ([string]$file.Path) ([string]$file.Sha) ([string]$file.Tag)
    }

    $goodW = Get-Content -LiteralPath (Join-Path $dl ($goodStem + '.witness.json')) -Encoding UTF8 -Raw | ConvertFrom-Json
    $ngW = Get-Content -LiteralPath (Join-Path $dl ($ngStem + '.witness.json')) -Encoding UTF8 -Raw | ConvertFrom-Json

    if ($goodW.mode -cne 'REAL_GAZEBO_SIMULATION_GOOD_R1' -or
        $goodW.status -cne 'PASS_BOUNDED_MAX_MEASURED_BELOW_100MM' -or
        $goodW.joint_return_verified -ne $true -or
        $goodW.automatic_ai_actuation -ne $false) {
        throw 'GOOD_WITNESS_STATUS_INVALID'
    }
    Assert-Bounded-Number $goodW.peak_cube_dx_mm 57.9031 'GOOD_PEAK_MM'
    Assert-Bounded-Number $goodW.final_cube_dx_mm 45.6114 'GOOD_FINAL_MM'

    if ($ngW.mode -cne 'SIM_ONLY_HUMAN_DEFECT_EXTENDED_MOVEMENT_R2_VIDEO' -or
        $ngW.status -cne 'PASS_BOUNDED_MAX_MEASURED_BELOW_100MM' -or
        $ngW.v4_ai_fusion -cne 'REVIEW' -or
        $ngW.manual_override_demo -ne $true -or
        $ngW.joint_return_verified -ne $true) {
        throw 'DEFECT_WITNESS_STATUS_INVALID'
    }
    Assert-Bounded-Number $ngW.measured_peak_negative_x_mm (-65.940) 'DEFECT_PEAK_MM'
    Assert-Bounded-Number $ngW.measured_final_x_mm (-18.13588) 'DEFECT_FINAL_MM'

    # Guard 3: check Docker exists and that story stage has not been used.
    $state = @(& docker inspect --format '{{.State.Running}}' $container 2>&1)
    $rc = $LASTEXITCODE
    if ($rc -ne 0 -or $state.Count -ne 1 -or ([string]$state[0]).Trim() -cne 'true') {
        throw 'DOCKER_CONTAINER_NOT_RUNNING'
    }
    & docker exec --user ubuntu $container test -e $remoteStage 2>$null
    $rc = $LASTEXITCODE
    if ($rc -eq 0) {throw 'REMOTE_STORY_STAGE_ALREADY_EXISTS_NO_OVERWRITE'}
    if ($rc -ne 1) {throw "REMOTE_STORY_STAGE_CHECK_FAILED_$rc"}

    Write-Host 'FINAL_PREFLIGHT=PASS_ALL_GENUINE_INPUTS_AND_NO_OVERWRITE'
    Write-Host 'GOOD_PEAK_MM=57.9031; GOOD_FINAL_MM=45.6114'
    Write-Host 'DEFECT_PEAK_MM=-65.940; DEFECT_FINAL_MM=-18.13588'
    Write-Host 'AI_DEFECT=OPENAI_REVIEW_GEMINI_DEFECT_HUMAN_CONFIRMED'
    Write-Host 'SIMULATION_MOTION_REQUESTS=0'
    Write-Host 'AI_API_REQUESTS=0'

    if ($Action -ceq 'Preflight') {
        Write-Host 'FINALIZATION=PASS_PREFLIGHT_ONLY_NO_VIDEO_BUILD'
        exit 0
    }

    Write-Host 'FINAL_BUILD_START=STORY_VIDEOS'
    $assembler = Join-Path $source 'assemble_submission_videos.ps1'
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $assembler
    $rc = $LASTEXITCODE
    if ($rc -ne 0) {throw "STORY_VIDEOS_HOLD_EXIT_$rc"}

    Write-Host 'FINAL_BUILD_STAGE_PASS=STORY_VIDEOS'
    $collector = Join-Path $source 'collect_final_evidence.ps1'
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $collector -UpdatedReportPdf $ReportPdf
    $rc = $LASTEXITCODE
    if ($rc -ne 0) {throw "EVIDENCE_BUNDLE_HOLD_EXIT_$rc"}

    $needed = @('GOOD_story.mp4','DEFECT_story.mp4','PAI_final_two_cases_story.mp4')
    foreach ($name in $needed) {
        $p = Join-Path $movieDir $name
        if (-not (Test-Path -LiteralPath $p -PathType Leaf)) {
            throw "FINAL_VIDEO_MISSING:$name"
        }
        Write-Host "FINAL_VIDEO_READY=$p"
    }
    if (-not (Test-Path -LiteralPath $evidenceZip -PathType Leaf)) {
        throw 'EVIDENCE_ZIP_MISSING_AFTER_COLLECTOR_PASS'
    }
    Write-Host "FINAL_EVIDENCE_ZIP_READY=$evidenceZip"
    Write-Host "FINAL_EVIDENCE_SHA256=$((Get-FileHash -LiteralPath $evidenceZip -Algorithm SHA256).Hash)"
    Write-Host 'FINALIZATION=PASS_THREE_GENUINE_VIDEOS_AND_EVIDENCE'
    exit 0
}
catch {
    Write-Host "FINALIZATION=HOLD; REASON=$($_.Exception.Message)"
    Write-Host 'NO_AUTOMATIC_RETRY=True'
    Write-Host 'SIMULATION_MOTION_REQUESTS=0'
    exit 3
}

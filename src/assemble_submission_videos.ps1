<#
===============================================================================
Dual-AI Quality Guardian - real Gazebo story / evidence packaging
Author  : Y.TOYODA
Platform: Windows PowerShell 5.1, Docker physicalai_crane, ffmpeg in Docker
Role    : No robot motion. Verify input PNGs/videos/JSON; build 2 case stories
          and 1 combined 1-3 minute movie; copy and recheck every SHA-256.
Important: Never use this as a substitute for the GOOD sim motion test.
===============================================================================
#>
param([switch]$AllowPriorGood)
$ErrorActionPreference='Stop'
$container='physicalai_crane'
$downloads=Join-Path $env:USERPROFILE 'Downloads'
$stage='/home/ubuntu/pai_demo/pai_final_story_v1'
$target=Join-Path $downloads 'PAI_Submission_Movies_Final'
$ngStem='ng_maxstroke_r2_20261101T163442Z_1793550882831717730'
$expectedLegacyGood='8F7CDF82A2A17DE9628E81D8E2F69064CEB12DFFD8B25C35CC1865148FA69362'
$expectedNgVideo='A64F3871DBD44A3C8E91256007C5A0855AEF766E3109FE2CB20CCC4ECBADE30D'
$expectedNgMotion='1897A95C916EBF464EBAE63B8613A9B2DE6E18FB423E801ADAE31858CA79568E'
$expectedNgWitness='837A1ACD170906F262E1B2BE70BE81E9A2652FE1BB16F2EE535BF4F5DA0F2A22'
$expectedAiV4='AAAA58D1EE31F148E5AD9FEB01C1F8F5FDDA4C7A048C08497FC0BDD4EAD726F6'
$items=@(
    @{Name='make_story_videos.py';Sha='71EE4A6A5DAB3125BF5C4AA4D660C327E6FF8CFB3594CC056A16ECF060549006'},
    @{Name='end.png';Sha='6BA57D7D564C1E09F141A7CC51174F307684FF74E5B247FEA21734C7032939E2'},
    @{Name='good_action.png';Sha='1AD50ADE62438D063C0D540C5577F71178B68CC5D8545A5A05F7B96C408E7B39'},
    @{Name='good_ai.png';Sha='330658007E34522380AB46F13F9BC51935C72C5AFC973FEB8CB2C1BF595E8838'},
    @{Name='good_intro.png';Sha='989E7D9C845D0A601B4E4B66412993E25FD1DCF585BC5CEE01C73B6A7524097A'},
    @{Name='good_result.png';Sha='505231C0A3DE6E449AE46B72EDD98D4B198D81FDCAC634CF9ABB6E27F89AF765'},
    @{Name='limits.png';Sha='8A6B4386813BCCCFF9D209D44609B546B1BD4179EDD75AADFA8A35EDB316E2AC'},
    @{Name='ng_action.png';Sha='894B86F0B53EB47B6D84041809C5859ADCDAFBB6E0DC7C0D197E94B385EB72D7'},
    @{Name='ng_ai.png';Sha='CD2ED6434CEF6597871ED681D9925165A2474D35B707419C6609FCAC71266F9E'},
    @{Name='ng_intro.png';Sha='2145AC14C0B20920570A766F0549D736CFC33BE13CAEB80EB0051122F6F43CF7'},
    @{Name='ng_result.png';Sha='603771C132FCBD439AB9CAB5961D7BEBE079ED1E313F010F80ACD79D911C09FD'},
    @{Name='title.png';Sha='D9D622EFA31EE67A481741C83033A032492E72C773C87EFE90D60F5E12A7393D'}
)
function Assert-Exit([int]$Code,[string]$Where) {
    if($Code -ne 0){throw "${Where}_EXIT_$Code"}
}
function File-Sha([string]$File) {
    if(-not(Test-Path -LiteralPath $File -PathType Leaf)) {throw "FILE_NOT_FOUND:$File"}
    return (Get-FileHash -LiteralPath $File -Algorithm SHA256).Hash.ToUpperInvariant()
}
function Remote-Sha([string]$Path) {
    $lines=@(& docker exec --user ubuntu $container sha256sum $Path 2>&1)
    Assert-Exit $LASTEXITCODE 'REMOTE_SHA'
    if($lines.Count -ne 1){throw 'REMOTE_SHA_NUMBER_LINES'}
    $m=[regex]::Match([string]$lines[0],'^[0-9A-Fa-f]{64}(?=\s)')
    if(-not $m.Success){throw 'REMOTE_SHA_FORMAT_INVALID'}
    return $m.Value.ToUpperInvariant()
}
function Stage-Once([string]$Local,[string]$Remote,[string]$Expect) {
    if((File-Sha $Local) -cne $Expect){throw "SOURCE_HASH_INVALID:$Local"}
    & docker exec --user ubuntu $container test -f $Remote
    $rc=$LASTEXITCODE
    if($rc -eq 1) {
        & docker cp $Local "${container}:$Remote" | Out-Host
        Assert-Exit $LASTEXITCODE 'STAGE_COPY'
    }
    elseif($rc -ne 0){throw 'STAGE_REMOTE_CHECK_FAILED'}
    if((Remote-Sha $Remote) -cne $Expect){throw "REMOTE_HASH_CHANGED:$Remote"}
}
try {
    if(Test-Path -LiteralPath $target){throw 'FINAL_MOVIE_FOLDER_EXISTS_NO_OVERWRITE'}
    $running=@(& docker inspect --format '{{.State.Running}}' $container 2>&1)
    if($LASTEXITCODE -ne 0 -or $running.Count -ne 1 -or
        ([string]$running[0]).Trim() -cne 'true') {throw 'CONTAINER_NOT_RUNNING'}

    # A legacy GOOD fallback is explicitly available if the new stroke HOLDs.
    # It must never be represented as a 100 mm measured movement.
    if($AllowPriorGood) {
        $gVideo=Join-Path (Join-Path (Split-Path -Parent $PSScriptRoot) 'media') 'GOOD_previous_real_3mm.mp4'
        $gMotion=$null
        $gWitness=$null
        if((File-Sha $gVideo) -cne $expectedLegacyGood) {
            throw 'LEGACY_GOOD_R4_SOURCE_HASH_MISMATCH'
        }
        Write-Host 'GOOD_VIDEO_SELECTED=LEGACY_3_05453MM_EXPLICIT_FALLBACK'
    }
    else {
        # Verify that NEW GOOD actually moved in Gazebo and returned home.
        $goodW=@(Get-ChildItem -LiteralPath $downloads -Filter 'good_maxstroke_r1_*.witness.json' -File)
        if($goodW.Count -ne 1){throw 'NEED_EXACTLY_ONE_VERIFIED_NEW_GOOD_WITNESS'}
        $stem=$goodW[0].Name.Substring(0,$goodW[0].Name.Length-'.witness.json'.Length)
        $gVideo=Join-Path $downloads ($stem+'.mp4')
        $gMotion=Join-Path $downloads ($stem+'.motion.json')
        $gWitness=$goodW[0].FullName
        $good=Get-Content -LiteralPath $gWitness -Raw -Encoding UTF8 | ConvertFrom-Json
        if($good.mode -cne 'REAL_GAZEBO_SIMULATION_GOOD_R1' -or
           $good.joint_return_verified -ne $true -or
           $good.status -notin @('PASS_100MM_MEASURED','PASS_BOUNDED_MAX_MEASURED_BELOW_100MM') -or
           ([double]$good.peak_cube_dx_mm) -lt 5.0 -or
           ([double]$good.final_cube_dx_mm) -lt 5.0 -or
           (File-Sha $gVideo) -cne ([string]$good.video_sha256).ToUpperInvariant() -or
           (File-Sha $gMotion) -cne ([string]$good.motion_sha256).ToUpperInvariant()) {
            throw 'GOOD_R1_WITNESS_FAILED'
        }
        Write-Host 'GOOD_VIDEO_SELECTED=NEW_R1_MEASURED'
    }
    $nVideo=Join-Path $downloads ($ngStem+'.mp4')
    $nMotion=Join-Path $downloads ($ngStem+'.motion.json')
    $nWitness=Join-Path $downloads ($ngStem+'.witness.json')
    if((File-Sha $nVideo) -cne $expectedNgVideo -or
       (File-Sha $nMotion) -cne $expectedNgMotion -or
       (File-Sha $nWitness) -cne $expectedNgWitness) {throw 'NG_R2_EVIDENCE_HASH_MISMATCH'}
    $ai=Join-Path $downloads 'dual_ai_v4_defect_result.json'
    if((File-Sha $ai) -cne $expectedAiV4){throw 'V4_REAL_AI_REPORT_HASH_MISMATCH'}
    Write-Host 'STORY_REAL_INPUTS_VERIFIED=PASS'

    # Stage clean builder. Does not connect to any Gazebo API.
    & docker exec --user ubuntu $container test -e $stage
    $rc=$LASTEXITCODE
    if($rc -eq 0){throw 'STORY_STAGE_PREVIOUSLY_EXISTS_NO_OVERWRITE'}
    if($rc -ne 1){throw 'STORY_STAGE_CHECK_FAILED'}
    & docker exec --user ubuntu $container mkdir -m 700 $stage
    Assert-Exit $LASTEXITCODE 'STORY_MKDIR'
    & docker exec --user ubuntu $container mkdir -m 700 "$stage/cards"
    Assert-Exit $LASTEXITCODE 'CARDS_MKDIR'
    foreach($e in $items) {
        if($e.Name -eq 'make_story_videos.py') {
            $f=Join-Path $PSScriptRoot $e.Name
            $remote="$stage/$($e.Name)"
        }
        else {
            $f=Join-Path (Join-Path (Split-Path -Parent $PSScriptRoot) 'video_assets') $e.Name
            $remote="$stage/cards/$($e.Name)"
        }
        Stage-Once $f $remote ([string]$e.Sha).ToUpperInvariant()
    }
    $sources=@(
      @{Local=$gVideo;Dest='src_good.mp4'},
      @{Local=$nVideo;Dest='src_ng.mp4'},
      @{Local=$nMotion;Dest='src_ng.motion.json'},
      @{Local=$nWitness;Dest='src_ng.witness.json'})
    if(-not $AllowPriorGood) {
        $sources+=@(
          @{Local=$gMotion;Dest='src_good.motion.json'},
          @{Local=$gWitness;Dest='src_good.witness.json'})
    }
    foreach($entry in $sources) {
        $expected=File-Sha $entry.Local
        Stage-Once $entry.Local "$stage/$($entry.Dest)" $expected
    }
    Write-Host 'STORY_DOCKER_SOURCE_HASHES=PASS'
    $cmd=@('exec','--user','ubuntu',
      '-e','HOME=/home/ubuntu',$container,'python3','-B',"$stage/make_story_videos.py",
      '--good',"$stage/src_good.mp4",
      '--ng',"$stage/src_ng.mp4",'--ng-motion',"$stage/src_ng.motion.json",
      '--ng-witness',"$stage/src_ng.witness.json",
      '--cards',"$stage/cards",'--out',"$stage/output")
    if($AllowPriorGood) {
        $cmd+=@('--good-legacy')
    }
    else {
        $cmd+=@('--good-motion',"$stage/src_good.motion.json",'--good-witness',"$stage/src_good.witness.json")
    }
    $lines=@(& docker @cmd 2>&1)
    $rc=$LASTEXITCODE
    foreach($l in $lines){Write-Host ([string]$l)}
    if($rc -ne 0 -or $lines -notcontains 'STORY_VIDEO_BUILD_GATE=PASS_GENUINE_SOURCE_EVIDENCE_BOUND') {
        throw "STORY_EDIT_HOLD_EXIT_$rc"
    }
    & docker cp "${container}:$stage/output" $target | Out-Host
    Assert-Exit $LASTEXITCODE 'COPY_FINAL_OUTPUT_DIR'
    $manifest=Join-Path $target 'video_build_manifest.json'
    if(-not(Test-Path -LiteralPath $manifest -PathType Leaf)) {throw 'BUILD_MANIFEST_MISSING'}
    $doc=Get-Content -LiteralPath $manifest -Raw -Encoding UTF8 | ConvertFrom-Json
    if($doc.mode -cne 'EVIDENCE_LINKED_GENUINE_GAZEBO_STORY_EDIT' -or
       $doc.legacy_good_fallback -ne ([bool]$AllowPriorGood)) {throw 'MANIFEST_CONTENT_INVALID'}
    foreach($filename in @('GOOD_story.mp4','DEFECT_story.mp4','PAI_final_two_cases_story.mp4')) {
        $p=Join-Path $target $filename
        $entry=$doc.output.PSObject.Properties[$filename].Value
        if($null -eq $entry){throw "FINAL_MANIFEST_ENTRY_MISSING:$filename"}
        $expected=([string]$entry.sha256).ToUpperInvariant()
        if((File-Sha $p) -cne $expected) {throw "FINAL_MP4_HASH_MISMATCH:$filename"}
        $dur=[double]$entry.duration_sec
        if($dur -lt 60 -or $dur -gt 180){throw "FINAL_MP4_DURATION_INVALID:$filename"}
        Write-Host "STORY_FINAL_VIDEO=$p"
    }
    Write-Host 'STORY_BUILD_RESULT=PASS_THREE_VERIFIED_VIDEOS'
    Write-Host 'NO_ROBOT_COMMANDS_ISSUED_BY_EDITOR=True'
    exit 0
}
catch {
    Write-Host "STORY_BUILD_RESULT=HOLD; REASON=$($_.Exception.Message)"
    Write-Host 'NO_AUTOMATIC_VIDEO_RETRY=True'
    exit 3
}

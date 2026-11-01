#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Dual-AI Quality Guardian / submission video editor.

Author: Y.TOYODA
Version: 1.0 / 2026-11-02

[Purpose]
 Create (1) GOOD case, (2) DEFECT case, and (3) combined 1-3 min story.
 The originals remain unmodified. All robot movement comes only from the
 supplied genuine Gazebo screen recording; zoom and explanatory cards do not
 change or synthesize cube motion.

[Evidence policy]
 * GOOD long stroke: accept only validated R1 .witness.json and .motion.json.
 * DEFECT long stroke: accept only the pinned R2 files and measured values.
 * AI results on cards are prior actual responses; B67 GOOD was a separate
   acquisition. DEFECT V4 OpenAI REVIEW and Gemini DEFECT is not an AI vote.
 * No API calls, no Gazebo commands, no simulation resets, no model writes.
 * On invalid hashes or contradictory evidence: HOLD / no final videos.
"""
from __future__ import annotations
import argparse, hashlib, json, subprocess, tempfile, shutil, os
from pathlib import Path

NG_SHA='a64f3871dbd44a3c8e91256007c5a0855aef766e3109fe2cb20ccc4ecbade30d'
NG_WITNESS_SHA='837a1acd170906f262e1b2be70be81e9a2652fe1bb16f2ee535bf4f5da0f2a22'
NG_MOTION_SHA='1897a95c916ebf464ebae63b8613a9b2de6e18fb423e801adae31858ca79568e'
LEGACY_GOOD_SHA='8f7cdf82a2a17de9628e81d8e2f69064ceb12dffd8b25c35cc1865148fa69362'
W,H,FPS=1280,720,15

class Hold(RuntimeError):pass

def need(ok,msg):
    if not ok:raise Hold(msg)

def sha(path):
    need(path.is_file() and not path.is_symlink(),'MISSING_FILE:'+str(path))
    return hashlib.sha256(path.read_bytes()).hexdigest()

def call(argv,where,limit=180):
    p=subprocess.run(argv,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,
                     stderr=subprocess.PIPE,text=True,timeout=limit,check=False)
    if p.returncode:
        raise Hold(where+'_EXIT_'+str(p.returncode)+':'+p.stderr[-700:].replace('\n',' '))
    return p.stdout

def metadata(path,max_duration=90):
    data=json.loads(call(['ffprobe','-v','error','-select_streams','v:0',
           '-show_entries','stream=width,height,codec_name:format=duration',
           '-of','json',str(path)],'PROBE'))
    need(len(data['streams'])==1,'NOT_ONE_VIDEO_STREAM')
    s=data['streams'][0]
    need(s['codec_name']=='h264' and int(s['width'])>=640 and
         int(s['height'])>=480,'SOURCE_VIDEO_FORMAT_INVALID')
    dur=float(data['format']['duration'])
    need(16<=dur<=max_duration,'VIDEO_DURATION_UNEXPECTED')
    return dur

def evidence(args):
    good=Path(args.good);ng=Path(args.ng)
    goodsha=sha(good);ngsha=sha(ng)
    need(ngsha==NG_SHA,'PINNED_NG_R2_SOURCE_VIDEO_HASH_MISMATCH')
    need(sha(Path(args.ng_witness))==NG_WITNESS_SHA,'NG_R2_WITNESS_SHA_MISMATCH')
    need(sha(Path(args.ng_motion))==NG_MOTION_SHA,'NG_R2_MOTION_SHA_MISMATCH')
    ng_doc=json.loads(Path(args.ng_witness).read_text(encoding='utf8'))
    need(ng_doc.get('mode')=='SIM_ONLY_HUMAN_DEFECT_EXTENDED_MOVEMENT_R2_VIDEO' and
         ng_doc.get('status')=='PASS_BOUNDED_MAX_MEASURED_BELOW_100MM' and
         ng_doc.get('manual_override_demo') is True and
         ng_doc.get('v4_ai_fusion')=='REVIEW' and
         ng_doc.get('joint_return_verified') is True and
         ng_doc.get('no_model_pose_writes') is True and
         ng_doc.get('video_sha256')==ngsha and
         ng_doc.get('motion_sha256')==NG_MOTION_SHA,
         'NG_R2_WITNESS_CONTENT_MISMATCH')
    peak_ng=float(ng_doc['measured_peak_negative_x_mm'])
    final_ng=float(ng_doc['measured_final_x_mm'])
    need(-66.5<=peak_ng<=-65.0 and -19.0<=final_ng<=-17.0,
         'NG_R2_MEASURED_VALUES_NOT_EXPECTED')
    ng_motion=json.loads(Path(args.ng_motion).read_text(encoding='utf8'))
    need(abs(float(ng_motion['peak_cube_dx_mm'])-peak_ng)<.2 and
         abs(float(ng_motion['final_cube_dx_mm'])-final_ng)<.2 and
         ng_motion.get('joint_return_verified') is True,
         'NG_R2_MOTION_WITNESS_DISAGREES')
    if args.good_legacy:
        need(goodsha==LEGACY_GOOD_SHA,'LEGACY_GOOD_VIDEO_HASH_MISMATCH')
        gd={'peak_cube_dx_mm':3.05453,'final_cube_dx_mm':3.05453,
            'mode':'LEGACY_R4_0215','status':'GOOD_3MM_ONLY'}
    else:
        need(args.good_witness and args.good_motion,'GOOD_R1_EVIDENCE_REQUIRED')
        gd=json.loads(Path(args.good_witness).read_text(encoding='utf8'))
        goodmotion=json.loads(Path(args.good_motion).read_text(encoding='utf8'))
        need(gd.get('mode')=='REAL_GAZEBO_SIMULATION_GOOD_R1' and
             gd.get('status') in ('PASS_100MM_MEASURED','PASS_BOUNDED_MAX_MEASURED_BELOW_100MM') and
             gd.get('joint_return_verified') is True and
             gd.get('automatic_ai_actuation') is False and
             gd.get('video_sha256')==goodsha and
             gd.get('motion_sha256')==sha(Path(args.good_motion)),
             'GOOD_R1_WITNESS_CONTENT_MISMATCH')
        peak=float(gd['peak_cube_dx_mm']);final=float(gd['final_cube_dx_mm'])
        need(peak>=5 and final>=5 and peak>=final-.2,'GOOD_R1_MOVE_NOT_VERIFIED')
        need(abs(peak-float(goodmotion['peak_cube_dx_mm']))<.2 and
             abs(final-float(goodmotion['final_cube_dx_mm']))<.2 and
             goodmotion.get('joint_return_verified') is True,
             'GOOD_R1_MOTION_DISAGREES')
        if gd.get('status')=='PASS_100MM_MEASURED':
            need(peak>=100 and final>=100,'GOOD_R1_FALSE_100MM_PASS')
    return {'good':gd,'ng':ng_doc,'good_sha256':goodsha,'ng_sha256':ngsha,
            'ng_motion_sha256':NG_MOTION_SHA,
            'legacy_good':args.good_legacy}

def render_still(card,seconds,out):
    need(card.is_file(),'CARD_MISSING:'+card.name)
    call(['ffmpeg','-nostdin','-hide_banner','-loglevel','error','-y',
          '-loop','1','-framerate',str(FPS),'-i',str(card),
          '-t',str(seconds),'-vf','format=yuv420p',
          '-r',str(FPS),'-c:v','libx264','-preset','veryfast','-crf','23',
          '-pix_fmt','yuv420p','-an',str(out)],'STILL_SEGMENT',120)

def render_reality(source,seconds,out,label,peak,final,case,start_sec=0.0):
    # 2 parallel views from the SAME genuine MP4 frame; no image animation.
    # The zoom is restricted to the Gazebo 3D pane; no object position is edited.
    if case=='GOOD':
        cx,cy,cw,ch=160,250,290,400
    else:
        cx,cy,cw,ch=5,335,310,420
    result=('MEASURED PEAK  %+07.2f mm   FINAL  %+07.2f mm'%(peak,final))
    title=label+'  |  GAZEBO GENUINE PHYSICS'
    flt=(
     '[0:v]split=2[a][b];'
     '[a]scale=640:605:force_original_aspect_ratio=decrease,'
     'pad=640:605:(ow-iw)/2:(oh-ih)/2:0x202B3F[full];'
     '[b]crop=%d:%d:%d:%d,scale=545:605[zoom];'% (cw,ch,cx,cy) +
     'color=c=0x101B2E:s=1280x720:r=15:d=%s[bg];'%str(seconds)+
     '[bg][full]overlay=25:64[a1];[a1][zoom]overlay=705:64,'
     "drawtext=fontcolor=white:fontsize=21:x=32:y=19:text='%s',"%title+
     "drawtext=fontcolor=0xE9BC70:fontsize=23:x=32:y=685:text='%s'[v]"%result)
    call(['ffmpeg','-nostdin','-hide_banner','-loglevel','error','-y',
           '-ss',str(round(start_sec,3)),'-i',str(source),'-filter_complex',flt,'-map','[v]',
           '-t',str(seconds),'-r',str(FPS),'-c:v','libx264',
           '-preset','veryfast','-crf','23','-pix_fmt','yuv420p',
           '-an',str(out)],'GenuineVideoSegment',180)

def concat(parts,dest):
    # Same exact video parameters: H.264 / yuv420p / 1280x720 / 15fps.
    list_path=dest.parent/(dest.stem+'_concat.txt')
    with list_path.open('x',encoding='utf8') as f:
        for p in parts:
            f.write("file '%s'\n"%str(p).replace("'","'\\''"))
    call(['ffmpeg','-nostdin','-hide_banner','-loglevel','error','-y',
           '-f','concat','-safe','0','-i',str(list_path),
           '-c','copy','-movflags','+faststart','-an',str(dest)],
           'VIDEO_CONCAT',60)
    list_path.unlink()

def peak_time(path,kind):
    """Return elapsed seconds of greatest real cube displacement, never invent a time."""
    d=json.loads(Path(path).read_text(encoding='utf8'))
    values=[]
    for sample in d.get('samples',[]):
        if isinstance(sample,dict) and 'elapsed_s' in sample and 'cube_dx_mm' in sample:
            values.append((float(sample['elapsed_s']),float(sample['cube_dx_mm'])))
    need(bool(values),'MEASURED_TRAJECTORY_SAMPLES_MISSING')
    return (max if kind=='GOOD' else min)(values,key=lambda x:x[1])[0]

def make(args,ev):
    out=Path(args.out)
    need(not out.exists(),'OUTPUT_DIR_EXISTS_NO_OVERWRITE')
    out.mkdir(parents=True)
    tmp=out/'segments';tmp.mkdir()
    cards=Path(args.cards)
    good_src=Path(args.good);ng_src=Path(args.ng)
    good_dur=min(34,metadata(good_src));ng_dur=min(34,metadata(ng_src))
    good=ev['good'];ng=ev['ng']
    # An explicitly selected, fully disclosed fallback is not 100mm evidence.
    t_good=0.0 if ev['legacy_good'] else peak_time(args.good_motion,'GOOD')+2.0
    t_ng=peak_time(args.ng_motion,'DEFECT')+2.0
    good_start=min(max(0.0,t_good-good_dur/2),max(0.0,metadata(good_src)-good_dur))
    ng_start=min(max(0.0,t_ng-ng_dur/2),max(0.0,metadata(ng_src)-ng_dur))
    goods=[];ngs=[];all_parts=[]
    def add(part_list,prefix,tag,dur):
        p=tmp/(prefix+'_'+str(len(part_list)).zfill(2)+'.mp4')
        render_still(cards/(tag+'.png'),dur,p)
        part_list.append(p)
    for tag,secs in [('good_intro',5),('good_ai',10),('good_action',6)]:
        add(goods,'g',tag,secs)
    p=tmp/'g_genuine_motion.mp4'
    render_reality(good_src,good_dur,p,'GOOD / +X',float(good['peak_cube_dx_mm']),
                   float(good['final_cube_dx_mm']),'GOOD',good_start)
    goods.append(p)
    for tag,secs in [('good_result',9),('limits',7),('end',6)]:
        add(goods,'g',tag,secs)
    for tag,secs in [('ng_intro',5),('ng_ai',10),('ng_action',6)]:
        add(ngs,'n',tag,secs)
    p=tmp/'n_genuine_motion.mp4'
    render_reality(ng_src,ng_dur,p,'DEFECT / -X',float(ng['measured_peak_negative_x_mm']),
                   float(ng['measured_final_x_mm']),'DEFECT',ng_start)
    ngs.append(p)
    for tag,secs in [('ng_result',9),('limits',7),('end',6)]:
        add(ngs,'n',tag,secs)
    good_out=out/'GOOD_story.mp4';ng_out=out/'DEFECT_story.mp4'
    concat(goods,good_out);concat(ngs,ng_out)
    title=tmp/'combined_title.mp4';end=tmp/'combined_end.mp4'
    render_still(cards/'title.png',6,title)
    render_still(cards/'end.png',6,end)
    together=out/'PAI_final_two_cases_story.mp4'
    concat([title]+goods+ngs+[end],together)
    docs={'mode':'EVIDENCE_LINKED_GENUINE_GAZEBO_STORY_EDIT',
      'ai_good_b67':['GOOD','GOOD'],'ai_defect_v4':['REVIEW','DEFECT'],
      'automatic_ai_ng_motion':False,'robot_pose_writes':0,
      'good_measured_peak_mm':good['peak_cube_dx_mm'],
      'good_measured_final_mm':good['final_cube_dx_mm'],
      'defect_measured_peak_mm':ng['measured_peak_negative_x_mm'],
      'defect_measured_final_mm':ng['measured_final_x_mm'],
      'source_good_sha256':ev['good_sha256'],'source_ng_sha256':ev['ng_sha256'],
      'source_good_peak_time_s':t_good,'source_ng_peak_time_s':t_ng,
      'legacy_good_fallback':ev['legacy_good'],'output':{}}
    for video in (good_out,ng_out,together):
        docs['output'][video.name]={'sha256':sha(video),'duration_sec':metadata(video,185),
               'bytes':video.stat().st_size}
    need(60<=docs['output'][together.name]['duration_sec']<=180,
         'COMBINED_VIDEO_NOT_WITHIN_1_3_MIN')
    for p in (good_out,ng_out):
        need(60<=docs['output'][p.name]['duration_sec']<=180,
              'INDIVIDUAL_VIDEO_NOT_WITHIN_1_3_MIN:'+p.name)
    (out/'video_build_manifest.json').write_text(
          json.dumps(docs,ensure_ascii=False,sort_keys=True,indent=2)+'\n',encoding='utf8')
    shutil.rmtree(tmp)
    print('STORY_VIDEO_BUILD_GATE=PASS_GENUINE_SOURCE_EVIDENCE_BOUND',flush=True)
    for video in (good_out,ng_out,together):
        print('STORY_VIDEO_REMOTE='+str(video),flush=True)
        print('STORY_VIDEO_SHA256='+sha(video),flush=True)
        print('STORY_VIDEO_DURATION_SEC=%.3f'%docs['output'][video.name]['duration_sec'],flush=True)
    print('STORY_MANIFEST_REMOTE='+str(out/'video_build_manifest.json'),flush=True)

def main():
    ap=argparse.ArgumentParser(allow_abbrev=False)
    ap.add_argument('--good',required=True);ap.add_argument('--ng',required=True)
    ap.add_argument('--ng-witness',required=True);ap.add_argument('--ng-motion',required=True)
    ap.add_argument('--good-witness');ap.add_argument('--good-motion')
    ap.add_argument('--good-legacy',action='store_true')
    ap.add_argument('--cards',required=True);ap.add_argument('--out',required=True)
    args=ap.parse_args()
    need(shutil.which('ffmpeg') is not None and shutil.which('ffprobe') is not None,
         'FFMPEG_FFPROBE_REQUIRED')
    ev=evidence(args);make(args,ev)

if __name__=='__main__':
    try:main()
    except (Exception,KeyboardInterrupt) as exc:
        print('STORY_VIDEO_BUILD_GATE=HOLD; REASON='+type(exc).__name__+':'+str(exc)[:900],flush=True)
        raise SystemExit(3)

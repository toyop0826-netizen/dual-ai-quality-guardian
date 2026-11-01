#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Dual-AI Quality Guardian - GOOD側・実物理シミュレーション移動試験.

Author: Y.TOYODA
Version: 1.0 / 2026-11-02

【目的】50mmのGOODキューブをGazebo物理計算で+X方向へ最大100mm押す。
【構成】既存のGOOD録画シーンを保全し、関節1だけを小刻みに指令する。
【守ること】実機操作なし。キューブ座標の直接書換えなし。AI再実行なし。
【状態管理】初回preflightは読み取り専用。recordは明示承認付き・1回だけ。
【成功判定】実測のキューブ変位と関節の原点復帰が一致する場合のみPASS。
【制約】静的OBB監査は動的衝突の完全な証明ではない。
"""
from __future__ import annotations
import argparse, hashlib, importlib.util, json, math, os, re, shlex
import subprocess, sys, tempfile, threading, time
from pathlib import Path
from datetime import datetime, timezone

BASE=Path('/home/ubuntu/pai_demo')
WORK=BASE/'pai_good_maxstroke_r1'
PART='pai_record_scene_wood_v1_20261101'
CAP=BASE/'pai_record_capture_v1'
SRC=CAP/'pai_record_capture_r4.py'
SRC_SHA='a479b3e677cc062ac3dd45b67bd2f0080714854379c18223afec3670ca074e4a'
MESH=CAP/'pai_v6_precontact_mesh_audit.py'
MESH_SHA='74ab17bf56b8f691bd73156dadc908ca72dbfcdc9fb28e7459c4ac77a0e52d9d'
V6=BASE/'pai_native_j1_pusher_20261101_v6'
V6_HELPER=V6/'pai_v6_preflight.py'
V6_HELPER_SHA='e92e0300f06cdef1fa432252e5582c58f39121dd45bda39ea44e560e5d743c47'
WORLD=V6/'world_native_j1_v6.sdf'
WORLD_SHA='0176b44ef8cb10d515d9824523730082eadd9fec4dae1e0b2c5e27fd2cd97a54'
PRIOR=CAP/'record_gazebo_r4_20261101T140110Z_1793541670875307375.witness.json'
PRIOR_VIDEO=CAP/'record_gazebo_r4_20261101T140110Z_1793541670875307375.mp4'
PRIOR_VIDEO_SHA='8f7cdf82a2a17de9628e81d8e2f69064ceb12dffd8b25c35cc1865148fa69362'
OBSERVER=WORK/'pai_good_pose_stream.cc'
DRIVER=WORK/'pai_good_guarded_driver.cc'
AUTH='AUTHORIZE_SIMULATED_GOOD_POSITIVE_J1_R1_ONCE'
TARGET_MM=100.0
MAX_ANGLE=1.20
GRID=0.010
STEP=0.025
DWELL=0.55
EXPECTED_START=(0.00305453,-0.100,1.015)
EXPECTED_J1=-1.571170863

class Hold(RuntimeError):
    """HOLD=未確認状態をPASSと扱わないための明示的な停止。"""

def need(cond,why):
    if not cond:raise Hold(why)

def digest(p):
    need(p.is_file() and not p.is_symlink(),'FILE_NOT_REGULAR:'+p.name)
    return hashlib.sha256(p.read_bytes()).hexdigest()

def pinned(p,expected,label):
    need(digest(p)==expected,label+'_SHA256_MISMATCH')

def load(p,name):
    spec=importlib.util.spec_from_file_location(name,str(p))
    need(spec and spec.loader,'PYTHON_MODULE_LOAD_FAILED:'+name)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    return m

def run(args,timeout=12):
    p=subprocess.run(args,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,
                     stderr=subprocess.PIPE,text=True,timeout=timeout,check=False)
    return p

def save_once(path,doc):
    data=(json.dumps(doc,ensure_ascii=False,indent=2,sort_keys=True,allow_nan=False)+'\n').encode('utf8')
    with path.open('xb') as f:f.write(data);f.flush();os.fsync(f.fileno())
    need(path.read_bytes()==data,'EVIDENCE_READBACK_FAILED')
    return hashlib.sha256(data).hexdigest()

class PoseFeed:
    """Gazebo位置の継続購読。古い/壊れたフレームは安全な計測として使わない。"""
    def __init__(self,exe,log):
        self.fp=log.open('xb')
        self.proc=subprocess.Popen([str(exe)],stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,
                   stderr=self.fp,text=True,bufsize=1,start_new_session=True,close_fds=True)
        self.cond=threading.Condition();self.seq=0;self.used=0;self.last=None
        self.last_at=0.0;self.failure=None;self.invalid=0
        self.thread=threading.Thread(target=self._reader,daemon=True);self.thread.start()
    def _reader(self):
        try:
            for line in self.proc.stdout:
                parts=line.split()
                if len(parts)!=9 or parts[0]!='POSE':
                    with self.cond:self.invalid+=1
                    continue
                try:
                    seq=int(parts[1]);x=tuple(map(float,parts[2:]))
                    need(seq>0 and len(x)==7 and all(map(math.isfinite,x)), 'BAD_FRAME')
                    need(max(abs(a) for a in x)<20,'POSITION_OUT_OF_BOUNDS')
                except (Hold,ValueError,OverflowError):
                    with self.cond:self.invalid+=1
                    continue
                with self.cond:
                    if seq<=self.seq:
                        self.failure='NON_MONOTONIC_SEQUENCE';self.cond.notify_all();return
                    self.seq=seq;self.last=(x[0:3],x[3:6],x[6])
                    self.last_at=time.monotonic();self.cond.notify_all()
        except (OSError,UnicodeError):
            with self.cond:self.failure='STREAM_READER_ERROR';self.cond.notify_all()
        with self.cond:
            if not self.failure:self.failure='STREAM_EOF'
            self.cond.notify_all()
    def snapshot(self):
        end=time.monotonic()+0.75
        with self.cond:
            while self.seq<=self.used and not self.failure:
                left=end-time.monotonic()
                if left<=0:break
                self.cond.wait(left)
            need(not self.failure,'POSE_STREAM_'+str(self.failure))
            need(self.seq>self.used,'POSE_STREAM_NO_NEW_FRAME')
            need(time.monotonic()-self.last_at<0.4,'POSE_STREAM_STALE')
            self.used=self.seq
            return self.last
    def __enter__(self):return self
    def __exit__(self,*_):self.close()
    def close(self):
        if self.proc.poll() is None:
            self.proc.terminate()  # terminate only our read-only observer
            try:self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:self.proc.kill();self.proc.wait(timeout=3)
        self.thread.join(timeout=2);self.fp.close()

def compile_cpp(folder,file,exe):
    flags=run(['pkg-config','--cflags','--libs','ignition-transport11','ignition-msgs8'],8)
    need(flags.returncode==0,'IGNITION_CPP_DEV_LIBRARIES_MISSING')
    cmd=['c++','-std=c++17','-O1','-Wall','-Wextra',str(file),'-o',str(exe)]
    p=run(cmd+shlex.split(flags.stdout),90)
    if p.returncode:print('GOOD_COMPILE_DIAG='+p.stderr[-600:].replace('\n',' '),flush=True)
    need(p.returncode==0 and exe.is_file(),'CPP_COMPILE_FAIL:'+file.name)
    return exe

def assert_publisher_free(r4,v):
    r4.verify_no_command_publisher(v) # Reject other joint1 controller publishers.

def static_audit(m,current_x):
    """STL/OBBによる保守的な全経路監査。GOODの意図した接触のみ除外。"""
    need(m.WORLD_SHA256==WORLD_SHA,'MESH_WORLD_REFERENCE_CHANGED')
    scene=m.scene_load(m.WORLD)
    crane,_,tables,meshes,pushers,_=scene
    mp=m.pose(crane)
    good_link,good_collision=pushers['OK']
    p0=m.push_obb(mp,0,good_link,good_collision)[0]
    last_safe=0.0;first_conflict=None;rows=[]
    for i in range(1,int(MAX_ANGLE/GRID)+1):
        q=round(i*GRID,6)
        margin=1e5;worst=''
        def compare(name,box):
            nonlocal margin,worst
            safety=m.angular_motion_margin(box,step=GRID)+.0015
            for tname,tbox in tables:
                d=m.sat_gap(box,tbox)-safety
                if d<margin:margin=d;worst=name+' vs table '+tname
        movable=[]
        for name,link,col,bounds in meshes:
            if name=='base_link':continue
            box=m.mesh_obb(mp,q,link,col,bounds);movable.append((name,box))
            compare('ARM:'+name,box)
        for name,(link,col) in pushers.items():
            compare('PUSHER:'+name,m.push_obb(mp,q,link,col))
        goodp=m.push_obb(mp,q,good_link,good_collision)[0]
        proposed_x=max(current_x,goodp[0]+.0285)
        proposed_y=-.100+(goodp[1]-p0[1])
        cube=m.obb((proposed_x,proposed_y,1.040,0,0,0),size=(.050,.050,.050))
        other_l,other_c=pushers['NG']
        other=m.push_obb(mp,q,other_l,other_c)
        d=m.sat_gap(other,cube)-.002
        if d<margin:margin=d;worst='NG_PUSHER vs projected GOOD cube'
        for name,box in movable:
            d=m.sat_gap(box,cube)-.003
            if d<margin:margin=d;worst='ARM:'+name+' vs projected GOOD cube'
        rows.append({'q_rad':q,'predicted_pusher_dx_mm':round((goodp[0]-p0[0])*1000,2),
             'nominal_cube_x_mm':round((proposed_x-current_x)*1000,2),
             'min_conservative_clearance_mm':round(margin*1000,3),'pair':worst})
        if margin<=0:
            first_conflict={'angle':q,'pair':worst,'clearance_mm':round(margin*1000,3)}
            break
        last_safe=q
    cap=math.floor((last_safe-.01+1e-9)/STEP)*STEP
    cap=round(max(0.,min(MAX_ANGLE,cap)),4)
    doc={'mode':'STATIC_GOOD_EXTENDED_OBB_AUDIT_NO_MOTION',
      'original_world_sha256':WORLD_SHA,'target_x_mm':TARGET_MM,
      'conservative_cap_rad':cap,'first_possible_unintended_conflict':first_conflict,
      'samples':rows,'limitations':['Nominal cube path is not a validated dynamic contact path.',
      'Other robot joints are held fixed; this audit does not prove global reach.',
      'Maximum 100mm is a requested target and must be actually measured.']}
    need(cap>=.250,'GOOD_STATIC_AUDIT_CAP_TOO_SMALL')
    print('GOOD_STATIC_AUDIT_CAP_RAD=%.4f'%cap,flush=True)
    print('GOOD_STATIC_AUDIT_NOT_DYNAMIC_CERTIFICATE=True',flush=True)
    return cap,doc

def verify_good_initial(feed,prior):
    samples=[feed.snapshot() for _ in range(4)]
    c,b,q=samples[-1]
    expected=tuple(float(a) for a in EXPECTED_START)
    # Prior R4 reported +3.05453 mm; small drift is allowed but not a reset.
    need(math.dist(c,expected)<.0030,'GOOD_CUBE_POSITION_DIFFERS_FROM_R4_WITNESS')
    need(math.dist(b,(0.,0.,1.015))<.0030,'GOOD_ROBOT_BASE_CHANGED')
    need(abs(math.remainder(q-EXPECTED_J1,math.tau))<.012,'GOOD_J1_NOT_HOME')
    need(math.dist(samples[0][0],c)<.001,'GOOD_CUBE_NOT_SETTLED')
    need(abs(math.remainder(samples[0][2]-q,math.tau))<.004,'GOOD_J1_NOT_SETTLED')
    print('GOOD_INITIAL_CUBE_M='+','.join('%.6f'%a for a in c),flush=True)
    print('GOOD_J1_HOME_VERIFIED=PASS_READONLY',flush=True)
    return c,b,q

def assert_snapshot(s,ref,cmd,t0,cap):
    c,b,q=s;dx=(c[0]-ref[0][0])*1000;dy=(c[1]-ref[0][1])*1000
    dz=(c[2]-ref[0][2])*1000;db=math.dist(b,ref[1])*1000
    a=math.remainder(q-ref[2],math.tau)
    row={'elapsed_s':round(time.monotonic()-t0,3),'j1_rad':round(a,6),
      'j1_command_rad':round(cmd,5),'cube_dx_mm':round(dx,4),
      'cube_dy_mm':round(dy,4),'cube_dz_mm':round(dz,4),
      'robot_base_dx_mm':round(db,4)}
    need(-2.0<=dx<=125.0,'GOOD_X_POSITION_OUTSIDE_LIMIT')
    need(abs(dy)<55,'GOOD_Y_DRIFT_LIMIT')
    need(abs(dz)<6,'GOOD_Z_LIFT_OR_SINK')
    need(db<2,'GOOD_ROBOT_BASE_MOVED')
    need(-.04<=a<=cap+.040,'GOOD_J1_BEYOND_STATIC_CAP')
    if cmd>0.0:need(a<=cmd+.050,'GOOD_J1_OVERSHOOT_CMD')
    return row

def send(driver,message):
    need(driver.poll() is None and driver.stdin is not None and not driver.stdin.closed,
         'GOOD_DRIVER_NOT_RUNNING')
    driver.stdin.write(message+'\n');driver.stdin.flush()

def perform_motion(feed,driver_exe,ref,cap,report):
    """唯一の関節指令箇所。各STEPの測定を保持し、例外時もゼロを試行する。"""
    proc=None;outcome='HOLD';error='';peak=0.0;recent=[]
    returned=False;begun=time.monotonic();command=0.0
    try:
        proc=subprocess.Popen([str(driver_exe)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
          stderr=subprocess.PIPE,text=True,bufsize=1,start_new_session=True,close_fds=True)
        time.sleep(.8)
        need(proc.poll() is None,'GOOD_DRIVER_EARLY_EXIT')
        count=int(math.floor((cap+1e-8)/STEP))
        for i in range(1,count+1):
            command=round(i*STEP,5)
            need(command<=cap+1e-8,'GOOD_COMMAND_EXCEEDS_STATIC_CAP')
            send(proc,'GO %.5f'%command)
            report['steps_sent'].append(command)
            stop=time.monotonic()+DWELL
            while time.monotonic()<stop:
                send(proc,'HB');row=assert_snapshot(feed.snapshot(),ref,command,begun,cap)
                report['samples'].append(row)
                peak=max(peak,row['cube_dx_mm'])
                if peak>=TARGET_MM:
                    outcome='TARGET_100MM_PEAK_SEEN';break
                time.sleep(.1)
            print('GOOD_STROKE_STEP=%.3f CUBE_DX_MM=%.3f PEAK_DX_MM=%.3f'%(
              command,row['cube_dx_mm'],peak),flush=True)
            recent.append(peak)
            if outcome!='HOLD':break
            if command>=.55 and peak<6.0:
                outcome='STOP_LOW_CONTACT_EFFECT';break
            if command>=.65 and len(recent)>=9 and recent[-1]-recent[-9]<1.2:
                outcome='STOP_NO_ADDITIONAL_CUBE_PROGRESS';break
        if outcome=='HOLD':outcome='STOP_CONSERVATIVE_AUDIT_CAP'
    except (Exception,KeyboardInterrupt) as ex:
        error=type(ex).__name__+':'+str(ex)[:400]
        outcome='HOLD_EMERGENCY_ZERO'
        print('GOOD_STROKE_EARLY_HOLD='+error,flush=True)
    finally:
        if proc is not None:
            try:
                if proc.poll() is None:send(proc,'RETURN')
            except (OSError,Hold) as ex:error+=';RETURN_'+type(ex).__name__
            # Do not equate a published return command with a measured home pose.
            for _ in range(100):
                try:
                    row=assert_snapshot(feed.snapshot(),ref,0.0,begun,cap)
                    report['samples'].append(row)
                    if abs(row['j1_rad'])<.012:
                        returned=True;break
                except Exception as ex:
                    error+=';RETURN_TELEMETRY_'+type(ex).__name__;break
                try:
                    if proc.poll() is None:send(proc,'HB')
                except Exception:break
                time.sleep(.08)
            try:
                if proc.poll() is None:send(proc,'EXIT' if returned else 'ABORT')
            except Exception:pass
            try:
                output,stderr=proc.communicate(timeout=8)
                report['driver_output']=output[-5000:]
                report['driver_stderr']=stderr[-900:]
            except subprocess.TimeoutExpired:
                error+=';DRIVER_DID_NOT_EXIT'
                print('OPERATOR_ACTION=PAUSE_SIMULATION_MANUALLY',flush=True)
    report['driver_exit']=None if proc is None else proc.poll()
    report['peak_cube_dx_mm']=peak
    report['stop_reason']=outcome;report['motion_error']=error
    report['joint_return_verified']=returned
    try:
        last=assert_snapshot(feed.snapshot(),ref,0.0,begun,cap)
        report['final_sample']=last
        report['final_cube_dx_mm']=last['cube_dx_mm']
        returned=returned and abs(last['j1_rad'])<.012
    except Exception as ex:
        error+=';FINAL_TELEMETRY_'+type(ex).__name__
        returned=False
    report['joint_return_verified']=returned
    report['motion_error']=error
    measured=max((v['j1_rad'] for v in report['samples']),default=0.0)
    report['measured_peak_j1_rad']=measured
    required=min(.165,max(report['steps_sent'],default=0)-.12)
    report['required_measured_peak_j1_rad']=required
    status='HOLD'
    if (returned and report['driver_exit']==0 and not error and
        measured>=required and peak>=5.0 and report.get('final_cube_dx_mm',0)>=5.0):
        if peak>=TARGET_MM and report['final_cube_dx_mm']>=TARGET_MM:
            status='PASS_100MM_MEASURED'
        else:
            status='PASS_BOUNDED_MAX_MEASURED_BELOW_100MM'
    report['motion_status']=status
    return status

def verify_frozen():
    need(Path('/.dockerenv').is_file() and os.geteuid()==1000,'UBUNTU_DOCKER_ONLY')
    need(os.environ.get('HOME')=='/home/ubuntu','HOME_UNEXPECTED')
    need(os.environ.get('DISPLAY')==':0','DISPLAY_UNEXPECTED')
    need(os.environ.get('IGN_PARTITION')==PART,'GOOD_PARTITION_NOT_MATCHING')
    need(WORK.is_dir() and not WORK.is_symlink(),'GOOD_STAGE_ABSENT')
    pinned(SRC,SRC_SHA,'FROZEN_GOOD_RECORDER')
    pinned(MESH,MESH_SHA,'FROZEN_MESH_AUDITOR')
    pinned(V6_HELPER,V6_HELPER_SHA,'FROZEN_V6_HELPER')
    pinned(WORLD,WORLD_SHA,'FROZEN_V6_WORLD')
    pinned(PRIOR_VIDEO,PRIOR_VIDEO_SHA,'PRIOR_REAL_GOOD_VIDEO')
    need(PRIOR.is_file() and not PRIOR.is_symlink(),'PRIOR_GOOD_WITNESS_ABSENT')
    w=json.loads(PRIOR.read_text(encoding='utf8'))
    need(w.get('video_sha256')==PRIOR_VIDEO_SHA and
         w.get('status')=='PASS_RECORDING_AND_MEASURED_PUSH' and
         w.get('record_partition')==PART and
         abs(float(w.get('cube_dx_mm',-10))-3.05453)<0.30 and
         w.get('robot_hardware_used') is False,'PRIOR_GOOD_WITNESS_CONTENT_INVALID')
    # Real process ownership checks are inherited from the proven R4 recorder.
    rec=load(SRC,'frozen_record_owner')
    gui_pid=rec.guard();win,_=rec.video_window(gui_pid)
    r4=load(CAP/'pai_v6_r4_cube_push_0215.py','frozen_r4_publisher_gate')
    sys.path.insert(0,str(V6));v=load(V6_HELPER,'frozen_v6_pose_reader')
    r4.verify_no_command_publisher(v)
    m=load(MESH,'frozen_static_mesh_checker')
    need(m.WORLD_SHA256==WORLD_SHA,'STATIC_REFERENCE_WORLD_CHANGED')
    return win,v,m

def preflight(feed,win,v,m):
    ref=verify_good_initial(feed,None)
    cap,audit=static_audit(m,ref[0][0])
    return ref,cap,audit

def capture_record(feed,win,ref,cap,audit):
    lock=WORK/'good_one_shot_intent.json'
    need(not lock.exists(),'GOOD_STROKE_PREVIOUS_ATTEMPT_EXISTS_NO_RETRY')
    for name in ('ffmpeg','ffprobe'):
        need(run(['which',name],3).returncode==0,'MISSING_EXECUTABLE:'+name)
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+str(time.time_ns())
    stem='good_maxstroke_r1_'+stamp
    movie=WORK/(stem+'.mp4');motion=WORK/(stem+'.motion.json')
    witness=WORK/(stem+'.witness.json');stderr=WORK/(stem+'.ffmpeg.log')
    report={'mode':'SIMULATION_ONLY_MANUAL_GOOD_POSITIVE_X_R1',
         'target_x_mm':100.,'ai_good_reference':'B67_OPENAI_GOOD_GEMINI_GOOD',
         'automatic_ai_actuation':False,'model_pose_writes':0,
         'original_world_sha256':WORLD_SHA,'source_prior_video_sha256':PRIOR_VIDEO_SHA,
         'start_cube_m':list(ref[0]),'cap_rad':cap,'static_audit':audit,
         'steps_sent':[],'samples':[],'motion_status':'HOLD'}
    with tempfile.TemporaryDirectory(prefix='good_driver_r1_',dir='/tmp') as td:
        exe=compile_cpp(Path(td),DRIVER,Path(td)/'good_driver')
        cmd=['ffmpeg','-nostdin','-hide_banner','-loglevel','warning',
            '-f','x11grab','-framerate','15','-window_id',win,
            '-i',':0.0','-t','58','-vf','pad=ceil(iw/2)*2:ceil(ih/2)*2',
            '-c:v','libx264','-preset','ultrafast','-crf','22',
            '-pix_fmt','yuv420p','-movflags','+faststart','-n',str(movie)]
        with stderr.open('xb') as error_fp:
            ff=subprocess.Popen(cmd,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,
                     stderr=error_fp,start_new_session=True,close_fds=True)
            status='HOLD';err=''
            try:
                time.sleep(2)
                need(ff.poll() is None,'GOOD_RECORDER_NOT_RUNNING')
                save_once(lock,{'timestamp':stamp,'mode':'SIM_ONLY_ONE_SHOT','movie':str(movie)})
                print('GOOD_ONE_SHOT_INTENT_SAVED=True',flush=True)
                status=perform_motion(feed,exe,ref,cap,report)
                try:ff.wait(timeout=62)
                except subprocess.TimeoutExpired:raise Hold('GOOD_RECORDER_TIMEOUT')
            finally:
                if ff.poll() is None:
                    ff.terminate()
                    try:ff.wait(timeout=5)
                    except subprocess.TimeoutExpired:ff.kill();ff.wait(timeout=5)
        print('GOOD_FFMPEG_EXIT='+str(ff.returncode),flush=True)
    if movie.is_file():
        report['video_path']=str(movie);report['video_sha256']=digest(movie)
        print('GOOD_VIDEO_REMOTE='+str(movie),flush=True)
        print('GOOD_VIDEO_SHA256='+report['video_sha256'],flush=True)
    report['record_exit']=ff.returncode
    report['observer_status']='POSE_STREAM_CONTINUOUS_READONLY'
    rsha=save_once(motion,report)
    print('GOOD_MOTION_REMOTE='+str(motion),flush=True)
    print('GOOD_MOTION_SHA256='+rsha,flush=True)
    need(status.startswith('PASS_'),'GOOD_SIM_MOTION_HELD_EVIDENCE_SAVED_NO_RETRY')
    need(ff.returncode==0 and movie.stat().st_size>50000,'GOOD_VIDEO_NOT_CAPTURED')
    vmeta=run(['ffprobe','-v','error','-show_entries',
               'stream=width,height,codec_name:format=duration','-of','json',str(movie)],18)
    need(vmeta.returncode==0,'GOOD_FFPROBE_FAILED')
    metadata=json.loads(vmeta.stdout)
    length=float(metadata['format']['duration'])
    need(52<=length<=60,'GOOD_VIDEO_DURATION_UNEXPECTED')
    doc={'mode':'REAL_GAZEBO_SIMULATION_GOOD_R1','status':status,
         'peak_cube_dx_mm':report['peak_cube_dx_mm'],
         'final_cube_dx_mm':report['final_cube_dx_mm'],
         'joint_return_verified':report['joint_return_verified'],
         'manual_demonstration':True,'automatic_ai_actuation':False,
         'video_sha256':report['video_sha256'],'video_path':str(movie),
         'motion_sha256':rsha,'motion_path':str(motion),'video_metadata':metadata,
         'limitations':['Only joint1 push. No autonomous pick and place or bin drop.',
                        'Static proxy audit does not establish dynamic collision safety.']}
    wsha=save_once(witness,doc)
    print('GOOD_WITNESS_REMOTE='+str(witness),flush=True)
    print('GOOD_WITNESS_SHA256='+wsha,flush=True)
    print('GOOD_PEAK_CUBE_DX_MM=%.4f'%report['peak_cube_dx_mm'],flush=True)
    print('GOOD_FINAL_CUBE_DX_MM=%.4f'%report['final_cube_dx_mm'],flush=True)
    print('GOOD_GATE='+status,flush=True)
    return 0

def selftest():
    """純粋関数と禁止操作の固定値確認。ネットワーク・Gazebo接続なし。"""
    import ast
    source=Path(__file__).read_text(encoding='utf8')
    ast.parse(source)
    c=DRIVER.read_text(encoding='utf8') if DRIVER.is_file() else ''
    p=OBSERVER.read_text(encoding='utf8') if OBSERVER.is_file() else ''
    need('q<=0.0||q>1.200001' in c,'POSITIVE_COMMAND_GUARD_MISSING')
    need('Subscribe("/world/default/pose/info"' in p,'POSE_SUBSCRIBER_MISSING')
    need('Advertise<' not in p and 'Publish(' not in p,'POSE_OBSERVER_WRITES_FORBIDDEN')
    need('model_pose_writes\':0' in source,'SIM_POSE_WRITE_AUDIT_MISSING')
    need('.025' in source and 'TARGET_MM=100.0' in source,'TARGET_BOUNDS_CHANGED')
    need('Y.TOYODA' in source,'AUTHOR_COMMENT_MISSING')
    print('GOOD_R1_SELFTEST=PASS_OFFLINE_NO_NETWORK_NO_MOTION',flush=True)

def main():
    pa=argparse.ArgumentParser(allow_abbrev=False)
    pa.add_argument('--action',choices=('selftest','preflight','record'),required=True)
    pa.add_argument('--authorization',default='')
    args=pa.parse_args()
    need((args.action=='record' and args.authorization==AUTH) or
         (args.action!='record' and args.authorization==''),'EXPLICIT_SIM_ONLY_AUTH_TOKEN_INVALID')
    if args.action=='selftest':selftest();return 0
    win,v,m=verify_frozen()
    need(not (WORK/'good_one_shot_intent.json').exists(),
         'GOOD_STROKE_PREVIOUS_ATTEMPT_EXISTS_NO_RETRY')
    with tempfile.TemporaryDirectory(prefix='good_pose_stream_',dir='/tmp') as td:
        obs=compile_cpp(Path(td),OBSERVER,Path(td)/'pose_observer')
        with PoseFeed(obs,WORK/('good_pose_'+str(os.getpid())+'.stderr')) as feed:
            ref,cap,audit=preflight(feed,win,v,m)
            if args.action=='preflight':
                path=WORK/'good_preflight_observed_static_audit.json'
                if path.exists():
                    need(json.loads(path.read_text())==audit,'PREVIOUS_PREFLIGHT_DIFFERS')
                else:save_once(path,audit)
                print('GOOD_R1_PREFLIGHT=PASS_READONLY_GOOD_HOME_AND_STATIC_AUDIT',flush=True)
                print('ROBOT_COMMANDS_SENT=0',flush=True)
                return 0
            return capture_record(feed,win,ref,cap,audit)

if __name__=='__main__':
    try:sys.exit(main())
    except (Exception,KeyboardInterrupt) as e:
        print('GOOD_R1_GATE=HOLD',flush=True)
        print('GOOD_R1_HOLD_REASON='+type(e).__name__+':'+str(e)[:400],flush=True)
        print('NO_AUTOMATIC_MOTION_RETRY=True',flush=True)
        sys.exit(3)

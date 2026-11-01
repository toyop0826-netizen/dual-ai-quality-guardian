#!/usr/bin/env python3
"""R2 guarded simulation-only long-stroke recording, continuous Pose_V telemetry.

Read-only preflight is mandatory. --action record may publish J1 commands only
if the V1 hold evidence, current HOME state and live stream are verified.
No scene/model writes, AI calls, resets, or hardware commands.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone

BASE=Path('/home/ubuntu/pai_demo')
WORK=BASE/'pai_ng_maxstroke_r2'
FROZEN_V1=BASE/'pai_ng_maxstroke_v1/pai_ng_maxstroke_v1.py'
FROZEN_V1_SHA='e79fa76eb563e3058ff0c28b4c88fcca6db80be5bba3b7831d7fb587161799f2'
V1_REPORT=BASE/'pai_ng_maxstroke_v1/ng_maxstroke_20261101T162629Z_1793550389624949571.motion.json'
V1_REPORT_SHA='d51d0227929b2c3e06043b95d384350a7f95504cc42aa8360fe3bf3176dd49ae'
OBSERVER_SOURCE=WORK/'pai_ng_pose_stream_r2.cc'
OBSERVER_SHA='3c9c7b4af180cde794329ebdbc4ac328b269864cca596f9602d334a5f2bdec93'
AUTH='AUTHORIZE_SIM_ONLY_GUARDED_R2_MAX_STROKE_ONE_SHOT'

class Hold(RuntimeError):pass

def need(x,label):
    if not x:raise Hold(label)

def hash_file(path):
    need(path.is_file() and not path.is_symlink(),'SOURCE_FILE_NOT_REGULAR:'+path.name)
    return hashlib.sha256(path.read_bytes()).hexdigest()

def verify_hash(path,expected,label):
    need(hash_file(path)==expected,label+'_SHA256_MISMATCH')

def frozen_load(path,name):
    spec=importlib.util.spec_from_file_location(name,str(path))
    need(spec is not None and spec.loader is not None,'IMPORT_SPEC_FAILED')
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

def v1_report():
    verify_hash(V1_REPORT,V1_REPORT_SHA,'FROZEN_V1_HOLD_REPORT')
    r=json.loads(V1_REPORT.read_text(encoding='utf8'))
    need(r['mode']=='SIMULATED_GUARDED_EXTENDED_J1_PUSH_HUMAN_DEFECT',
         'V1_REPORT_MODE_UNEXPECTED')
    need(r.get('motion_status')=='HOLD' and
         r.get('stop_reason')=='HOLD_EMERGENCY_RETURN' and
         'MULTIPLE_POSE_V_HEADERS' in r.get('motion_error','') and
         r.get('model_pose_writes')==0 and
         r.get('automatic_ai_actuation') is False,
         'V1_HOLD_REPORT_NOT_EXPECTED_FAILURE')
    steps=r.get('steps_sent',[])
    need(isinstance(steps,list) and 2<=len(steps)<=4 and
         all(-0.101<=float(q)<=-0.024 for q in steps),
         'V1_HOLD_STEPS_UNEXPECTED')
    print('R2_PRIOR_HOLD_REPORT_SHA256=PASS',flush=True)
    print('R2_PRIOR_HOLD_REASON=TRANSIENT_POSE_V_MULTI_HEADER',flush=True)
    print('R2_PRIOR_DRIVER_EXIT='+str(r.get('driver_exit','UNAVAILABLE')),flush=True)
    print('R2_PRIOR_RETURN_VERIFIED='+str(bool(r.get('joint_return_verified'))),flush=True)
    print('R2_PRIOR_RECORDED_STEPS='+','.join('%.3f'%float(q) for q in steps),flush=True)
    print('R2_PRIOR_BOUNDED_PEAK_DX_MM='+str(r.get('peak_cube_dx_mm','UNAVAILABLE')),flush=True)
    return r

def compile_observer(folder):
    cmd=['pkg-config','--cflags','--libs','ignition-transport11','ignition-msgs8']
    p=subprocess.run(cmd,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,
                     stderr=subprocess.PIPE,text=True,timeout=8,check=False)
    need(p.returncode==0,'OBSERVER_PKGCONFIG_FAILED')
    out=folder/'pose_stream_r2'
    c=['c++','-std=c++17','-O1','-Wall','-Wextra',str(OBSERVER_SOURCE),'-o',str(out)]
    r=subprocess.run(c+shlex.split(p.stdout),stdin=subprocess.DEVNULL,
                     stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,
                     timeout=65,check=False)
    if r.returncode:
        print('R2_OBSERVER_COMPILE_DIAGNOSTIC='+r.stderr[-900:].replace('\n',' '),flush=True)
    need(r.returncode==0 and out.is_file(),'POSE_STREAM_COMPILE_FAILED')
    print('R2_POSE_STREAM_COMPILE=PASS',flush=True)
    return out

class PoseFeed:
    """Accept only fresh, unique, complete single-frame readings from C++ subscriber."""
    def __init__(self,exe,stderr_path):
        self.stderr_fp=stderr_path.open('xb')
        try:
            self.proc=subprocess.Popen([str(exe)],stdin=subprocess.DEVNULL,
                       stdout=subprocess.PIPE,stderr=self.stderr_fp,text=True,
                       bufsize=1,start_new_session=True,close_fds=True)
        except BaseException:
            self.stderr_fp.close();raise
        self.cond=threading.Condition()
        self.last=None
        self.sequence=0
        self.delivered=0
        self.last_at=0.0
        self.invalid=0
        self.failure=None
        self.thread=threading.Thread(target=self._read,daemon=True)
        self.thread.start()
    def _read(self):
        try:
            for line in self.proc.stdout:
                fields=line.split()
                if len(fields)!=9 or fields[0]!='POSE':
                    with self.cond:self.invalid+=1
                    continue
                try:
                    seq=int(fields[1])
                    vals=tuple(float(i) for i in fields[2:])
                    if seq<=0 or len(vals)!=7 or not all(math.isfinite(i) for i in vals):
                        raise ValueError('invalid telemetry')
                    cube=vals[0:3];base=vals[3:6];q=vals[6]
                    if max(abs(i) for i in vals)>20 or abs(q)>3.15:
                        raise ValueError('position out of broad bound')
                except (ValueError,OverflowError):
                    with self.cond:self.invalid+=1
                    continue
                with self.cond:
                    if seq<=self.sequence:
                        self.failure='NON_MONOTONIC_STREAM_SEQUENCE';self.cond.notify_all();return
                    self.sequence=seq
                    self.last=(cube,base,q)
                    self.last_at=time.monotonic()
                    self.cond.notify_all()
        except (OSError,UnicodeError) as exc:
            with self.cond:
                self.failure='STREAM_READER_'+type(exc).__name__
                self.cond.notify_all()
        with self.cond:
            if not self.failure:self.failure='STREAM_EOF'
            self.cond.notify_all()
    def snapshot(self):
        end=time.monotonic()+0.65
        with self.cond:
            while self.sequence<=self.delivered and not self.failure:
                remain=end-time.monotonic()
                if remain<=0:break
                self.cond.wait(remain)
            need(not self.failure,'POSE_STREAM_'+str(self.failure))
            need(self.sequence>self.delivered,'POSE_STREAM_TIMEOUT_NO_NEW_MESSAGE')
            need(time.monotonic()-self.last_at<0.35,'POSE_STREAM_FRAME_STALE')
            need(self.last is not None,'POSE_STREAM_DATA_NOT_SET')
            self.delivered=self.sequence
            return self.last
    def __enter__(self):
        return self
    def __exit__(self,exc_type,exc,traceback):
        self.close()
    def close(self):
        if self.proc.poll() is None:
            self.proc.terminate() # Only our own read-only observer (never Gazebo).
            try:self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill();self.proc.wait(timeout=3)
        self.thread.join(timeout=2)
        self.stderr_fp.close()


def verify_stream_against_live(v,feed,ref):
    samples=[]
    for _ in range(3):
        samples.append(feed.snapshot())
        time.sleep(0.12)
    cube,base,q=samples[-1]
    need(all(v.distance(s[0],ref[0])<0.0015 for s in samples),
         'CUBE_MOVED_SINCE_FROZEN_REFERENCE')
    need(all(v.distance(s[1],ref[1])<0.0015 for s in samples),
         'ROBOT_BASE_MOVED')
    need(all(abs(v.angle_diff(s[2],ref[2]))<0.010 for s in samples),
         'JOINT_NOT_VERIFIED_HOME_AFTER_V1_HOLD')
    need(v.distance(samples[0][0],samples[-1][0])<0.001,
         'CUBE_NOT_SETTLED')
    need(abs(v.angle_diff(samples[0][2],samples[-1][2]))<0.004,
         'JOINT_NOT_SETTLED')
    print('R2_POST_HOLD_LIVE_J1_RAD=%.6f'%v.angle_diff(q,ref[2]),flush=True)
    print('R2_POST_HOLD_LIVE_CUBE_XYZ='+','.join('%.6f'%a for a in cube),flush=True)
    print('R2_POST_HOLD_HOME_AND_STABILITY=PASS_READ_ONLY',flush=True)
    return samples[-1]


def prepare():
    need(os.geteuid()==1000 and Path('/.dockerenv').exists(),'ONLY_UBUNTU_DOCKER_ALLOWED')
    need(os.environ.get('IGN_PARTITION')=='pai_ng_defect_camera_v2_20261101',
         'WRONG_GAZEBO_PARTITION')
    need(os.environ.get('DISPLAY')==':0','DISPLAY_NOT_EXPECTED')
    need(WORK.is_dir() and not WORK.is_symlink(),'R2_WORK_DIR_MISSING')
    verify_hash(FROZEN_V1,FROZEN_V1_SHA,'FROZEN_V1_CODE')
    verify_hash(OBSERVER_SOURCE,OBSERVER_SHA,'R2_OBSERVER_SOURCE')
    prior=v1_report()
    v1=frozen_load(FROZEN_V1,'frozen_maxstroke_v1')
    win,v,obs_state,ref,cap,static,ng=v1.prepare()
    need(0.225<=cap<=1.2,'STATIC_CAP_INVALID')
    need(prior.get('driver_exit')==0,'PRIOR_DRIVER_DID_NOT_RETURN_CLEANLY')
    # A clean driver exit is not proof of home. Live HOME is verified separately.
    print('R2_PRIOR_DRIVER_EXIT_NOT_TREATED_AS_HOME_PROOF=True',flush=True)
    return v1,win,v,obs_state,ref,cap,static,ng


def safe_write(path,doc):
    b=(json.dumps(doc,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+'\n').encode('utf8')
    with path.open('xb') as f:f.write(b);f.flush();os.fsync(f.fileno())
    need(path.read_bytes()==b,'REPORT_READBACK_MISMATCH')
    return hashlib.sha256(b).hexdigest()


def dry_tests():
    import ast
    ast.parse(Path(__file__).read_text(encoding='utf8'))
    s=OBSERVER_SOURCE.read_text(encoding='utf8') if OBSERVER_SOURCE.exists() else ''
    need('Subscribe("/world/default/pose/info"' in s,'STREAM_SUBSCRIPTION_MISSING')
    need('Advertise<' not in s and 'Publish(' not in s,'OBSERVER_MUST_NOT_PUBLISH')
    need(FROZEN_V1_SHA=='e79fa76eb563e3058ff0c28b4c88fcca6db80be5bba3b7831d7fb587161799f2',
         'FROZEN_V1_HASH_CONSTANT_BAD')
    need('POSE_STREAM_FRAME_STALE' in Path(__file__).read_text(encoding='utf8'),
         'STALE_FRAME_GUARD_MISSING')
    print('R2_OFFLINE_SELFTEST=PASS_NO_GAZEBO_NO_MOTION',flush=True)
    print('ROBOT_COMMANDS_SENT=0',flush=True)


def record(v1,win,v,obs_state,ref,cap,static,exe,feed):
    # Separate R2 intent from frozen V1 lock. Never clear or modify V1 files.
    lock=WORK/'r2_one_shot_intent.json'
    need(not lock.exists(),'R2_PRIOR_ATTEMPT_EXISTS_NO_RETRY')
    for program in ('ffmpeg','ffprobe'):
        need(subprocess.run(['which',program],stdin=subprocess.DEVNULL,
              stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=3).returncode==0,
              'MISSING_PROGRAM_'+program)
    # Stream sanity rechecked immediately before starting recording.
    verify_stream_against_live(v,feed,ref)
    now=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+str(time.time_ns())
    stem='ng_maxstroke_r2_'+now
    mp4=WORK/(stem+'.mp4')
    motion=WORK/(stem+'.motion.json')
    wit=WORK/(stem+'.witness.json')
    stderr=WORK/(stem+'.ffmpeg.log')
    driver_report={'mode':'SIMULATED_GUARDED_EXTENDED_J1_PUSH_HUMAN_DEFECT_R2',
             'target_cube_x_mm':-100.,'frozen_v1_hold_report_sha256':V1_REPORT_SHA,
             'frozen_v1_source_sha256':FROZEN_V1_SHA,
             'observer_source_sha256':OBSERVER_SHA,
             'ai_v4_fusion':'REVIEW','human_label':'DEFECT',
             'automatic_ai_actuation':False,'physical_robot_used':False,
             'model_pose_writes':0,'static_cap_abs_rad':cap,'static_audit':static,
             'begin_cube_m':list(ref[0]),'samples':[], 'motion_status':'HOLD'}
    cmd=['ffmpeg','-nostdin','-hide_banner','-loglevel','warning',
         '-f','x11grab','-framerate','15','-window_id',win,
         '-i',':0.0','-t','42',
         '-vf','pad=ceil(iw/2)*2:ceil(ih/2)*2',
         '-c:v','libx264','-preset','ultrafast','-crf','22',
         '-pix_fmt','yuv420p','-movflags','+faststart','-n',str(mp4)]
    with tempfile.TemporaryDirectory(prefix='pai_ng_maxstroke_r2_driver_',dir='/tmp') as d:
        driver=v1.build_driver(Path(d))
        print('R2_SIM_ONLY_RECORDING_REQUESTED=True',flush=True)
        with stderr.open('xb') as f:
            ff=subprocess.Popen(cmd,stdin=subprocess.DEVNULL,
                 stdout=subprocess.DEVNULL,stderr=f,start_new_session=True,close_fds=True)
            result='HOLD'
            try:
                time.sleep(2)
                need(ff.poll() is None,'R2_RECORDER_EARLY_EXIT')
                safe_write(lock,{'mode':'SIM_ONLY_MAXSTROKE_R2_ONE_SHOT',
                      'timestamp_utc':now,'prior_hold_sha256':V1_REPORT_SHA,
                      'observer_sha256':OBSERVER_SHA,'video':str(mp4),
                      'no_model_pose_writes':True})
                print('R2_ONE_SHOT_INTENT_SAVED=True',flush=True)
                original=v.snapshot
                v.snapshot=feed.snapshot
                try:
                    result=v1.drive_motion(v,ref,driver,cap,driver_report,obs_state)
                finally:
                    v.snapshot=original
                if ff.poll() is None:
                    try:ff.wait(timeout=47)
                    except subprocess.TimeoutExpired:raise Hold('R2_RECORDER_TIMEOUT')
            finally:
                if ff.poll() is None:
                    ff.terminate()
                    try:ff.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        ff.kill();ff.wait(timeout=3)
        print('R2_FFMPEG_EXIT='+str(ff.returncode),flush=True)
        if mp4.is_file():
            driver_report['video_path']=str(mp4)
            driver_report['video_sha256']=hash_file(mp4)
            print('R2_VIDEO_REMOTE='+str(mp4),flush=True)
            print('R2_VIDEO_SHA256='+driver_report['video_sha256'],flush=True)
        driver_report['record_exit']=ff.returncode
        driver_report['observer_invalid_lines']=feed.invalid
        msha=safe_write(motion,driver_report)
        print('R2_MOTION_REMOTE='+str(motion),flush=True)
        print('R2_MOTION_SHA256='+msha,flush=True)
        need(result.startswith('PASS_'),'R2_MOTION_HELD_NO_RETRY')
        need(ff.returncode==0 and mp4.is_file(),'R2_VIDEO_NOT_COMPLETE')
        metadata=v1.check_video(mp4)
        witness={'mode':'SIM_ONLY_HUMAN_DEFECT_EXTENDED_MOVEMENT_R2_VIDEO',
           'status':result,'target_mm':100.,
           'measured_peak_negative_x_mm':driver_report['peak_cube_dx_mm'],
           'measured_final_x_mm':driver_report['final_cube_dx_mm'],
           'joint_return_verified':driver_report['joint_return_verified'],
           'motion_sha256':msha,'motion_path':str(motion),
           'video_sha256':driver_report['video_sha256'],'video_path':str(mp4),
           'video_metadata':metadata,'no_model_pose_writes':True,
           'v4_ai_fusion':'REVIEW','manual_override_demo':True,
           'note':'Bounded dynamic observed displacement, not global physical reach proof.'}
        wsha=safe_write(wit,witness)
        print('R2_WITNESS_REMOTE='+str(wit),flush=True)
        print('R2_WITNESS_SHA256='+wsha,flush=True)
        print('R2_PEAK_CUBE_DX_MM=%.3f'%driver_report['peak_cube_dx_mm'],flush=True)
        print('R2_FINAL_CUBE_DX_MM=%.3f'%driver_report['final_cube_dx_mm'],flush=True)
        print('R2_GATE='+result,flush=True)
        return 0


def main():
    pa=argparse.ArgumentParser(allow_abbrev=False)
    pa.add_argument('--action',required=True,choices=('selftest','preflight','record'))
    pa.add_argument('--authorization',default='')
    args=pa.parse_args()
    need((args.action=='record' and args.authorization==AUTH) or
         (args.action!='record' and not args.authorization),
         'R2_SIM_ONLY_AUTHORIZATION_NOT_VALID')
    if args.action=='selftest':dry_tests();return 0
    v1,win,v,state,ref,cap,static,ng=prepare()
    lock=WORK/'r2_one_shot_intent.json'
    need(not lock.exists(),'R2_PREVIOUS_MOVEMENT_ATTEMPT_EXISTS')
    with tempfile.TemporaryDirectory(prefix='pai_ng_stream_r2_',dir='/tmp') as d:
        folder=Path(d)
        exe=compile_observer(folder)
        with PoseFeed(exe,WORK/('observer_'+str(os.getpid())+'.log')) as feed:
            verify_stream_against_live(v,feed,ref)
            ng.check_no_publishers(v)
            if args.action=='preflight':
                print('R2_PREFLIGHT_GATE=PASS_READONLY_HOME_AND_STREAM',flush=True)
                print('GAZEBO_STARTS=0',flush=True)
                print('ROBOT_COMMANDS_SENT=0',flush=True)
                return 0
            return record(v1,win,v,state,ref,cap,static,exe,feed)

if __name__=='__main__':
    try:sys.exit(main())
    except (Exception,KeyboardInterrupt) as e:
        print('R2_GATE=HOLD',flush=True)
        print('R2_HOLD_REASON='+type(e).__name__+':'+str(e)[:420],flush=True)
        print('R2_NO_AUTOMATIC_MOVEMENT_RETRY=True',flush=True)
        sys.exit(3)

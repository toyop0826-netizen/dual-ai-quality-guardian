#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Dual-AI Quality Guardian: on-screen Japanese explanatory cards.
Author: Y.TOYODA

Movie assets only. No robot simulation, no model pose changes, no API requests.
All on-screen statements distinguish genuine AI responses from manual demos.
"""
from pathlib import Path
import argparse
from PIL import Image, ImageDraw, ImageFont

FONT='/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'
BOLD='/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc'

def make(path,tag,title,lines,accent='#39CED0',footer='Gazebo / CRANE+ | シミュレーション実証'):
    img=Image.new('RGB',(1280,720),'#101B2E')
    d=ImageDraw.Draw(img)
    d.rectangle((0,0,1280,9),fill=accent)
    d.ellipse((1040,-120,1420,260),outline='#273E5C',width=6)
    d.ellipse((1000,-80,1370,295),outline='#1D2F49',width=2)
    fb=lambda s:ImageFont.truetype(BOLD,s)
    fr=lambda s:ImageFont.truetype(FONT,s)
    d.text((88,80),tag,font=fb(22),fill=accent)
    d.text((88,135),title,font=fb(49),fill='#F6F8FD')
    y=252
    for line in lines:
        d.ellipse((92,y+11,106,y+25),fill=accent)
        d.text((132,y),line,font=fr(30),fill='#DFE7F2')
        y+=83
    d.rectangle((88,634,1190,636),fill='#31445D')
    d.text((88,656),footer,font=fr(20),fill='#A8B7CA')
    img.save(path,optimize=True)


def main(out):
    o=Path(out);o.mkdir(parents=True,exist_ok=True)
    cards={
     'title':('FINAL TASK','Dual-AI Quality Guardian',[
       '画像AIの判定と、ロボットによる実際の移動を検証',
       '正常品GOOD ／ 傷あり品DEFECT の2ケース',
       '物理シミュレーションの動作映像・証拠を使用']),
     'good_intro':('CASE 01 / GOOD','正常品をOK方向へ',[
       'AI検査で正常品を識別することを想定',
       '使用ロボット：CRANE+ / Gazebo',
       '方向：+X（緑色プッシャー）']),
     'good_ai':('CASE 01 / AI EVIDENCE','2つのAIが正常と判断',[
       'OpenAI（B67実画像判定）：GOOD',
       'Gemini（B67実画像判定）：GOOD',
       '判定記録と本映像の動作連携は別工程']),
     'good_action':('CASE 01 / ROBOT MOTION','GOOD：ロボット実動作',[
       '関節1を小刻みに動かしてキューブを押す',
       '目標：+100mm／到達量は別途実測',
       '座標の直接書換え・実機操作は行わない']),
     'good_result':('CASE 01 / RESULT','GOOD側：実測結果',[
       '実測ピークと終了時位置を証拠JSONに記録',
       '100mm未達なら、未達と明示',
       '単なるCG移動ではなくGazebo物理結果']),
     'ng_intro':('CASE 02 / DEFECT','傷あり品をNG方向へ',[
       'カメラでキューブ表面の傷を撮影',
       'AIの不一致を含めて記録',
       '方向：-X（青色プッシャー）']),
     'ng_ai':('CASE 02 / AI EVIDENCE','AIは一致せず：人が確認',[
       'OpenAI（V4実画像判定）：REVIEW',
       'Gemini（V4実画像判定）：DEFECT',
       '自動動作は保留し、人がDEFECTと確認']),
     'ng_action':('CASE 02 / ROBOT MOTION','DEFECT：ロボット実動作',[
       '人が確認した傷あり品のシミュレーション実演',
       '青色プッシャーで-X方向へ押す',
       'AIの全自動仕分け成立とは表示しない']),
     'ng_result':('CASE 02 / RESULT','DEFECT側：実測結果',[
       '動作途中の最大-X変位：65.94mm',
       '録画終了時の開始位置からの変位：18.14mm',
       '目標100mmには未到達・実際の移動を記録']),
     'limits':('ENGINEERING REVIEW','成果と、まだできていないこと',[
       '実現：2つのAIの画像推論と押し動作',
       '未実現：AI合意からの完全自動仕分け',
       '未実現：把持搬送と仕分け箱への投入']),
     'end':('SUBMISSION','実証動画とコード・レポート',[
       'GOOD／DEFECTの実録画を別々に検証',
       'SHA-256・変位ログを証拠として保存',
       '実績と制約を区別して提出します']),
    }
    for name,(tag,title,lines) in cards.items():
        accent='#E9BC70' if name.startswith('ng') else '#39CED0'
        make(o/(name+'.png'),tag,title,lines,accent)
    print('CARDS_WRITTEN='+str(len(cards)))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',required=True)
    main(p.parse_args().out)

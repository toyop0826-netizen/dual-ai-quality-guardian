1. 証跡ファイル全体の役割
6件のJSONは、大きく3つのグループに分類できます。
分類	ファイル	主な目的
AI判定	DEFECT_AI_V4_real_results.json	AIがどのように判断したか
動作測定	GOOD_original_motion.json	GOODの移動量を記録
動作測定	DEFECT_original_motion.json	DEFECTの移動量を記録
実証確認	GOOD_original_witness.json	GOODの実験成立条件を記録
実証確認	DEFECT_original_witness.json	DEFECTの実験成立条件を記録
動画検証	video_build_manifest.json	完成動画と元データの対応関係を記録

ここで重要なのは、motion.jsonとwitness.jsonの役割が異なることです。
- motion.json：どのように動いたかを記録する。
- witness.json：その動作が所定の条件を満たしたかを確認する。

2. 各ファイルの詳細説明
No.01　DEFECT_AI_V4_real_results.json
役割：OpenAIとGeminiによるDEFECT画像の判定結果を記録するJSONファイル。

主な内容：
- V4で実施した画像判定の結果
- OpenAIによる判定：REVIEW
- Geminiによる判定：DEFECT
- 二重AI判定に関する証跡
- 人による最終判断を必要とするケースの説明に利用
このファイルの重要な点は、2つのAIの判定が一致していないことです。

OpenAIは人の確認が必要と判断し、Geminiは欠点と判断しています。

この結果を単純な多数決に変換せず、AIの判断に不確実性が残る場合には人が確認するという仕組みを説明するための資料です。

技術的な意義： AIの判定結果だけで自動仕分けするのではなく、人の判断を組み合わせた品質検査システムの必要性を示しています。
No.02　DEFECT_original_motion.json
役割：DEFECTケースにおけるGazebo上の物体移動を、測定データとして記録するJSONファイル。

主な内容：
- シミュレーション中のキューブの移動量
- 移動量の時系列データ
- 最大変位と最終変位
- ロボットの元位置への復帰確認に関係する情報
実測結果：
測定項目	実測値
目標変位	−100 mm
最大変位	−65.940 mm
最終変位	−18.13588 mm
最大変位の目標到達率	約65.9%

このファイルは、ロボットに移動指令を送ったという記録ではなく、実際のシミュレーション上でキューブがどの程度動いたかを確認するために使用されます。

技術的な意義： ロボットの動作指令と対象物の実際の移動量を区別し、物理的な動作結果を定量的に評価できます。
No.03　DEFECT_original_witness.json
役割：DEFECTケースの実証結果が所定の条件を満たしているかを確認するJSONファイル。

主な確認内容：
- DEFECT R2のシミュレーションであること
- 動作結果が記録されていること
- 測定値が期待範囲内であること
- ロボットの元位置への復帰確認
- AI判定結果がREVIEWとして扱われていること
- 人による判断を含むデモであること
- Gazeboのモデル位置を直接書き換えていないという記録
Finalizerでは、manual_override_demo、joint_return_verified、v4_ai_fusion などの条件を確認しています。

また、動画生成Pythonでは、DEFECTのmotion.jsonとwitness.jsonの測定値が整合するかも検証しています。

技術的な意義： DEFECTケースの実験結果が、単なる映像ではなく、所定の検証条件を満たす記録として管理されていることを示します。
No.04　GOOD_original_motion.json
役割：GOODケースにおけるGazebo上のキューブ移動量を記録するJSONファイル。

主な内容：
- GOODケースの移動量の時系列データ
- 最大変位と最終変位
- ロボットの動作・復帰に関係する測定情報
実測結果：
測定項目	実測値
目標変位	+100 mm
最大変位	+57.9031 mm
最終変位	+45.6114 mm
最大変位の目標到達率	約57.9%

移動中の最大変位と動作終了時の変位は異なります。

そのため、「最大57.9031mm動いた」という事実と、「最終的に45.6114mmの変位が残った」という事実を区別する必要があります。

技術的な意義： Gazeboの実測データからGOODケースの移動性能を数値で評価し、今後のロボット動作改善に利用できます。
No.05　GOOD_original_witness.json
役割：GOODケースの実験成立条件と測定結果の信頼性を確認するJSONファイル。

主な確認内容：
- GOOD R1のシミュレーションであること
- 実測変位が記録されていること
- ロボットの元位置への復帰確認
- 動画と動作データのSHA-256の整合性
- AIの判断による完全自動動作ではないこと
今回のFinalizerでは、次の状態が確認されています。

PASS_BOUNDED_MAX_MEASURED_BELOW_100MM

これは、所定の条件内で移動測定が成立した一方、100mmの目標変位には達していないことを示すステータスです。

技術的な意義： GOODケースの測定結果について、どの条件が確認され、どの目標が未達だったかを明確にできます。

No.06　video_build_manifest.json
役割：提出用動画3本の生成結果と、元動画・測定証跡との対応関係を管理するJSONファイル。

主な内容：
- 動画編集の実行モード
- 使用したGOOD・DEFECT元動画のSHA-256
- 動画に表示する測定結果
- AI判定結果
- GOODの過去版への代替切替の有無
- 完成動画3本のファイル名
- 完成動画のSHA-256
- 完成動画の再生時間・ファイルサイズ
今回の生成結果：
完成動画	再生時間	状態
GOOD_story.mp4	77秒	PASS
DEFECT_story.mp4	77秒	PASS
PAI_final_two_cases_story.mp4	166秒	PASS

本ファイルの特徴は、単に動画ファイルが存在することを確認するのではなく、その動画がどの元データに基づいて作成されたかを追跡できることです。

技術的な意義： 動画と証跡の対応関係を保持することで、提出後も動画の内容や生成結果の整合性を検証できます。

3. motion.jsonとwitness.jsonの違い
この2種類のファイルは、GitHubで説明する際に特に重要です。
比較項目	motion.json	witness.json
主な役割	動作の測定記録	実証条件の確認記録
中心となる情報	移動量・時間・変位	動作状態・検証結果
最大変位	記録する	測定値との整合性を確認
最終変位	記録する	測定値との整合性を確認
ロボット復帰	関連情報を保持	復帰確認結果を保持
用途	動作解析	実験結果の妥当性確認

例えばGOODケースでは、motion.jsonによって「キューブが最大57.9031mm移動した」という測定結果を確認します。

一方、witness.jsonによって、「GOOD R1の実験であること」「ロボット復帰が確認されたこと」「動画や測定記録が対応していること」などを検査します。

両方を組み合わせることで、測定値と実験成立条件の整合性を確認できます。

4. 6ファイルの関連性
Dual-AI Quality Guardian
│
├─ AI画像判定
│   └─ DEFECT_AI_V4_real_results.json
│
├─ GOODケース
│   ├─ GOOD_original_motion.json
│   └─ GOOD_original_witness.json
│
├─ DEFECTケース
│   ├─ DEFECT_original_motion.json
│   └─ DEFECT_original_witness.json
│
└─ 提出動画の管理
    └─ video_build_manifest.json
        ├─ GOOD_story.mp4
        ├─ DEFECT_story.mp4
        └─ PAI_final_two_cases_story.mp4


これらを組み合わせると、AIの判定結果、ロボットの物理的な動作結果、実験条件、提出用動画の対応関係を説明できます。

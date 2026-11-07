# 第19条に基づくスクラムのアノテーション

[English](LAW19_WORKFLOW.md) | [日本語](LAW19_WORKFLOW.ja.md)

新しい画面では、提供されたWorld Rugby第19条を基準に、観察した事実・条項の評価・
実際のレフェリー判定を別々に記録します。選手の追跡結果だけで、反則・故意・原因・
反則者を確定しません。従来のフェーズ分類用パイロットは引き続き利用できます。

## 1. 画面を作る

新しい `scan` は、第19条用の `review.html` と `events-law19.json` を生成します。
元の収集用 `events.json` と `legacy_clip_review.html` も保持します。
既存の収集用JSONや保存した第19条用JSONから再開する場合は、次を実行します。

```sh
python autoclip.py review-laws --video media/match01/match.mp4 --events runs/match01/events.json --ruleset-preset rwc2023 --output runs/match01-law19
open runs/match01-law19/review.html
```

出力先は新しいフォルダーを指定します。画面で同じ元のMP4を選び、閉じる前に
JSONを保存してください。保存したJSONを読み込むと再開できます。
切り出し時はファイル名だけでなく、元映像のSHA-256も照合します。

最初の対象は**男子ラグビーワールドカップ2023**です。`scan` または `review-laws` に
`--ruleset-preset rwc2023` を付けると対象大会が入力されます。
当時の規則の版は空欄、試験的ルールの適用は不明、規則の確認状態は未検証のままです。
提供された19.30(a)の試験的ルールを2023年にも適用されたものとして扱いません。
他大会の映像ではこのオプションを省略してください。

## 2. 映像と適用規則を確認する

発声候補を確認して誤検出を除外し、Crouch・Bind・Setを確認済みにします。
実際の終了時刻を `attempt_end_s`、終了後のレフェリーの説明終了を
`explanation_end_s`、両方を残すクリップ終了を `clip_end_s` に記録します。
開始はCrouchの15秒前です。元映像の先頭を超える場合は0秒になります。
終了位置とカメラ視点の確認状態は、条項評価の確認状態と別です。

大会名・試合グループ・日付・`ruleset_id`・`law_edition`・`trial_context` を記録します。
その試合に適用された規則を確認してから `context_status=verified` にしてください。
提供されたHTMLは版が不明で、特定のワールドカップの大会規定を確認した資料では
ありません。過去の版・大会規定・U19規則・試験的ルールの適用確認が必要な場合が
あります。著作権表示の年を規則の版として扱わないでください。

7種類の表を使います。

| 表 | 内容 |
| --- | --- |
| events | 時系列・試合と規則の情報・切り出しの確認 |
| teams | 出場人数・スクラム人数・ポジションの構成 |
| participants | 根拠のある選手識別・所属・役割・追跡ID |
| restarts | 再開理由・位置・投入権・リセットとの関係 |
| observations | 時刻・見え方・観察値・証拠 |
| rule_assessments | 個別条項と観察結果の独立した比較 |
| decisions | 実際の判定・レフェリーの発言・判定上の反則者 |

88件の条項に加え、原則・17件の再開条件・図と31本の動画の参照情報を確認できます。
画像・参照動画そのものの内容は未確認です。179種類の観察項目は選択肢であり、
全部を埋める義務はありません。空欄は未記録、`not_observable` は証拠不足、
`not_applicable` は条件が適用されない状態です。証拠のIDは同じイベントの
observationsを参照するJSON配列で指定します。倒れた事実や背番号3だけで、
故意や反則者を決めないでください。

## 3. 記録した事実からチェックを行う

```sh
python autoclip.py check-laws --events ~/Downloads/law19_reviewed_events.json --output runs/match01-checked.json
python autoclip.py review-laws --events runs/match01-checked.json --output runs/match01-check-review
```

準備の30秒制限・人数構成・許可された人数削減・投入前の押し・確認済みリセットの
投入チーム継続など、根拠を確認できる項目を提案します。適用規則が確認済みで、
観察と証拠がレビュー済みの場合に限ります。不明・不足・矛盾があれば
`not_observable` とします。試験的ルールの適用を大会名から推測しません。

これは記録済みの事実のチェックで、映像から新しい動作を自動検出する機能では
ありません。人数だけのチェックでは、同じ条項のバインドや姿勢まで確認できません。
人手の評価・実際の判定を上書きせず、故意や反則者も自動で付けません。
編集後は提案が古くなるため、コマンドを再実行します。
競技規則上の開始はSetではなくボール投入時です（19.16）。
安全確保の笛が必ずペナルティになるわけではなく、無反則のリセットもあります。

時刻のチェックではイベントも `review_status=reviewed` にし、`events.evidence_ids` で
確認済みの観察を参照します。観察には証拠の種類・場所・見え方を記録し、JSONの
観察値を該当する秒数と一致させます。`mark_s` は `referee_mark_time_s`、`ready_s` は
`teams_ready_time_s`、`ball_feed_s` は `ball_leave_hands_time_s`、`first_push_s` は
`push_start_time_s` という観察項目です。例として投入が50秒ならJSON値は `50` です。
人数の証拠は各チームの `evidence_ids` で参照し、`subject_type=team`、
`subject_id=team_id` を指定します。人数だけでバインドまで確認できたことにはしません。
試験的ルールは当時の適用を確認した後にのみ、`trial_context` へ
`19.30(a)=applicable` または `19.30(a)=not_applicable` と記録してください。

## 4. 検証して出力する

```sh
# クリップの準備が未完でも、7種類の表を下書き状態のまま出力できます。
python autoclip.py export-annotations --events ~/Downloads/law19_reviewed_events.json --output datasets/match01-annotations

# 確認済みの俯瞰・横からのクリップと、音声・アノテーションを出力します。
python autoclip.py export --video media/match01/match.mp4 --events ~/Downloads/law19_reviewed_events.json --output datasets/match01
```

不正なID・参照・選択肢・時刻、記録された終了や説明を切り落とす設定は拒否します。
元のメタデータを含むJSONと7種類のCSVを保持します。CSVの時刻は元映像の秒数で、
`clips.csv` で切り出し開始位置を確認できます。クリップの確認完了は、条項評価の
完了を意味しません。同じ試合の別映像も同一のデータ分割にまとめてください。
既存の出力先は上書きしません。

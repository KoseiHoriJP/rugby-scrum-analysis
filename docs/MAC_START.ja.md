# 新コードをMacに取り込んで起動する

この手順は、第19条のアノテーション画面を含む新コードをMacへ取り込むためのものです。
対象は男子ラグビーワールドカップ2023です。試合映像は別途、音声付きのMP4を用意します。

## 1. GitHubからダウンロードする

[新コードのブランチ](https://github.com/KoseiHoriJP/rugby-scrum-analysis/tree/codex/law19-rwc2023-mac)
を開き、緑色の **Code → Download ZIP** を選びます。

[ZIPを直接ダウンロード](https://github.com/KoseiHoriJP/rugby-scrum-analysis/archive/refs/heads/codex/law19-rwc2023-mac.zip)
する方法もあります。GitHubへのログインを求められた場合は、リポジトリにアクセスできる
自分のアカウントでログインしてください。

Finderの「ダウンロード」でZIPをダブルクリックして展開します。すでに同名の作業
フォルダーがある場合は、新しい場所に展開して、以前保存したJSONや映像を保持してください。

## 2. ターミナルでそのフォルダーを開く

Macの「ターミナル」を開き、`cd ` と入力します。`cd` の後ろに半角スペースを入れ、
展開したフォルダーをターミナルのウィンドウへドラッグして、Returnキーを押します。
`autoclip.py` と `scripts` フォルダーが入っている場所を選んでください。

Gitをすでに使っていて、新しい場所にクローンする場合は、次でも取得できます。

```sh
git clone --branch codex/law19-rwc2023-mac --single-branch \
  https://github.com/KoseiHoriJP/rugby-scrum-analysis.git rugby-scrum-law19
cd rugby-scrum-law19
```

## 3. 初回の準備をする

[Homebrew](https://brew.sh/ja/) が未導入の場合は、公式ページの手順で先に導入します。
導入済みであれば、ターミナルで次を実行します。

```sh
brew install python@3.12 ffmpeg yt-dlp
```

`yt-dlp` は公開URLからの取得を試すための任意ツールです。すでにMP4を持っている
場合は、`brew install python@3.12 ffmpeg` で構いません。

## 4. ファイル選択付きで起動する

```sh
bash scripts/label_match_macos.command
```

初回はPythonの専用環境と音声認識ライブラリを準備します。ファイル選択画面で元の
試合MP4を選ぶと、音声認識モデルを必要に応じてダウンロードし、スクラム候補を探します。

ブラウザーで確認画面が開いたら、「Original MP4」で同じ試合動画を選びます。
候補・終了時刻・説明の終了・カメラ視点を確認し、必要な観察と判定を記録して、
「Save full review JSON」で保存してください。2023年の適用規則を確認するまでは
規則の確認状態を未検証に保ちます。

ターミナルに戻り、保存したJSONを選ぶと、確認済みのクリップと表を出力します。
ファイル選択待ちのターミナルは終了せずに開いておいてください。

詳しい入力手順は [第19条のアノテーション手順](LAW19_WORKFLOW.ja.md)にあります。
画面のテンプレート `templates/law19_review.html` は直接開かず、処理によって生成された
`runs/…/review.html` を使用してください。

# フロント画面（inuki）

`index.html`は、サービス「いぬきんじょ」のランディングページ（トップページ）。
`demo.html`は、APIRunの主要エンドポイントをブラウザから試す動作確認ページです。
公開画面はビルドツールやフレームワークを使わない静的HTMLと共通JavaScriptで構成します。

## ページ構成

- `index.html`: トップページ（LP）。サービス紹介・検索フォームのモックアップ
- `demo.html`: API動作確認用フォーム（旧`index.html`）
- `lists.html`: DBの居抜き物件候補を一覧検索・表示するページ
- `maps.html`: DBの居抜き物件候補をマップ形式で検索・表示するページ
- `vacant-search.js`: 一覧・マップ共通の検索、現在地取得、業種選択、表示処理
- `terms.html`: 利用規約
- `privacy.html`: プライバシーポリシー
- `faq.html`: よくある質問
- `contact.html`: お問い合わせフォーム
- `img/`: LP用の画像アセット

各ページのヘッダー/フッターから相互にリンクしている。`contact.html`のフォーム送信は
バックエンドに送信せず、「現在、送信を停止しています」と表示する。
`index.html`（LP）の「検索する」ボタンは`lists.html`へ、マップ検索と業種カテゴリーは
`maps.html`へ誘導する。業種カテゴリーから遷移した場合は、選択した業種タグを検索条件へ引き継ぐ。

## 使い方

1. Cloud RunのフロントURLで`index.html`を開く。
2. `lists.html`または`maps.html`で緯度・経度・半径・業種を指定する。
3. APIRun URLは非表示の固定設定で、nginxの同一オリジン`/api/`経由で呼び出す。
4. 現在地取得と検索パネルの最小化・復元にも対応する。

## 前提条件（重要）

公開検索画面は認証機能を持たない。動作させるにはAPIRun側で以下を有効化する。
一覧・マップ検索はnginxの`/api/`プロキシを使うため、ブラウザからAPIRunを直接呼び出さず、
APIの500応答にCORSヘッダーがない場合もブラウザ側で応答を扱える。

1. **未認証アクセスの許可**（`terraform apply`時に`app_allow_unauthenticated=true`を指定）
2. **CORSの許可**（`demo.html`や管理画面など、APIRunを直接呼ぶ画面を利用する場合）

```bash
cd terraform
terraform apply \
  -var="app_allow_unauthenticated=true" \
  -var="app_cors_allowed_origins=https://inuki-804626259225.us-central1.run.app" \
  # ...他の必須変数...
```

公開検索を提供する間は`app_allow_unauthenticated=true`が必要です。相談API・登録APIも
同じAPIRunで公開されるため、本格運用前に利用者認証・認可を実装してください。公開検索を
停止する場合は`app_allow_unauthenticated=false`へ戻します。

## 本格的な業務用UIについて

本ページはあくまで動作確認用です。実際に自治体職員・利用者が使う業務用のUIを
構築する場合は、認証（利用者ログイン等）・入力検証・エラーハンドリング等を
含めた本格的なフロントエンド実装（React等）を別途設計・実装することを推奨します。

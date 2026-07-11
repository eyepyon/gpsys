# フロント画面（inuki）

`index.html`は、サービス「いぬきんじょ」のランディングページ（トップページ）。
`demo.html`は、APIRunの3つのエンドポイント（相談応答・地域資源登録・居抜き物件検索）を
ブラウザから手軽に試すための、動作確認専用の最小限の静的HTMLページです。
いずれもビルドツールやフレームワークは使用していません（単一のHTMLファイルのみ）。

## ページ構成

- `index.html`: トップページ（LP）。サービス紹介・検索フォームのモックアップ
- `demo.html`: API動作確認用フォーム（旧`index.html`）
- `terms.html`: 利用規約
- `privacy.html`: プライバシーポリシー
- `faq.html`: よくある質問
- `contact.html`: お問い合わせフォーム
- `img/`: LP用の画像アセット

各ページのヘッダー/フッターから相互にリンクしている。`contact.html`のフォーム送信は
バックエンドに送信せず、ブラウザ内で完了メッセージを表示するのみ（動作確認用のダミー実装）。
`index.html`（LP）の検索フォームも同様に未実装で、「検索する」ボタンは`demo.html`へ誘導する。

## 使い方

1. `index.html`をブラウザで直接開く（ローカルファイルとして開くだけで動作します）。
2. 画面上部の「APIRunのベースURL」欄に、デプロイ済みのAPIRunのURLを入力する
   （例: `https://regional-revitalization-api-dev-xxxxx.a.run.app`）。
3. 各セクションのフォームに入力し、ボタンを押すとAPIを呼び出し、
   レスポンス（JSON）がそのまま画面下部に表示されます。

## 前提条件（重要）

このページはブラウザから直接HTTPリクエストを送信するだけの薄いクライアントであり、
認証機能を持ちません。動作させるには、APIRun側で以下の2点を一時的に有効化する必要があります。

1. **未認証アクセスの許可**（`terraform apply`時に`app_allow_unauthenticated=true`を指定）
2. **CORSの許可**（`terraform apply`時に`app_cors_allowed_origins`にこのページを配信する
   オリジンを指定。ローカルファイルとして開く場合は`file://`オリジンとなり、ブラウザの実装に
   よってCORSチェックの挙動が異なるため、GCSの静的ホスティング等でオリジンを固定して
   配信することを推奨します）

```bash
cd terraform
terraform apply \
  -var="app_allow_unauthenticated=true" \
  -var="app_cors_allowed_origins=https://storage.googleapis.com" \
  # ...他の必須変数...
```

**確認が終わったら、必ず`app_allow_unauthenticated=false`（デフォルト）に戻して
再適用してください。** 未認証アクセスを許可したままにすると、相談API・登録APIが
インターネット上の誰からでも呼び出せる状態になります。

## 本格的な業務用UIについて

本ページはあくまで動作確認用です。実際に自治体職員・利用者が使う業務用のUIを
構築する場合は、認証（利用者ログイン等）・入力検証・エラーハンドリング等を
含めた本格的なフロントエンド実装（React等）を別途設計・実装することを推奨します。

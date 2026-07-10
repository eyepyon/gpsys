# Requirements Document

# 要件定義書: 地方創生支援システム (regional-revitalization-support-system)

## Introduction

本要件定義書は、既存の`design.md`（設計書）から導出したものである。位置情報データベース（地理空間インデックス）とベクトルデータベース（pgvector）を活用し、地方創生に関する相談対応・地域資源の検索・登録を行うシステムを、GCP（us-central1リージョン）上にCloud Run、Cloud SQL for PostgreSQL、Cloud Storageを用いて構築する。推論エンジンにはGemma 4 12B QATモデルをCloud Run上でGPU（L4）を用いてホストする。さらに本システムは、Google Maps Platform Places APIを用いて閉店・廃業したスポットを検知し「居抜き物件」として蓄積・検索できる機能を提供し、不動産屋も把握していない物件情報を早期に得て出店コストを抑えることを支援する。インフラはTerraformでコード化し、すべてのドキュメント・コードコメントは日本語・UTF-8・LF改行で記述する。

## Requirements

### Requirement 1: 相談応答（RAGによる回答生成）

**User Story:** 地域の利用者として、質問文と自分の位置情報を入力すると、近隣かつ関連性の高い地域資源を根拠とした回答を得たい。それにより、地方創生に関する的確な情報を得られるようにしたい。

#### Acceptance Criteria

1. WHEN 利用者が`query_text`（空でない文字列）、`location`（有効な`GeoPoint`）、`radius_km`（正の数）を含む相談リクエストを送信した THEN システム SHALL ハイブリッド検索を実行し、その結果をコンテキストとして推論サービスに回答生成を依頼する
2. WHEN 相談リクエストの`query_text`が空文字列である THEN システム SHALL リクエストを拒否し、検証エラーを返す
3. WHEN 相談リクエストの`radius_km`が0以下である THEN システム SHALL リクエストを拒否し、検証エラーを返す
4. WHEN 推論サービスが正常に応答を生成した THEN システム SHALL 生成されたテキストと、参照した地域資源一覧の両方を利用者に返す
5. WHEN 推論サービスの呼び出しが失敗またはタイムアウトした THEN システム SHALL 部分的な結果を利用者に返さず、エラーを返す
6. IF 相談リクエストに`top_k`が指定されない THEN システム SHALL デフォルト値5を用いる

### Requirement 2: 地理空間検索（近隣地域資源の取得）

**User Story:** システム開発者として、指定した位置から一定距離内にある地域資源を、距離が近い順に取得する機能が必要である。それにより、利用者の現在地に関連する情報を優先的に提示できるようにしたい。

#### Acceptance Criteria

1. WHEN 有効な`location`、`radius_km > 0`、`limit >= 1`が与えられた THEN システム SHALL `location`との地理的距離が`radius_km`以下の地域資源のみを返す
2. WHEN 検索結果が複数件存在する THEN システム SHALL 戻り値のリストを`location`からの距離の昇順（近い順）に並べる
3. WHEN 検索対象件数が`limit`を超える THEN システム SHALL 戻り値の件数を`limit`以下に制限する
4. WHEN 地理空間検索が実行される THEN システム SHALL データベースに対して読み取り専用の操作のみを行い、データを変更しない
5. IF `location`の緯度が-90から90の範囲外、または経度が-180から180の範囲外である THEN システム SHALL 検証エラーとしてリクエストを拒否する

### Requirement 3: ベクトル検索（類似地域資源の取得）

**User Story:** システム開発者として、クエリのembeddingに対してコサイン類似度が高い地域資源を取得する機能が必要である。それにより、位置に依存しない意味的関連性の高い情報も提示できるようにしたい。

#### Acceptance Criteria

1. WHEN 有効な`embedding`（格納済みembeddingと同一次元数）、`top_k >= 1`が与えられた THEN システム SHALL コサイン類似度が高い順に地域資源を返す
2. WHEN 検索結果が複数件存在する THEN システム SHALL 戻り値のリストをコサイン類似度の降順に並べる
3. WHEN 検索対象件数が`top_k`を超える THEN システム SHALL 戻り値の件数を`top_k`以下に制限する
4. WHEN ベクトル検索が実行される THEN システム SHALL データベースに対して読み取り専用の操作のみを行い、データを変更しない
5. IF 与えられた`embedding`の次元数が格納済みデータの次元数と一致しない THEN システム SHALL エラーを検知し、500エラーとしてログに記録する

### Requirement 4: ハイブリッド検索（地理空間フィルタリングとベクトル類似度ソートの段階的統合）

**User Story:** システム開発者として、位置情報による絞り込みとベクトル類似度によるソートを単一のSQLクエリで段階的に実行するハイブリッド検索機能が必要である。それにより、位置的関連性を優先しつつ意味的関連性の高い検索結果を効率的に提供したい。

#### Acceptance Criteria

1. WHEN 有効な`query_text`、`location`、`radius_km > 0`、`top_k >= 1`を含むハイブリッド検索が要求された THEN システム SHALL PostGISの`ST_DWithin`等の地理空間条件により`location`から半径`radius_km`以内の地域資源に候補集合を絞り込む
2. WHEN 候補集合への絞り込みが完了した THEN システム SHALL `query_text`のembeddingをCloud SQLの`google_ml_integration`拡張によりSQL側（データベース側）で生成する
3. WHEN 候補集合が1件以上存在する THEN システム SHALL 候補集合内で生成したembeddingとのpgvectorコサイン類似度（`<=>`演算子）の降順に候補集合をソートし、上位`top_k`件を単一SQLクエリの結果として返す
4. WHEN 候補集合が0件である THEN システム SHALL ベクトル類似度の計算を行わず、空リストを返す
5. WHEN ハイブリッド検索が結果を返す THEN システム SHALL 戻り値に含まれる全ての資源について、`location`との地理的距離が`radius_km`以下であることを保証する
6. WHEN 候補集合の件数が`top_k`を超える THEN システム SHALL 戻り値の件数を`min(候補集合の件数, top_k)`に制限する
7. THE システム SHALL ハイブリッド検索の戻り値において同一`resource_id`が複数回出現しないことを保証する（単一SQLクエリの結果セットとして実行されるため、重複排除の後処理を必要とせず重複は発生しない）

### Requirement 5: 地域資源の登録

**User Story:** 自治体職員として、地域資源（施設・イベント・支援制度等）の情報とファイル（画像・レポート等）を登録したい。それにより、システムが今後の相談応答時にその資源を検索・参照できるようにしたい。

#### Acceptance Criteria

1. WHEN 職員が`name`、`category`、`description`（いずれも空でない文字列）、有効な`location`を含む登録リクエストを送信した THEN システム SHALL INSERT文の中でCloud SQLの`google_ml_integration`拡張を用いて説明文からembeddingをデータベース側（SQL関数呼び出し）で生成し、データベースへ地域資源を保存する
2. WHEN 登録リクエストに添付ファイル（`file_bytes`と`content_type`）が含まれる THEN システム SHALL ファイルをCloud Storageへアップロードし、発行されたURLを`file_url`として資源情報とともに保存する
3. WHEN 登録リクエストに添付ファイルが含まれない THEN システム SHALL `file_url`をNoneのまま資源情報を保存する
4. WHEN ファイルのアップロードが失敗した THEN システム SHALL データベースへの登録を実行せず、エラーを返す（部分登録の防止）
5. WHEN 登録が正常に完了した THEN システム SHALL 一意な`resource_id`を発行し、登録済み資源を`resource_id`で再取得できるようにする
6. IF `name`、`category`、`description`のいずれかが空文字列である THEN システム SHALL リクエストを拒否し、検証エラーを返す
7. IF `location`が緯度経度の有効範囲外である THEN システム SHALL リクエストを拒否し、検証エラーを返す
8. IF 添付ファイルの`file_bytes`が指定されているにもかかわらず`content_type`が指定されていない THEN システム SHALL リクエストを拒否し、検証エラーを返す

### Requirement 6: 位置情報データモデルの検証

**User Story:** システム開発者として、システム全体で位置情報（緯度経度）が常に有効な範囲であることを保証したい。それにより、不正な位置情報による検索・登録の誤動作を防ぎたい。

#### Acceptance Criteria

1. WHEN 任意のコンポーネントが`GeoPoint`を受理する THEN システム SHALL 緯度が-90以上90以下であることを検証する
2. WHEN 任意のコンポーネントが`GeoPoint`を受理する THEN システム SHALL 経度が-180以上180以下であることを検証する
3. IF 緯度または経度が有効範囲外である THEN システム SHALL 当該リクエスト（検索・登録）を検証エラーとして拒否する

### Requirement 7: 推論サービス（Gemma 4 12B QAT on Cloud Run with L4 GPU）

**User Story:** システム開発者として、Gemma 4 12B QATモデルをGCP Cloud Run上でGPU（L4）を用いてホストし、コンテキスト付きの生成リクエストを処理するサービスが必要である。それにより、アプリ本体サービスから分離された形で推論処理をスケールさせたい。

#### Acceptance Criteria

1. WHEN 推論サービスがデプロイされる THEN システム SHALL GCPのus-central1リージョンにおいて、GPUタイプL4を割り当てたCloud Runサービスとして構築する
2. WHEN 推論サービスがプロンプトとコンテキストスニペットを含む生成リクエストを受信した THEN システム SHALL 生成テキストと入力/出力トークン数を含む応答を返す。入力/出力トークン数は0以上の整数を許容する（空のコンテキストや空の生成結果であっても0件として応答してよい）
3. WHEN アプリ本体サービス以外から推論サービスへの外部アクセスが試行された THEN システム SHALL アクセスを拒否する（内部通信またはIAM認証によって保護される）
4. WHEN 推論サービスへのリクエストが指定タイムアウトを超えた THEN システム SHALL エラーとして処理を終了し、アプリ本体サービスにエラーを通知する

### Requirement 8: データストア（Cloud SQL for PostgreSQL、地理空間インデックス + pgvector）

**User Story:** システム開発者として、地域資源のメタデータ、位置情報、embeddingベクトルを1つのデータベースで一貫して管理したい。それにより、地理空間検索とベクトル検索を同一のクエリ経路で扱えるようにしたい。

#### Acceptance Criteria

1. WHEN データベースがプロビジョニングされる THEN システム SHALL Cloud SQL for PostgreSQLインスタンスに地理空間インデックス機能（PostGIS拡張相当）を有効化する
2. WHEN データベースがプロビジョニングされる THEN システム SHALL Cloud SQL for PostgreSQLインスタンスにpgvector拡張を有効化する
3. WHEN 地域資源テーブルが作成される THEN システム SHALL `location`列に地理空間インデックス（GiST等）、`embedding`列にベクトルインデックス（HNSW等）を作成する
4. WHEN アプリ本体サービスがデータベースに接続する THEN システム SHALL プライベートIPまたはCloud SQL Auth Proxy経由で接続し、パブリックIPを無効化する

### Requirement 9: ファイルストレージ（Cloud Storage）

**User Story:** システム開発者として、地域資源に紐づくファイル（画像・PDF等）をCloud Storageに保存し、必要に応じて安全にアクセス可能にしたい。

#### Acceptance Criteria

1. WHEN ファイルがアップロードされる THEN システム SHALL 非公開のCloud Storageバケットにファイルを格納する（外部システムやCDNからの直接アクセスが必要な場合でも、バケットを公開設定にはせず、署名付きURLの発行によって対応する）
2. WHEN 利用者または外部システムにファイルへのアクセスを提供する THEN システム SHALL 有効期限付きの署名付きURLを発行する
3. WHEN ファイルアップロードが完了した THEN システム SHALL 対応するオブジェクトのURLを呼び出し元に返す

### Requirement 10: インフラのコード化（Terraform）

**User Story:** システム運用者として、すべてのGCPリソースをTerraformで宣言的に管理したい。それにより、インフラの再現性と変更履歴の追跡性を確保したい。

#### Acceptance Criteria

1. WHEN インフラが構築される THEN システム SHALL Cloud Run（アプリ本体サービス、推論サービス）、Cloud SQL for PostgreSQL、Cloud Storage、VPCコネクタ、IAM、Secret ManagerをTerraformコードとして定義する
2. WHEN Terraformコードが適用される THEN システム SHALL すべてのリソースをus-central1リージョンに作成する
3. WHEN シークレット（DB接続情報等）がTerraformで扱われる THEN システム SHALL Secret Managerを使用し、Terraformの状態ファイルに平文の認証情報を残さない

### Requirement 11: ドキュメント・コード規約

**User Story:** 開発チームとして、すべてのドキュメントとコードコメントを日本語・UTF-8・LF改行で統一したい。それにより、チーム内での可読性と一貫性を確保したい。

#### Acceptance Criteria

1. WHEN ソースコードにコメントまたはdocstringが記述される THEN システム SHALL 日本語で記述する
2. WHEN ファイルが保存される THEN システム SHALL 文字コードをUTF-8とする
3. WHEN ファイルが保存される THEN システム SHALL 改行コードをLFとする

### Requirement 12: セキュリティ（サービス間通信・入力検証）

**User Story:** システム運用者として、サービス間通信と外部からの入力を適切に保護したい。それにより、不正アクセスやインジェクション攻撃からシステムを守りたい。

#### Acceptance Criteria

1. WHEN アプリ本体サービスが推論サービスを呼び出す THEN システム SHALL Cloud RunのIAM認証（サービスアカウントの識別トークン）を使用する
2. WHEN データベースへのクエリが実行される THEN システム SHALL パラメータ化クエリを使用し、SQLインジェクションを防止する
3. WHEN 外部からの入力（位置情報、クエリ文字列、登録情報）を受け付ける THEN システム SHALL アプリ本体サービスの境界で検証を行う

### Requirement 13: 居抜き物件の検知・同期

**User Story:** 不動産・出店検討者として、Googleデータから閉店・廃業したスポットを自動的に検知したい。それにより、不動産屋も把握していない居抜き物件の情報を早期に得て出店コストを抑えたい。

#### Acceptance Criteria

1. WHEN 居抜き物件同期サービスが対象`place_id`群についてPlace Details APIを呼び出し、`business_status == CLOSED_PERMANENTLY`を検知した THEN システム SHALL 当該スポットを`VacantPropertyCandidate`として保存する
2. WHEN 同一`place_id`について同期処理が複数回実行される THEN システム SHALL `place_id`をキーとしたUPSERTにより、`vacant_property_candidates`テーブル内の該当レコードを常に1件のみに保つ
3. WHEN `business_status == CLOSED_PERMANENTLY`のスポットが検知される THEN システム SHALL Places APIが返す`types`（業種・ジャンルタグ配列）を当該レコードとともに保存する
4. IF 対象`place_id`に対するPlace Details API呼び出しが失敗（レート制限、APIキー無効、対象が存在しない等）した THEN システム SHALL 当該`place_id`の処理をスキップしエラーカウントに加算し、バッチ全体の処理は中断しない
5. WHILE `vacant_property_candidates`テーブルに既存レコードが存在する THEN システム SHALL Places APIの利用規約上の制約（`business_status`・`types`・レビュー等のフィールドは概ね30日程度で再取得が必要）を前提に、既存レコードを定期的にリフレッシュし`data_fetched_at`を更新する
6. WHERE 居抜き物件同期サービスがPlaces APIキーを利用する場合、THE システム SHALL Secret Managerで管理されたAPIキーを使用し、当該サービスにのみアクセス権限を付与する

### Requirement 14: 廃業時期の推定

**User Story:** 出店検討者として、閉店・廃業したスポットのおおよその廃業時期を知りたい。それにより、物件の現状（放置期間等）を把握する材料にしたい。

#### Acceptance Criteria

1. WHEN `CLOSED_PERMANENTLY`が検知されたスポットに`last_review_time`（最新レビュー投稿時刻）が存在する THEN システム SHALL `estimated_closure_period_start`に`last_review_time`を、`estimated_closure_period_end`に`data_fetched_at`（データ取得時刻）を設定する
2. IF `CLOSED_PERMANENTLY`が検知されたスポットに`last_review_time`が存在しない THEN システム SHALL 推定不能として`estimated_closure_period_start`と`estimated_closure_period_end`の両方をNoneとする
3. THE システム SHALL `data_fetched_at`が未来の時刻でないことを前提として廃業時期の推定を行う
4. WHEN `estimated_closure_period_start`と`estimated_closure_period_end`が共に非Noneである THEN システム SHALL `estimated_closure_period_start <= estimated_closure_period_end`が成立することを保証する

### Requirement 15: 居抜き物件の検索

**User Story:** 出店検討者として、位置・業種・ステータスで居抜き物件を検索したい。それにより、出店エリア・業種に合った物件を効率的に見つけたい。

#### Acceptance Criteria

1. WHEN 利用者が`location`、`radius_km > 0`、`business_status`、`limit >= 1`を含む居抜き物件検索リクエストを送信した THEN システム SHALL 条件に合致する`VacantPropertyCandidate`のリストを返す
2. WHEN 居抜き物件検索が実行される THEN システム SHALL 戻り値に含まれる全ての候補について、`location`との地理的距離が`radius_km`以下であることを保証する
3. WHEN 居抜き物件検索が実行される THEN システム SHALL 戻り値に含まれる全ての候補について、`business_status`が指定された値と一致することを保証する
4. WHERE 検索リクエストに業種タグ`types`が指定される場合、THE システム SHALL 戻り値に含まれる全ての候補について、当該候補の`types`と指定された`types`の積集合が空でないことを保証する
5. WHEN 検索対象件数が`limit`を超える THEN システム SHALL 戻り値の件数を`limit`以下に制限する
6. WHEN 居抜き物件検索が実行される THEN システム SHALL データベースに対して読み取り専用の操作のみを行い、データを変更しない

## Glossary

| 用語 | 説明 |
|---|---|
| GeoPoint | 緯度・経度で表される地理座標（EPSG:4326想定） |
| 地域資源 (RegionalResource) | 施設・イベント・支援制度等、地方創生に関連する情報の単位 |
| ハイブリッド検索 | PostGISによる地理空間フィルタリングでresource候補集合を絞り込み、その候補集合内でpgvectorによるベクトル類似度ソートを適用する、単一SQLクエリによる段階的フィルタリング検索手法 |
| embedding | テキストを固定次元の数値ベクトルに変換した表現。ベクトル検索の類似度計算に使用する |
| pgvector | PostgreSQLにベクトル型と類似検索機能を追加する拡張機能 |
| PostGIS | PostgreSQLに地理空間データ型とインデックス機能を追加する拡張機能 |
| google_ml_integration | Cloud SQL for PostgreSQLの拡張機能。SQL関数呼び出し（`google_ml.embedding(...)`相当）により、アプリケーション側での呼び出しを介さずデータベース側でテキストのembeddingを生成する |
| APIRun | アプリ本体サービス（Cloud Run上で稼働するPython製サービス）を指す設計上の呼称 |
| InferRun | 推論サービス（Cloud Run上でGemma 4 12B QATをGPU(L4)でホストするサービス）を指す設計上の呼称 |
| top_k | 検索・生成において取得または利用する上位件数を指定するパラメータ |
| place_id | Google Places APIが発行するスポットの一意識別子。無期限にキャッシュ可能であり、居抜き物件候補の重複防止・同一性判定のキーとして使用する |
| business_status | Places APIが返すスポットの営業状態を示すフィールド。`OPERATIONAL`（営業中）、`CLOSED_TEMPORARILY`（一時休業）、`CLOSED_PERMANENTLY`（完全閉店・廃業）のいずれかの値を取る |
| CLOSED_PERMANENTLY | `business_status`の値の一つ。スポットが完全に閉店・廃業したことを示す |
| types | Places APIが返す業種・ジャンルタグの配列（例: `["restaurant", "cafe"]`）。居抜き物件の業種による絞り込み検索に使用する |
| VacantPropertyCandidate（居抜き物件候補） | Places APIで`business_status == CLOSED_PERMANENTLY`が検知されたスポットを表すデータ単位。旧店舗名、位置情報、業種タグ、推定廃業時期レンジ等を含む |
| Places API（Google Maps Platform Places API / Place Details API） | Google Maps Platformが提供する、スポットの詳細情報（`business_status`、`types`、レビュー等）を取得するための外部API |

## Design Reference

本要件は`design.md`の以下の対応関係に基づいて導出された。

| Requirement | 対応する設計要素 |
|---|---|
| 1 | フロー1（相談応答）、`generate_consultation_response()` |
| 2 | `search_nearby_resources()`、Correctness Property 1-3 |
| 3 | `search_similar_resources()`、Correctness Property 4-5 |
| 4 | `hybrid_search()`（段階的フィルタリング方式）、Correctness Property 6-7, 11 |
| 5 | フロー2（地域資源登録）、`register_resource()`、Correctness Property 8-9 |
| 6 | `GeoPoint`データモデル、Correctness Property 10 |
| 7 | コンポーネント2（InferRun）、Performance/Security Considerations |
| 8 | コンポーネント3（Cloud SQL）、スキーマ概要 |
| 9 | コンポーネント4（Cloud Storage）、Security Considerations |
| 10 | コンポーネント5（Terraform）、Dependencies |
| 11 | Overview記載のドキュメント規約 |
| 12 | Security Considerations |
| 13 | コンポーネント5（VacantPropertySyncService）、フロー3（居抜き物件の同期・検知）、`sync_vacant_properties()`、`upsert_by_place_id()`、Correctness Property 12、エラーシナリオ6・7 |
| 14 | `estimate_closure_period()`、Correctness Property 16 |
| 15 | フロー4（居抜き物件の検索）、`search_vacant_properties()`、Correctness Property 13-15 |

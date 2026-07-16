# 居抜き物件発見機能

## 背景・目的

「不動産屋も知らない居抜き物件をGoogleデータから探し出し、出店コストを大幅に下げる」ことを目的とした機能です。Google Maps Platform Places API（Place Details API）を活用し、閉店・廃業したスポットを自動検知して蓄積・検索できるようにします。

## 仕組みの概要

1. **検知**: Places APIの`business_status`フィールドが`CLOSED_PERMANENTLY`（完全閉店・廃業）であるスポットを検知する。
2. **誤情報対策**: 同じ場所に新しい店ができた場合、Google側で古い店の情報は表示されなくなる仕組みを利用し、誤情報のリスクを抑える。取得したスポットの`place_id`をDBのキーとして保持し、再取得時の同一性判定・重複防止に用いる。
3. **業種情報**: Places APIが返す`types`配列（例: `["restaurant", "cafe"]`）をDBに格納し、業種による絞り込み検索を可能にする。
4. **廃業時期の推定**: Places APIには廃業時期そのものを返す項目がないため、データ取得時刻とレビューの最新更新日時から推定レンジを算出する。

## データモデル

`src/regional_revitalization/vacant_property.py`に実装されています。

### BusinessStatus（Enum）

```python
class BusinessStatus(str, Enum):
    OPERATIONAL = "OPERATIONAL"          # 営業中
    CLOSED_TEMPORARILY = "CLOSED_TEMPORARILY"  # 一時休業
    CLOSED_PERMANENTLY = "CLOSED_PERMANENTLY"  # 完全閉店・廃業
```

### VacantPropertyCandidate（居抜き物件候補）

| フィールド | 型 | 説明 |
|---|---|---|
| `place_id` | str | Google Places APIのPlace ID（一意識別子、空文字列不可） |
| `name` | str | 旧店舗名（空文字列不可） |
| `location` | GeoPoint | 位置情報 |
| `business_status` | BusinessStatus | 営業状態 |
| `types` | list[str] | 業種・ジャンルタグ配列（空リスト可、Noneは不可） |
| `address` | str \| None | 住所 |
| `phone_number` | str \| None | 電話番号 |
| `data_fetched_at` | datetime | データ取得時刻（未来の時刻は不可） |
| `last_review_time` | datetime \| None | 最新レビューの投稿時刻 |
| `estimated_closure_period_start` | datetime \| None | 推定廃業時期レンジの開始 |
| `estimated_closure_period_end` | datetime \| None | 推定廃業時期レンジの終了 |

**検証ルール**（`__post_init__`で検証、違反時は`ValueError`）:

- `place_id`・`name`は空文字列不可
- `types`はNone不可（空リストは可）
- `last_review_time`がNoneの場合、`estimated_closure_period_start`/`end`は共にNone
- `estimated_closure_period_start`と`end`が共に非Noneの場合、`start <= end`
- `data_fetched_at`は未来の時刻であってはならない

## 廃業時期の推定ロジック

`estimate_closure_period(data_fetched_at, last_review_time)`関数（`vacant_property.py`）で実装されています。

```python
def estimate_closure_period(
    data_fetched_at: datetime, last_review_time: datetime | None
) -> tuple[datetime | None, datetime | None]:
    if last_review_time is None:
        return None, None
    return last_review_time, data_fetched_at
```

**考え方**: 「最終確認時点でまだ営業中だった可能性が高い時期」の推定レンジを返します。厳密な廃業日ではなく、代理データ（データ取得時刻・最新レビュー時刻）からの推定レンジとして扱います。

- レビューが存在する場合: `estimated_closure_period_start = last_review_time`、`estimated_closure_period_end = data_fetched_at`。つまり「最後にレビューが投稿された時点」から「`CLOSED_PERMANENTLY`を検知した時点」までの間に廃業した可能性が高いと推定する。
- レビューが存在しない場合: 推定不能として`(None, None)`を返す。

## 同期処理（sync_vacant_properties）

`sync_vacant_properties(places_api_client, vacant_property_repository, target_place_ids)`関数（`vacant_property.py`）が中核ロジックです。

```python
def sync_vacant_properties(
    places_api_client: PlacesApiClient,
    vacant_property_repository: VacantPropertyRepository,
    target_place_ids: list[str],
) -> SyncResult:
    ...
```

**処理内容**:

1. 対象`place_id`ごとにPlace Details APIを呼び出す。
2. API呼び出しが失敗した場合、当該`place_id`をスキップし`error_count`に加算する（**部分失敗許容**。1件の失敗でバッチ全体を中断しない）。
3. `business_status == CLOSED_PERMANENTLY`を検知した場合、廃業時期を推定して`VacantPropertyCandidate`を構築し、`place_id`をキーとしたUPSERTでDBに保存する。
4. 最終的に`SyncResult(processed_count, detected_closure_count, error_count)`を返す。

**冪等性**: 同一`place_id`について本処理を複数回実行しても、`vacant_property_candidates`テーブル内の該当レコードは常に1件のみに保たれます（UPSERTによる）。

## Places API利用規約上の制約（重要）

Google Places APIの利用規約には以下の制約があります。

- **Place ID**: 無期限にキャッシュ可能。
- **`business_status`・`types`・レビュー等のその他のフィールド**: 概ね**30日程度**で再取得（リフレッシュ）が必要。

この制約を前提に、居抜き物件同期サービスは新規スポットの発掘だけでなく、既存の`vacant_property_candidates`レコード（監視対象スポット）についても定期的にPlace Details APIを再呼び出しし、`data_fetched_at`を更新するリフレッシュ処理を兼ねる設計になっています。

**運用上の注意**: Cloud Schedulerの実行頻度（例: 日次）は、監視対象place_id数とAPIのレート制限・コストのバランスを見て調整し、全対象レコードが30日以内に再取得されるようにスケジュール設計・監視を行ってください。

## 検索機能（search_vacant_properties）

`search_vacant_properties(vacant_property_repository, location, radius_km, business_status, types, limit)`関数（`vacant_property.py`）で、位置・任意の営業状態・業種タグによる絞り込み検索を提供します。`business_status=None`では営業状態を問わず検索します。HTTP API経由での利用は[api-reference.md](./api-reference.md)の`POST /vacant-properties/search`を参照してください。

**検証される正当性（Property-Based Testingで検証済み）**:

- 戻り値の全候補について、指定した位置からの距離が`radius_km`以下であること（地理的整合性）
- 戻り値の全候補について、`business_status`が指定値と一致すること
- `types`が指定されている場合、戻り値の全候補について候補の`types`と指定`types`の積集合が空でないこと
- 戻り値の件数が`limit`以下であること
- データベースに対して読み取り専用の操作のみを行うこと（副作用なし）

## Cloud Run Jobsとしての運用

居抜き物件同期サービスは、Cloud SchedulerによってトリガーされるCloud Run Jobsとして実行されます。エントリポイントは`src/regional_revitalization/vacant_property_sync_job.py`の`main()`です。

**必要な環境変数**:

| 環境変数 | 説明 |
|---|---|
| `DB_CONNECTION_JSON` | DB接続情報（host/port/database/user/password）のJSON文字列。Secret Manager経由でマウント |
| `PLACES_API_KEY` | Places APIキー。Secret Manager経由でマウント |
| `GCP_PROJECT_ID` | GCPプロジェクトID |
| `TARGET_PLACE_IDS` | 同期対象の`place_id`をカンマ区切りで連結した文字列 |

Places APIキーは、Terraform側の`secret_key_ref`設定によりSecret Managerから自動的に環境変数へマウントされます。アプリケーションコード側で明示的にSecret Manager APIを呼び出す必要は基本的にありません（フォールバック経路として`PLACES_API_KEY_SECRET_NAME`を指定した直接取得も用意されています）。

**ローカルでの実行例**:

```bash
export DB_CONNECTION_JSON='{"host":"localhost","port":5432,"database":"regional_revitalization","user":"app_user","password":"..."}'
export PLACES_API_KEY="your-places-api-key"
export GCP_PROJECT_ID="your-project-id"
export TARGET_PLACE_IDS="ChIJ_xxxxx1,ChIJ_xxxxx2,ChIJ_xxxxx3"

python -m regional_revitalization.vacant_property_sync_job
```

## セキュリティ上の考慮事項

- `vacant_property_candidates`に格納する旧店舗名・住所・電話番号等は、廃業済みスポットの事業者情報です。検索結果には`business_status`・`data_fetched_at`を明示し、誤って営業中の情報として利用されないようにする表示仕様を徹底してください。
- Places APIキーへのアクセス権限は、居抜き物件同期サービスの実行用サービスアカウントにのみ付与されます（Terraform: `terraform/modules/cloudrun_jobs_vacant_property_sync/main.tf`）。APIRun・InferRunのサービスアカウントには付与されません。

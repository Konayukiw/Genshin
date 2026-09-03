# Genshin Database

原神のキャラクター / 武器 / 聖遺物 / 任務データを収録した、非公式のファン制作データベースです。
データは英語/日本語/中国語簡体の3言語を含み、Cloudflare Workers + R2 上で API として配信されます。

> Game content and data © HoYoverse / Cognosphere.
> Unofficial fan project - not affiliated with or endorsed by HoYoverse.

## リポジトリ構成

```
genshin/
├── data/v1/                  # API 配信用データ
├── source/                   # 生データ
├── scripts/
│   ├── recover_quest_ids.py  # 生スクレイプから ID を復元
│   ├── build_index.py        # API 配信用データを構築
│   ├── validate.py           # 検証
│   └── maps/                 # 生成された ID 対応表
├── worker/                   # Cloudflare Worker
└── .github/workflows/        # R2 同期
```

## API

| エンドポイント | 内容 |
|---|---|
| `GET /` | ブラウザ向けエクスプローラー (HTML)。言語→カテゴリ→項目のツリーを展開して JSON を閲覧・検索できる。`Accept: text/html` を送らないクライアントや `/?json` 指定時は従来どおりの JSON を返す |
| `GET /v1` | マニフェスト (`data_version`, カテゴリ別件数) |
| `GET /v1/(locale)` | API インデックス |
| `GET /v1/(locale)/(category)` | キャラクター一覧 (`characters` / `weapons` / `artifacts`) |
| `GET /v1/(locale)/(category)/(slug)` | 個別データ |
| `GET /v1/(locale)/quests` | 任務一覧 |
| `GET /v1/(locale)/quests/(type)` | 任務一覧 (`archon` / `story` / `world` / `event` / `hangout`) |
| `GET /v1/(locale)/quests/(type)/(slug)` | 個別クエスト |
| `GET /v1/icons` | キャラクターアイコン一覧 |

- すべてのレスポンスに `Access-Control-Allow-Origin: *` (CORS) を付与
- `data_version` は `data/` 更新のたびに変わるため、クライアントは `/v1` を見て更新を検知
- `ETag` / `If-None-Match` で 304 応答に対応

## ID について

- **キャラクター / 武器 / 聖遺物** … (`"id"`)。全言語共通。
  API で配信されるファイル名も全言語で同一 (例: `/v1/ja/characters/hutao.json`)。
- **任務** … 任務 ID を復元して付与 (`q-12345` / `ch-2001` / `ch-2001-2`)。
  復元できないものは `"id": null`。任務名はロケールごとの固有名。
- ID対応表は `scripts/maps/` にコミットされているため、`_tmp/` がなくても再ビルド可能。

## データ更新フロー

```
1. 取得 & 生データを更新
2. python scripts/recover_quest_ids.py   # 生データからID復元
3. python scripts/build_index.py         # data/v1/ 再生成
4. python scripts/validate.py            # 検証
5. git commit & push                     # data/ の変更を Actions が R2 へ同期
```

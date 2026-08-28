# Genshin DB (Unofficial)

原神のキャラクター / 武器 / 聖遺物 / 任務データを収録した、非公式のファン制作データベースです。
データは en / ja / zh の3言語を収め、Cloudflare Workers + R2 上で JSON API として配信されます。

> Game content and data © HoYoverse / Cognosphere.
> Unofficial fan project — not affiliated with or endorsed by HoYoverse.

## リポジトリ構成

```
genshin/
├── data/v1/                  # ビルド済みデータ + index (R2へ同期される)
├── source/                   # 生データ (En / Ja / Zh)
├── scripts/
│   ├── recover_quest_ids.py  # 生スクレイプからwiki IDを復元 (_tmp/ が必要)
│   ├── build_index.py        # data/v1/ を生成 (LUNABASE ID + index)
│   ├── validate.py           # 検証
│   └── maps/                 # 生成されたID対応表 (コミット対象)
├── worker/                   # Cloudflare Worker (API)
└── .github/workflows/        # R2同期
```

## API

| エンドポイント | 内容 |
|---|---|
| `GET /v1` | マニフェスト (`data_version`, カテゴリ別件数) |
| `GET /v1/:locale` | ロケールインデックス |
| `GET /v1/:locale/:category` | 一覧 (`characters` / `weapons` / `artifacts`) |
| `GET /v1/:locale/:category/:slug` | 個別データ |
| `GET /v1/:locale/quests` | クエストタイプ一覧 |
| `GET /v1/:locale/quests/:type` | クエスト一覧 (`archon` / `story` / `world` / `event` / `hangout`) |
| `GET /v1/:locale/quests/:type/:slug` | 個別クエスト |

- すべてのレスポンスに `Access-Control-Allow-Origin: *` (CORS) を付与
- `data_version` は `data/` 更新のたびに変わるため、クライアントは `/v1` を見て更新を検知
- `ETag` / `If-None-Match` で 304 応答に対応

## ID について

- **characters / weapons / artifacts** … LUNABASE の数値 ID (`"id"`)。全言語共通。
  ファイル名 (slug) も全言語で同一 (例: `/v1/ja/characters/albedo.json`)。
- **quests** … Honey Hunter Wiki の数値 ID を復元して付与 (`q-12345` / `ch-2001` / `ch-2001-2`)。
  復元できないものは `"id": null`。クエストの slug はロケールごとの固有名。
- ID対応表は `scripts/maps/` にコミットされているため、`_tmp/` がなくても再ビルド可能。

## データ更新フロー

```
1. スクレイプ → source/ を更新
2. python scripts/recover_quest_ids.py   # _tmp/ の生データからID復元
3. python scripts/build_index.py         # data/v1/ 再生成
4. python scripts/validate.py            # 検証
5. git commit & push                     # data/ が変わっていれば Actions が R2 へ同期
```

Worker の再デプロイはデータ更新時には不要です (Workerコード変更時のみ)。

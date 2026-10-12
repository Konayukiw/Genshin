# Genshin Database

原神のキャラクター / 武器 / 聖遺物 / 任務データを収録した、非公式のファン制作データベースです。
データは英語/日本語/中国語簡体の3言語を含み、Cloudflare Workers + R2 上で API として配信されます。

> Game content and data © HoYoverse / Cognosphere.
> Unofficial fan project - not affiliated with or endorsed by HoYoverse.

## リポジトリ構成

```
genshin/
├── data/v1/                  # API 配信データ (唯一の正データ。R2 に同期される)
│   ├── index.json            # マニフェスト (data_version, 件数)
│   ├── icons/                # キャラアイコン (<en slug>.png) + index.json
│   └── {en,ja,zh}/           # characters / weapons / artifacts / quests/<type>
├── scripts/
│   ├── build_index.py        # data/v1 から index.json 群を再生成
│   ├── validate.py           # 検証
│   └── fetch_lunabase.py     # LUNABASE を _tmp/ に取得して差分表示
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
  API で配信されるファイル名も全言語で同一 (例: `/v1/ja/characters/hu-tao.json`)。
- **任務** … 任務 ID を復元して付与 (`q-12345` / `ch-2001` / `ch-2001-2`)。
  復元できないものは `"id": null`。任務名はロケールごとの固有名。
- ID は各 JSON の `"id"` に直接入っている (別の対応表はない)。

## データ更新フロー

`data/v1/` が唯一の正データ。生データ (`source/`) や ID 復元スクリプトは廃止済み (git 履歴には残っている)。

```
1. data/v1/<locale>/... の JSON を追加・編集
2. python scripts/build_index.py    # index.json 群とマニフェストを再生成 (ファイルは削除しない)
3. python scripts/validate.py       # 検証
4. git commit & push                # data/ の変更を Actions が R2 へ同期
```

- **キャラ / 武器 / 聖遺物**: ファイル名は en 名の slug で全言語共通 (`hu-tao.json`)。`"id"` は LUNABASE の ID。
  `python scripts/fetch_lunabase.py` で LUNABASE を `_tmp/LUNABASE` に取得し、API に無いエントリを一覧できる
  (要 `gh auth login`、`lunnoa1013/LUNABASE-Simulator` のコラボレーター権限)。
- **任務**: `"id"` は Honey Hunter World の任務 ID (`q-xxxxx`)。不明なら `null`。
  取得元の Honey Hunter World はサービス終了済み、スクレイパーも残っていないため、新しい任務の取得元は未定。
- **アイコン**: `data/v1/icons/<en の slug>.png` を置けば `build_index.py` が `icons/index.json` に載せる。
- index の並び順は維持され、新しいファイルは末尾に slug 順で追加される。

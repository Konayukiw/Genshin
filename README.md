# Genshin Database

## Genshin Impact database API.

Languages: English / 日本語 / 中文簡体
Contents: Characters, Weapons, Artifacts, Stories

> Game content and data © HoYoverse / Cognosphere.
> Unofficial fan project - not affiliated with or endorsed by HoYoverse.

## Directory 

```
Genshin/
├── data/v1/                  # Streaming API datas
│   ├── index.json            # Manifest (Data version, contents counts)
│   ├── icons/                # Character icons (<Slug>.png) + index.json
│   └── {en,ja,zh}/           # characters / weapons / artifacts / quests/<type>/
├── scripts/
│   ├── build_index.py        # Biuld all of index.json from data/v1/.
│   ├── validate.py           # Verify database.
│   └── fetch_lunabase.py     # Fetch LUNABASE datas to _tmp/.
├── worker/                   # Cloudflare Worker
└── .github/workflows/        # Sync R2, deploy to `(Genshin)[https://genshin.konayuki.xyz]`
```

## API

| Endpoint | Content |
|---|---|
| `GET /` | API Interface (HTML). Repond /v1 datas json for clients, bots. |
| `GET /v1` | Manifest (`data_version`, contents counts) |
| `GET /v1/(locale)` | API index |
| `GET /v1/(locale)/(category)` | `characters` / `weapons` / `artifacts` |
| `GET /v1/(locale)/(category)/(slug)` | Details for each contents |
| `GET /v1/(locale)/quests` | Quests |
| `GET /v1/(locale)/quests/(type)` | `archon` / `story` / `world` / `event` / `hangout` |
| `GET /v1/(locale)/quests/(type)/(slug)` | Details for each quests |
| `GET /v1/icons` | Character icons |

- Add `Access-Control-Allow-Origin: *` (CORS) for every response.
- Clients should detect updates from `/v1` changes.
- 304 response is supported from `ETag` / `If-None-Match`.

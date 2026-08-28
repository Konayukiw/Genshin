/**
 * Genshin Database API — Cloudflare Worker
 *
 * Serves data/v1/** from a private R2 bucket (binding: DATA) with
 * version-keyed edge caching: the manifest's data_version is part of every
 * cache key, so a data push invalidates the API globally without purges.
 *
 * Routes:
 *   GET /v1                                  -> manifest (data_version, counts, ...)
 *   GET /v1/:locale                          -> locale index
 *   GET /v1/:locale/:category                -> category index
 *   GET /v1/:locale/quests/:type             -> quest-type index
 *   GET /v1/:locale/:category/:slug          -> entity JSON
 *   GET /v1/:locale/quests/:type/:slug       -> quest JSON
 */

export interface Env {
  DATA: R2Bucket;
}

const LOCALES = new Set(["en", "ja", "zh"]);
const CATEGORIES = new Set(["characters", "weapons", "artifacts"]);
const QUEST_TYPES = new Set(["archon", "story", "world", "event", "hangout"]);

const CORS: Record<string, string> = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
  "Access-Control-Allow-Headers": "If-None-Match",
  "Access-Control-Max-Age": "86400",
};

function json(obj: unknown, status = 200, extra: Record<string, string> = {}): Response {
  const body = JSON.stringify(obj, null, 2) + "\n";
  return new Response(status === 204 ? null : body, {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", ...CORS, ...extra },
  });
}

function err(status: number, code: string, message: string): Response {
  return json({ error: { code, message } }, status);
}

async function dataVersion(env: Env, ctx: ExecutionContext): Promise<string> {
  const cacheKey = new Request("https://__meta.local__/data_version");
  const cache = caches.default;
  const cached = await cache.match(cacheKey);
  if (cached) return cached.text();
  let version = "";
  try {
    const obj = await env.DATA.get("v1/index.json");
    if (obj) {
      const manifest = (await obj.json()) as { data_version?: string };
      version = String(manifest.data_version ?? "");
    }
  } catch {
  }
  const res = new Response(version, { headers: { "Cache-Control": "max-age=60" } });
  ctx.waitUntil(cache.put(cacheKey, res.clone()));
  return version;
}

async function serveKey(
  env: Env,
  ctx: ExecutionContext,
  request: Request,
  key: string,
  manifest = false,
): Promise<Response> {
  const url = new URL(request.url);
  const version = await dataVersion(env, ctx);
  const cacheKey = new Request(`${url.origin}${url.pathname}?v=${version}`);
  const cache = caches.default;
  const cached = await cache.match(cacheKey);
  if (cached) {
    return request.method === "HEAD" ? new Response(null, cached) : cached;
  }

  const etag = `"${version}"`;
  if (!manifest && version && request.headers.get("If-None-Match") === etag) {
    return new Response(null, { status: 304, headers: { ETag: etag, ...CORS } });
  }

  const obj = await env.DATA.get(key);
  if (!obj) {
    return err(404, "not_found", `No data at ${url.pathname}`);
  }

  const headers: Record<string, string> = {
    "Content-Type": "application/json; charset=utf-8",
    "Cache-Control": manifest ? "public, max-age=60" : "public, max-age=86400",
    ETag: etag,
    ...CORS,
  };
  const res = new Response(obj.body, { headers });
  ctx.waitUntil(cache.put(cacheKey, res.clone()));
  return request.method === "HEAD" ? new Response(null, { headers }) : res;
}

export default {
  async fetch(request, env, ctx): Promise<Response> {
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: CORS });
    }
    if (request.method !== "GET" && request.method !== "HEAD") {
      return err(405, "method_not_allowed", "Only GET / HEAD / OPTIONS are supported");
    }

    const url = new URL(request.url);
    const parts = url.pathname.split("/").filter(Boolean);

    if (parts.length === 0) {
      return json({
        name: "Genshin DB API",
        endpoints: {
          manifest: "/v1",
          locale: "/v1/{locale}",
          category: "/v1/{locale}/{category}",
          entity: "/v1/{locale}/{category}/{slug}",
          quests: "/v1/{locale}/quests/{quest_type}",
          quest: "/v1/{locale}/quests/{quest_type}/{slug}",
        },
        locales: [...LOCALES],
        categories: [...CATEGORIES, "quests"],
        quest_types: [...QUEST_TYPES],
      });
    }
    if (parts[0] !== "v1") {
      return err(404, "not_found", "Unknown API root; start at /v1");
    }
    if (parts.length === 1) {
      return serveKey(env, ctx, request, "v1/index.json", true);
    }

    const locale = parts[1];
    if (!LOCALES.has(locale)) {
      return err(404, "unknown_locale", `Locale '${locale}' is not one of: en, ja, zh`);
    }

    if (parts.length === 2) {
      return serveKey(env, ctx, request, `v1/${locale}/index.json`);
    }

    const category = parts[2];
    if (category === "quests") {
      if (parts.length === 3) {
        return serveKey(env, ctx, request, `v1/${locale}/quests/index.json`);
      }
      const qtype = parts[3];
      if (!QUEST_TYPES.has(qtype)) {
        return err(404, "unknown_quest_type",
          `Quest type '${qtype}' is not one of: ${[...QUEST_TYPES].join(", ")}`);
      }
      if (parts.length === 4) {
        return serveKey(env, ctx, request, `v1/${locale}/quests/${qtype}/index.json`);
      }
      return serveKey(env, ctx, request, `v1/${locale}/quests/${qtype}/${parts[4]}.json`);
    }
    if (CATEGORIES.has(category)) {
      if (parts.length === 3) {
        return serveKey(env, ctx, request, `v1/${locale}/${category}/index.json`);
      }
      return serveKey(env, ctx, request, `v1/${locale}/${category}/${parts[3]}.json`);
    }
    return err(404, "unknown_category",
      `Category '${category}' is not one of: ${[...CATEGORIES, "quests"].join(", ")}`);
  },
} satisfies ExportedHandler<Env>;



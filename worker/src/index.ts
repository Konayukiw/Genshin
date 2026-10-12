import EXPLORER_HTML from "./explorer.html";

export interface Env {
  DATA: R2Bucket;
}

const LOCALES = new Set(["en", "ja", "zh"]);
const CATEGORIES = new Set(["characters", "weapons", "artifacts"]);
const QUEST_TYPES = new Set(["archon", "story", "world", "event", "hangout"]);
const ICON_IMAGE_TYPES: Record<string, string> = {
  png: "image/png",
  webp: "image/webp",
  jpg: "image/jpeg",
  jpeg: "image/jpeg",
  gif: "image/gif",
  svg: "image/svg+xml",
};

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

async function serveIcon(
  env: Env,
  ctx: ExecutionContext,
  request: Request,
  key: string,
  contentType: string,
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
  if (version && request.headers.get("If-None-Match") === etag) {
    return new Response(null, { status: 304, headers: { ETag: etag, ...CORS } });
  }

  const obj = await env.DATA.get(key);
  if (!obj) {
    return err(404, "not_found", `No icon at ${url.pathname}`);
  }

  const headers: Record<string, string> = {
    "Content-Type": contentType,
    "Cache-Control": "public, max-age=604800",
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
    const parts = url.pathname
      .split("/")
      .filter(Boolean)
      .map((p) => {
        try {
          return decodeURIComponent(p);
        } catch {
          return p;
        }
      });

    if (parts.length === 0) {
      const accept = request.headers.get("Accept") ?? "";
      if (!url.searchParams.has("json") && accept.includes("text/html")) {
        return new Response(EXPLORER_HTML, {
          headers: {
            "Content-Type": "text/html; charset=utf-8",
            "Cache-Control": "public, max-age=300",
            ...CORS,
          },
        });
      }
      return json({
        name: "Genshin Database API",
        endpoints: {
          manifest: "/v1",
          locale: "/v1/{locale}",
          category: "/v1/{locale}/{category}",
          entity: "/v1/{locale}/{category}/{slug}",
          quests: "/v1/{locale}/quests/{quest_type}",
          quest: "/v1/{locale}/quests/{quest_type}/{slug}",
        },
        locales: [...LOCALES],
        categories: [...CATEGORIES, "quests", "icons"],
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
    if (locale === "icons") {
      if (parts.length === 2) {
        return serveKey(env, ctx, request, "v1/icons/index.json");
      }
      const file = parts.slice(2).join("/");
      const ext = file.includes(".") ? file.split(".").pop()!.toLowerCase() : "";
      const imageType = ICON_IMAGE_TYPES[ext];
      if (!imageType || file !== parts[parts.length - 1]) {
        return err(404, "not_found", `No icon at ${url.pathname}`);
      }
      return serveIcon(env, ctx, request, `v1/icons/${file}`, imageType);
    }
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
      return serveKey(env, ctx, request,
        `v1/${locale}/quests/${qtype}/${parts[4].replace(/\.json$/, "")}.json`);
    }
    if (CATEGORIES.has(category)) {
      if (parts.length === 3) {
        return serveKey(env, ctx, request, `v1/${locale}/${category}/index.json`);
      }
      return serveKey(env, ctx, request,
        `v1/${locale}/${category}/${parts[3].replace(/\.json$/, "")}.json`);
    }
    return err(404, "unknown_category",
      `Category '${category}' is not one of: ${[...CATEGORIES, "quests"].join(", ")}`);
  },
} satisfies ExportedHandler<Env>;



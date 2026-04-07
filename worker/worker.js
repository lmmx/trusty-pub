export default {
  async fetch(request, env) {
    if (request.method === "OPTIONS") {
      return new Response(null, { headers: corsHeaders(env.ALLOWED_ORIGIN) });
    }

    if (new URL(request.url).pathname === "/token" && request.method === "POST") {
      return handleTokenExchange(request, env);
    }

    return new Response("Not found", { status: 404 });
  },
};

async function handleTokenExchange(request, env) {
  if (request.headers.get("Origin") !== env.ALLOWED_ORIGIN) {
    return new Response("Forbidden", { status: 403 });
  }

  const { code } = await request.json();
  if (!code) {
    return new Response(JSON.stringify({ error: "missing code" }), {
      status: 400,
      headers: { ...corsHeaders(env.ALLOWED_ORIGIN), "Content-Type": "application/json" },
    });
  }

  const ghResponse = await fetch("https://github.com/login/oauth/access_token", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({
      client_id: env.GITHUB_CLIENT_ID,
      client_secret: env.GITHUB_CLIENT_SECRET,
      code,
    }),
  });

  const data = await ghResponse.json();

  return new Response(JSON.stringify(data), {
    headers: { ...corsHeaders(env.ALLOWED_ORIGIN), "Content-Type": "application/json" },
  });
}

function corsHeaders(origin) {
  return {
    "Access-Control-Allow-Origin": origin,
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
  };
}
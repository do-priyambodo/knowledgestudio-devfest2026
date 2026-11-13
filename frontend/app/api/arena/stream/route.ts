import { buildBackendHeaders, resolveBackendOrigin } from "@/lib/backend";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(req: Request): Promise<Response> {
  let bodyText = "";
  try {
    bodyText = await req.text();
  } catch {
    return Response.json({ detail: "Invalid request payload." }, { status: 400 });
  }

  try {
    const upstream = await fetch(`${resolveBackendOrigin()}/api/v1/agent/arena-stream`, {
      method: "POST",
      headers: {
        ...buildBackendHeaders(),
        Accept: "text/event-stream",
      },
      body: bodyText,
      cache: "no-store",
    });

    if (!upstream.ok || !upstream.body) {
      const errBody = await upstream.text().catch(() => "");
      return Response.json(
        { detail: errBody || `Upstream error (${upstream.status}).` },
        { status: upstream.status || 502 },
      );
    }

    return new Response(upstream.body, {
      status: 200,
      headers: {
        "Content-Type": "text/event-stream; charset=utf-8",
        "Cache-Control": "no-cache, no-transform",
        Connection: "keep-alive",
        "X-Accel-Buffering": "no",
      },
    });
  } catch {
    return Response.json(
      {
        detail:
          "Verification halted — upstream BigQuery or Knowledge Catalog service did not respond.",
      },
      { status: 502 },
    );
  }
}

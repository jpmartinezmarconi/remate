const renderEndpoint = process.env.REMINDER_ENDPOINT_URL;
const triggerSecret = process.env.REMINDER_TRIGGER_SECRET;

export default {
  async fetch(request) {
    if (request.method !== "POST") {
      return Response.json({ error: "Method not allowed." }, { status: 405 });
    }

    if (!request.headers.get("x-neon-trigger-invocation-id")) {
      return Response.json({ error: "Trigger invocation required." }, { status: 403 });
    }

    if (!renderEndpoint || !triggerSecret) {
      console.error("Reminder function environment is not configured.");
      return Response.json({ error: "Function is not configured." }, { status: 500 });
    }

    const endpointUrl = new URL(renderEndpoint);
    if (endpointUrl.protocol !== "https:") {
      console.error("Reminder endpoint must use HTTPS.");
      return Response.json({ error: "Function is not configured." }, { status: 500 });
    }

    let payload;
    try {
      payload = await request.json();
    } catch {
      return Response.json({ error: "Invalid JSON payload." }, { status: 400 });
    }

    const scheduledAt = payload?.data?.scheduled_at;
    if (typeof scheduledAt !== "string") {
      return Response.json({ error: "Missing scheduled_at." }, { status: 400 });
    }

    const response = await fetch(endpointUrl, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${triggerSecret}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ scheduled_at: scheduledAt }),
      signal: AbortSignal.timeout(60_000),
    });

    if (!response.ok) {
      console.error(`Reminder endpoint returned HTTP ${response.status}.`);
      return Response.json({ error: "Reminder processing failed." }, { status: 502 });
    }

    return Response.json({ ok: true, scheduled_at: scheduledAt });
  },
};

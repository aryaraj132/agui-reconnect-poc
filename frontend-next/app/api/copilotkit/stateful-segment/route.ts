import {
  CopilotRuntime,
  EmptyAdapter,
  copilotRuntimeNextJSAppRouterEndpoint,
} from "@copilotkit/runtime";
import { LangGraphHttpAgent } from "@copilotkit/runtime/langgraph";

const BACKEND_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";

const runtime = new CopilotRuntime({
  agents: {
    default: new LangGraphHttpAgent({
      url: `${BACKEND_URL}/api/v1/stateful-segment`,
      description: "Stateful segment generation agent (checkpointer-only)",
    }),
  },
});

export const POST = async (req: Request) => {
  const body = await req.json();

  // Intercept agent/connect and proxy directly to the backend.
  if (body.method === "agent/connect") {
    const threadId = body.body?.threadId ?? body.params?.threadId;
    const runId = body.body?.runId ?? crypto.randomUUID();

    const backendResp = await fetch(`${BACKEND_URL}/api/v1/stateful-segment`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        thread_id: threadId,
        run_id: runId,
        messages: body.body?.messages ?? [],
        metadata: { requestType: "connect" },
      }),
    });

    return new Response(backendResp.body, {
      status: backendResp.status,
      headers: {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        Connection: "keep-alive",
      },
    });
  }

  // Non-connect requests — pass to CopilotKit handler
  const newReq = new Request(req.url, {
    method: req.method,
    headers: req.headers,
    body: JSON.stringify(body),
  });

  const { handleRequest } = copilotRuntimeNextJSAppRouterEndpoint({
    runtime,
    serviceAdapter: new EmptyAdapter(),
    endpoint: "/api/copilotkit/stateful-segment",
  });
  return handleRequest(newReq);
};

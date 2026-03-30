const path = require("path");
const HtmlWebpackPlugin = require("html-webpack-plugin");
const webpack = require("webpack");

module.exports = {
  entry: "./src/index.tsx",
  output: {
    path: path.resolve(__dirname, "dist"),
    filename: "bundle.[contenthash].js",
    publicPath: "/",
    clean: true,
  },
  resolve: {
    extensions: [".tsx", ".ts", ".js"],
    alias: {
      "@": path.resolve(__dirname, "src"),
      // Force CJS so @ag-ui/client's `import *` gets applyPatch at top level
      "fast-json-patch": path.resolve(__dirname, "node_modules/fast-json-patch/index.js"),
    },
  },
  module: {
    rules: [
      {
        test: /\.tsx?$/,
        use: "ts-loader",
        exclude: /node_modules/,
      },
      {
        test: /\.css$/,
        use: ["style-loader", "css-loader", "postcss-loader"],
      },
    ],
  },
  plugins: [
    new HtmlWebpackPlugin({
      template: "./public/index.html",
    }),
    new webpack.DefinePlugin({
      "process.env.BACKEND_URL": JSON.stringify(
        process.env.BACKEND_URL || "http://localhost:8000"
      ),
      "process.env.COPILOT_RUNTIME_URL": JSON.stringify(
        process.env.COPILOT_RUNTIME_URL || "/copilotkit"
      ),
      "process.env.COPILOT_STATEFUL_RUNTIME_URL": JSON.stringify(
        process.env.COPILOT_STATEFUL_RUNTIME_URL || "/copilotkit-stateful"
      ),
    }),
  ],
  devServer: {
    port: 3000,
    hot: true,
    historyApiFallback: true,
    open: false,
    setupMiddlewares: (middlewares, devServer) => {
      // Embed CopilotRuntime in the dev server — no separate process needed.
      // Dynamic import because @copilotkit/runtime is ESM.
      (async () => {
        try {
          const { CopilotRuntime, copilotRuntimeNodeHttpEndpoint, EmptyAdapter } =
            await import("@copilotkit/runtime");
          const { LangGraphHttpAgent } = await import(
            "@copilotkit/runtime/langgraph"
          );

          const backendUrl = process.env.BACKEND_URL || "http://localhost:8000";

          const runtime = new CopilotRuntime({
            agents: {
              default: new LangGraphHttpAgent({
                url: `${backendUrl}/api/v1/segment`,
                description: "Segment generation agent",
              }),
            },
          });

          const handler = copilotRuntimeNodeHttpEndpoint({
            runtime,
            serviceAdapter: new EmptyAdapter(),
            endpoint: "/copilotkit",
          });

          // Register the route on the Express app
          devServer.app.all("/copilotkit", async (req, res) => {
            try {
              // Read body to detect agent/connect
              const chunks = [];
              for await (const chunk of req) chunks.push(chunk);
              const rawBody = Buffer.concat(chunks).toString();
              const parsed = JSON.parse(rawBody);

              if (parsed.method === "agent/connect") {
                // Proxy directly to backend — CopilotKit's in-memory
                // runner loses state on page reload
                const threadId = parsed.body?.threadId ?? parsed.params?.threadId;
                const runId = parsed.body?.runId ?? require("crypto").randomUUID();

                const backendResp = await fetch(`${backendUrl}/api/v1/segment`, {
                  method: "POST",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({
                    thread_id: threadId,
                    run_id: runId,
                    messages: parsed.body?.messages ?? [],
                    metadata: { requestType: "connect" },
                  }),
                });

                res.writeHead(backendResp.status, {
                  "Content-Type": "text/event-stream",
                  "Cache-Control": "no-cache",
                  "Connection": "keep-alive",
                });
                const reader = backendResp.body.getReader();
                while (true) {
                  const { done, value } = await reader.read();
                  if (done) { res.end(); return; }
                  res.write(value);
                }
              }

              // Not agent/connect — pass body to CopilotKit handler
              req.body = parsed;
              await handler(req, res);
            } catch (err) {
              console.error("CopilotRuntime error:", err);
              if (!res.headersSent) {
                res.status(500).send("Internal server error");
              }
            }
          });

          console.log(
            `CopilotRuntime embedded at /copilotkit → ${backendUrl}/api/v1/segment`
          );

          // Stateful segment runtime
          const statefulRuntime = new CopilotRuntime({
            agents: {
              default: new LangGraphHttpAgent({
                url: `${backendUrl}/api/v1/stateful-segment`,
                description: "Stateful segment generation agent",
              }),
            },
          });

          const statefulHandler = copilotRuntimeNodeHttpEndpoint({
            runtime: statefulRuntime,
            serviceAdapter: new EmptyAdapter(),
            endpoint: "/copilotkit-stateful",
          });

          devServer.app.all("/copilotkit-stateful", async (req, res) => {
            try {
              const chunks = [];
              for await (const chunk of req) chunks.push(chunk);
              const rawBody = Buffer.concat(chunks).toString();
              const parsed = JSON.parse(rawBody);

              if (parsed.method === "agent/connect") {
                const threadId = parsed.body?.threadId ?? parsed.params?.threadId;
                const runId = parsed.body?.runId ?? require("crypto").randomUUID();

                const backendResp = await fetch(`${backendUrl}/api/v1/stateful-segment`, {
                  method: "POST",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({
                    thread_id: threadId,
                    run_id: runId,
                    messages: parsed.body?.messages ?? [],
                    metadata: { requestType: "connect" },
                  }),
                });

                res.writeHead(backendResp.status, {
                  "Content-Type": "text/event-stream",
                  "Cache-Control": "no-cache",
                  "Connection": "keep-alive",
                });
                const reader = backendResp.body.getReader();
                while (true) {
                  const { done, value } = await reader.read();
                  if (done) { res.end(); return; }
                  res.write(value);
                }
              }

              req.body = parsed;
              await statefulHandler(req, res);
            } catch (err) {
              console.error("CopilotRuntime (stateful) error:", err);
              if (!res.headersSent) {
                res.status(500).send("Internal server error");
              }
            }
          });

          console.log(
            `CopilotRuntime (stateful) embedded at /copilotkit-stateful → ${backendUrl}/api/v1/stateful-segment`
          );
        } catch (err) {
          console.error("Failed to set up CopilotRuntime:", err);
        }
      })();

      return middlewares;
    },
  },
};

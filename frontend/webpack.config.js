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
        } catch (err) {
          console.error("Failed to set up CopilotRuntime:", err);
        }
      })();

      return middlewares;
    },
  },
};

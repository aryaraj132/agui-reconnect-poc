import Link from "next/link";

const agents = [
  {
    href: "/segment",
    title: "Segment Builder",
    description:
      "Build audience segments with an 8-step AI pipeline. Features stream reconnection with Redis Pub/Sub event persistence.",
  },
  {
    href: "/stateful-segment",
    title: "Segment Builder (Stateful)",
    description:
      "Same segment pipeline but catch-up on reconnect uses LangGraph checkpointer state instead of Redis List replay.",
  },
  {
    href: "/template",
    title: "Template Builder",
    description:
      "Create and modify email templates with AI. Uses ag-ui-langgraph for automatic AG-UI event generation.",
  },
];

export default function Home() {
  return (
    <main className="min-h-screen flex items-center justify-center bg-gray-50 dark:bg-gray-950">
      <div className="max-w-3xl w-full px-6 py-16">
        <h1 className="text-2xl font-bold text-center mb-2">
          Stream Reconnection Demo
        </h1>
        <p className="text-sm text-gray-500 text-center mb-10">
          Choose an agent to get started
        </p>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {agents.map((agent) => (
            <Link
              key={agent.href}
              href={agent.href}
              className="block p-6 rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 hover:border-blue-400 dark:hover:border-blue-600 hover:shadow-md transition-all"
            >
              <h2 className="text-lg font-semibold mb-2">{agent.title}</h2>
              <p className="text-sm text-gray-500 dark:text-gray-400">
                {agent.description}
              </p>
            </Link>
          ))}
        </div>
      </div>
    </main>
  );
}

export function Nav() {
  return (
    <header className="border-b border-gray-200 dark:border-gray-700 px-6 py-3 flex items-center justify-between">
      <a href="/" className="text-lg font-semibold">
        Stream Reconnection Demo
      </a>
      <nav className="flex gap-1 bg-gray-100 dark:bg-gray-800 rounded-lg p-1">
        <span className="px-3 py-1.5 rounded-md text-sm font-medium bg-white dark:bg-gray-700 shadow-sm">
          Segment Builder
        </span>
      </nav>
    </header>
  );
}

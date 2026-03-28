import "./globals.css";
import "@copilotkit/react-ui/styles.css";

export const metadata = {
  title: "AG-UI Stream Reconnection Demo",
  description: "POC for stream reconnection using Redis Streams + AG-UI protocol",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}

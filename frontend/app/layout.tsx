import type { Metadata } from "next";
import "@fontsource-variable/inter";
import "@fontsource-variable/manrope";
import "./globals.css";
import "./site.css";

export const metadata: Metadata = {
  title: { default: "Resolve — Payment aftercare", template: "%s · Resolve" },
  description: "Give buyers a clear next step and verify what happened after checkout.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}

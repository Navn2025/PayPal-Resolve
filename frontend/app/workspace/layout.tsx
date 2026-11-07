import type { Metadata } from "next";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { SESSION_COOKIE, SESSION_PATTERN } from "@/lib/server";

export const metadata: Metadata = { robots: { index: false, follow: false }, referrer: "no-referrer" };

export default async function WorkspaceLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  const token = (await cookies()).get(SESSION_COOKIE)?.value ?? "";
  if (!SESSION_PATTERN.test(token)) redirect("/login");
  return children;
}

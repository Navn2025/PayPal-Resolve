import type { Metadata } from "next";
import { Workspace } from "@/components/workspace";

export const metadata: Metadata = { title: "Merchant workspace" };

export default async function WorkspacePage({ searchParams }: { searchParams: Promise<{ case?: string | string[] }> }) {
  const requested = (await searchParams).case;
  const caseId = typeof requested === "string" && /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(requested)
    ? requested.toLowerCase() : null;
  return <Workspace key={caseId ?? "inbox"} mode="merchant" initialCaseId={caseId} />;
}

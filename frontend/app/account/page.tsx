import type { Metadata } from "next";
import { WorkspaceAccount } from "@/components/workspace-account";
export const metadata: Metadata = { title: "Merchant account", robots: { index: false, follow: false }, referrer: "no-referrer" };
export default function AccountPage() { return <WorkspaceAccount />; }

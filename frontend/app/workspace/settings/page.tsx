import type { Metadata } from "next";
import { MerchantSettings } from "@/components/merchant-login";

export const metadata: Metadata = { title: "Workspace settings" };

export default async function SettingsPage({ searchParams }: { searchParams: Promise<{ paypal?: string }> }) {
  const query = await searchParams;
  return <MerchantSettings notice={query.paypal} />;
}

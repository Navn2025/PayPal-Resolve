import type { Metadata } from "next";
import { MerchantLogin } from "@/components/merchant-login";

export const metadata: Metadata = { title: "Merchant sign in", robots: { index: false, follow: false }, referrer: "no-referrer" };

export default async function LoginPage({ searchParams }: { searchParams: Promise<{ paypal?: string; next?: string }> }) {
  const query = await searchParams;
  return <MerchantLogin notice={query.paypal} next={query.next === "settings" ? "/workspace/settings" : "/workspace"} />;
}

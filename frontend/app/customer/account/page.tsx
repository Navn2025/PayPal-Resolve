import type { Metadata } from "next";
import { CustomerAccount } from "@/components/customer-account";

export const metadata: Metadata = {
  title: "My cases — Resolve",
  robots: { index: false, follow: false },
  referrer: "no-referrer",
};

export default function CustomerAccountPage() {
  return <CustomerAccount />;
}

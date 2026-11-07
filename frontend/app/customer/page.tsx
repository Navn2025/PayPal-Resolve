import type { Metadata } from "next";
import { CustomerView } from "@/components/customer-view";

export const metadata: Metadata = {
  title: "Track your resolution — Resolve",
  description: "View the remedy, progress, and messages for your case.",
  robots: { index: false, follow: false },
  referrer: "no-referrer",
};

export default function CustomerPage() {
  return <CustomerView />;
}

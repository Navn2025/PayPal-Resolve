import type { Metadata } from "next";
import { Workspace } from "@/components/workspace";

export const metadata: Metadata = { title: "Interactive demo" };

export default function DemoPage() {
  return <Workspace mode="demo" />;
}

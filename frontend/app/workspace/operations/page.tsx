import type { Metadata } from "next";
import { OperationsConsole } from "@/components/operations-console";
export const metadata: Metadata = { title: "Merchant operations" };
export default function OperationsPage() { return <OperationsConsole />; }

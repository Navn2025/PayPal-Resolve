import type { Metadata } from "next";
import { MerchantOrders } from "@/components/merchant-orders";

export const metadata: Metadata = { title: "Connected orders" };

export default function OrdersPage() {
  return <MerchantOrders />;
}

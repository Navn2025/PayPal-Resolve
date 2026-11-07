import Link from "next/link";
import { ArrowLeft, ArrowRight } from "lucide-react";
import { Brand } from "@/components/ui";

export default function NotFound() {
  return <main className="access-shell access-empty"><section className="access-card">
    <Link href="/" aria-label="Resolve home"><Brand /></Link>
    <p className="site-kicker"><span /> PAGE NOT FOUND</p>
    <h1>Let’s get you back on track.</h1>
    <p>Return to Resolve or open the customer portal from the link your merchant shared.</p>
    <div className="site-actions"><Link href="/" className="site-button site-button-primary"><ArrowLeft size={17} /> Back home</Link>
      <Link href="/customer" className="site-button site-button-quiet">Customer portal <ArrowRight size={17} /></Link></div>
  </section></main>;
}

import Link from "next/link";
import type { Metadata } from "next";
import { ArrowUpRight, BookOpen } from "lucide-react";
import { Brand } from "@/components/ui";
import { DocsNavigation } from "@/components/docs-navigation";
import { docNavigation } from "@/lib/documentation";
import "./docs.css";

export const metadata: Metadata = {
  title: { default: "Documentation · Resolve", template: "%s · Resolve Docs" },
  description: "Guides for merchants, buyers and developers using Resolve payment aftercare.",
};
export default function DocsLayout({ children }: { children: React.ReactNode }) {
  return <div className="resolve-docs"><a className="skip-link" href="#docs-content">Skip to documentation</a>
    <header className="docs-header"><div className="docs-header-inner">
      <Link href="/" className="site-brand" aria-label="Resolve home"><Brand small /></Link>
      <Link href="/docs" className="docs-header-label"><BookOpen size={16} />Documentation</Link>
      <nav aria-label="Documentation header"><Link href="/account">Merchant account</Link><Link href="/workspace" className="docs-workspace-link">Open workspace<ArrowUpRight size={15} /></Link></nav>
    </div></header>
    <div className="docs-shell"><DocsNavigation entries={docNavigation} /><main id="docs-content" className="docs-main">{children}</main></div>
    <footer className="docs-footer"><span>Resolve · Payment aftercare</span><Link href="/docs/getting-started">Start your first resolution →</Link></footer>
  </div>;
}

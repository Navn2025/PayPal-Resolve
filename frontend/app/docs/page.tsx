import Link from "next/link";
import { ArrowRight, ArrowUpRight, Braces, ShoppingBag, Store } from "lucide-react";
import { documentation, docGroups } from "@/lib/documentation";

export default function DocsHome() {
  return <>
    <header className="docs-home-hero"><p className="docs-eyebrow">THE RESOLVE GUIDE</p><h1>From an issue<br />to a clear next step.</h1>
      <p className="docs-lead">Learn the workspace, help your buyers and connect order support to your app.</p>
      <div className="docs-hero-actions"><Link className="docs-primary" href="/docs/getting-started">Start with a practice case<ArrowRight size={17} /></Link><a href="/docs/resolve-guide.md" download>Download the full guide<ArrowUpRight size={15} /></a></div>
      <p className="docs-edition">{documentation.articles.length} practical guides <span>·</span> {documentation.edition}</p>
    </header>
    <section className="docs-role-grid" aria-label="Choose your role">{[
      { title: "For merchants", description: "Cases, commitments and financial review.", href: "/docs/merchant-workspace", Icon: Store },
      { title: "For buyers", description: "Private support, offers and progress.", href: "/docs/buyer-portal", Icon: ShoppingBag },
      { title: "For developers", description: "Server-side SDK and reliable app updates.", href: "/docs/sdk-integration", Icon: Braces },
    ].map(({ title, description, href, Icon }) => <Link className="docs-role-card" key={href} href={href}><Icon size={22} /><h2>{title}</h2><p>{description}</p><ArrowRight className="docs-card-arrow" size={17} /></Link>)}</section>
    {docGroups.map(group => <section className="docs-guide-group" key={group}><h2>{group}</h2><div className="docs-guide-grid">{documentation.articles.filter(article => article.group === group).map(article =>
      <Link className="docs-guide-card" href={"/docs/" + article.slug} key={article.slug}><h3>{article.title}<ArrowUpRight size={16} /></h3><p>{article.description}</p></Link>
    )}</div></section>)}
    <section className="docs-reference"><div><p className="docs-eyebrow">BUILD AGAINST THE CONTRACT</p><h2>Need the exact API shape?</h2><p>Download methods, request bodies and response schemas from the generated OpenAPI contract.</p></div><a href="/docs/resolve.openapi.json" download>Download OpenAPI<ArrowUpRight size={16} /></a></section>
  </>;
}

"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState } from "react";
import { Search } from "lucide-react";

type Entry = { slug: string; title: string; description: string; group: string; search: string };
export function DocsNavigation({ entries }: { entries: Entry[] }) {
  const path = usePathname();
  const router = useRouter();
  const [query, setQuery] = useState("");
  const normalized = query.trim().toLowerCase();
  const matching = entries.filter(entry => entry.search.includes(normalized));
  const groups = [...new Set(matching.map(entry => entry.group))];
  return <aside className="docs-sidebar" aria-label="Documentation navigation">
    <Link className="docs-overview-link" href="/docs" aria-current={path === "/docs" ? "page" : undefined}>Documentation home</Link>
    <label className="docs-search"><Search size={17} aria-hidden="true" /><span className="docs-sr-only">Search guides</span>
      <input type="search" value={query} maxLength={100} placeholder="Find a guide…" onChange={event => setQuery(event.target.value)} />
    </label>
    <label className="docs-mobile-select">Browse the guide
      <select value={path.split("/")[2] ?? ""} onChange={event => router.push(event.target.value ? "/docs/" + event.target.value : "/docs")}>
        <option value="">Documentation home</option>{entries.map(entry => <option key={entry.slug} value={entry.slug}>{entry.title}</option>)}
      </select>
    </label>
    <nav className={`docs-nav-groups ${normalized ? "is-searching" : ""}`} aria-label="Guides">
      {groups.map(group => <div key={group}><p>{group}</p>{matching.filter(entry => entry.group === group).map(entry =>
        <Link key={entry.slug} href={"/docs/" + entry.slug} aria-current={path === "/docs/" + entry.slug ? "page" : undefined}>{entry.title}</Link>
      )}</div>)}
    </nav>
    {normalized && <p className="docs-search-status" role="status">{matching.length ? `${matching.length} matching ${matching.length === 1 ? "guide" : "guides"}` : "No matching guide. Try “refund”, “SDK” or “sender”."}</p>}
    <a className="docs-download-link" href="/docs/resolve-guide.md" download>Download the complete guide ↗</a>
  </aside>;
}

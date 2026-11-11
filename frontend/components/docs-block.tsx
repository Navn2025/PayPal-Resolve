import Link from "next/link";
import { ArrowUpRight, Info } from "lucide-react";
import type { DocBlock as Block } from "@/lib/documentation";
import { DocCode } from "./docs-actions";

export function DocsBlock({ block }: { block: Block }) {
  switch (block.type) {
    case "paragraph": return <p>{block.text}</p>;
    case "note": return <aside className="docs-note"><Info size={18} aria-hidden="true" /><div><strong>{block.title}</strong><p>{block.text}</p></div></aside>;
    case "steps": return <ol className="docs-steps">{block.items.map((item, index) => <li key={index}>{item}</li>)}</ol>;
    case "list": return <ul>{block.items.map((item, index) => <li key={index}>{item}</li>)}</ul>;
    case "code": return <DocCode language={block.language} text={block.text} />;
    case "table": return <div className="docs-table-scroll" role="region" aria-label={block.columns.join(" and ")} tabIndex={0}><table><thead><tr>{block.columns.map(column => <th scope="col" key={column}>{column}</th>)}</tr></thead><tbody>{block.rows.map((row, index) => <tr key={index}>{row.map((cell, cellIndex) => <td key={cellIndex}>{cell}</td>)}</tr>)}</tbody></table></div>;
    case "links": return <ul className="docs-related">{block.items.map(item => <li key={item.href}>{/\.(json|md)$/.test(item.href)
      ? <a href={item.href} download>{item.label}<ArrowUpRight size={15} aria-hidden="true" /></a>
      : <Link href={item.href}>{item.label}<ArrowUpRight size={15} aria-hidden="true" /></Link>}</li>)}</ul>;
  }
}

import Link from "next/link";
import { notFound } from "next/navigation";
import type { Metadata } from "next";
import { ArrowLeft, ArrowRight, Link as LinkIcon } from "lucide-react";
import { documentation } from "@/lib/documentation";
import { DocsBlock } from "@/components/docs-block";
import { PrintArticle } from "@/components/docs-actions";

export const dynamicParams = false;
export function generateStaticParams() { return documentation.articles.map(article => ({ slug: article.slug })); }
export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }): Promise<Metadata> {
  const { slug } = await params;
  const article = documentation.articles.find(item => item.slug === slug);
  return article ? { title: article.title, description: article.description } : { title: "Guide not found" };
}
export default async function Article({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const index = documentation.articles.findIndex(item => item.slug === slug);
  if (index < 0) notFound();
  const article = documentation.articles[index];
  const previous = documentation.articles[index - 1], next = documentation.articles[index + 1];
  return <div className="docs-article-layout"><article className="docs-article">
    <header className="docs-article-header"><nav aria-label="Breadcrumb"><Link href="/docs">Documentation</Link><span>/</span><span>{article.group}</span></nav>
      <h1>{article.title}</h1><p className="docs-lead">{article.description}</p><div className="docs-article-meta"><span>{documentation.edition}</span><PrintArticle /></div>
    </header>
    <nav className="docs-contents-inline" aria-label="Article sections"><strong>In this guide</strong>{article.sections.map(section => <a key={section.id} href={"#" + section.id}>{section.title}</a>)}</nav>
    {article.sections.map(section => <section className="docs-section" id={section.id} key={section.id}><h2>{section.title}<a className="docs-anchor" aria-label={"Link to " + section.title} href={"#" + section.id}><LinkIcon size={16} /></a></h2>{section.blocks.map((block, index) => <DocsBlock key={index} block={block} />)}</section>)}
    <nav className="docs-pagination" aria-label="Previous and next guide">{previous ? <Link href={"/docs/" + previous.slug}><ArrowLeft size={16} /><span><small>Previous guide</small>{previous.title}</span></Link> : <span />}{next && <Link href={"/docs/" + next.slug}><span><small>Next guide</small>{next.title}</span><ArrowRight size={16} /></Link>}</nav>
    <p className="docs-bottom-download"><a href="/docs/resolve-guide.md" download>Download all 10 guides as Markdown</a></p>
  </article><nav className="docs-contents" aria-label="On this page"><strong>On this page</strong>{article.sections.map(section => <a key={section.id} href={"#" + section.id}>{section.title}</a>)}</nav></div>;
}

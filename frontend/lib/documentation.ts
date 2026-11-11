import content from "@/content/docs.json";

export type DocBlock =
  | { type: "paragraph"; text: string }
  | { type: "note"; title: string; text: string }
  | { type: "list" | "steps"; items: string[] }
  | { type: "code"; language: string; text: string }
  | { type: "table"; columns: string[]; rows: string[][] }
  | { type: "links"; items: { label: string; href: string }[] };
export interface DocArticle {
  slug: string; title: string; description: string; group: string;
  sections: { id: string; title: string; blocks: DocBlock[] }[];
}
export const documentation = content as { edition: string; articles: DocArticle[] };
export const docGroups = [...new Set(documentation.articles.map(article => article.group))];
function searchable(block: DocBlock): string {
  switch (block.type) {
    case "paragraph": case "code": return block.text;
    case "note": return block.title + " " + block.text;
    case "list": case "steps": return block.items.join(" ");
    case "table": return block.columns.join(" ") + " " + block.rows.flat().join(" ");
    case "links": return block.items.map(item => item.label).join(" ");
  }
}
export const docNavigation = documentation.articles.map(({ slug, title, description, group, sections }) => ({
  slug, title, description, group, search: [title, description, ...sections.flatMap(section => [section.title, ...section.blocks.map(searchable)])].join(" ").toLowerCase(),
}));

import { redirect } from "next/navigation";

// Old bookmarks must lead to real authenticated work, never synthetic records.
export default function RetiredDemoPage() {
  redirect("/login");
}

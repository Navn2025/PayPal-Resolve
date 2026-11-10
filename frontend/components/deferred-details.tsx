"use client";

import { useState, type ReactNode } from "react";

/** Mount secondary tools when opened, retaining drafts when collapsed. */
export function DeferredDetails({ title, children, onOpen, unmountOnClose=false, className = "ops-record" }: {
  title: string; children: ReactNode; onOpen?: () => void; unmountOnClose?:boolean; className?: string;
}) {
  const [open,setOpen] = useState(false);
  const [visited, setVisited] = useState(false);
  return <details className={className} onToggle={event => {
    setOpen(event.currentTarget.open);
    if (event.currentTarget.open && !visited) { setVisited(true); onOpen?.(); }
  }}><summary>{title}</summary>{visited && (!unmountOnClose || open) && children}</details>;
}

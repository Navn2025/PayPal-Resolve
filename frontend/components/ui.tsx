"use client";

import { useEffect, useRef, type ButtonHTMLAttributes, type ReactNode } from "react";
import { ArrowUpRight, CalendarClock, CircleAlert, CircleCheck, CircleX, CreditCard, FileText, PackageCheck, RotateCcw, ShieldCheck, WalletCards, X, type LucideIcon } from "lucide-react";
import { outcomeLabels, type Outcome, type Remedy } from "@/lib/domain";

export const remedyIcons: Record<Remedy, LucideIcon> = {
  refund: RotateCcw, return: PackageCheck, replacement: PackageCheck,
  order_cancellation: CircleX, subscription: CalendarClock, store_credit_or_exchange: WalletCards,
  billing_correction: CreditCard, dispute_handoff: FileText,
};

export function Brand({ small = false }: { small?: boolean }) {
  return <span className={`brand ${small ? "brand-small" : ""}`}>
    <svg className="brand-icon" width="35" height="35" viewBox="0 0 36 36" fill="none" aria-hidden="true">
      <rect width="36" height="36" rx="11" fill="currentColor" />
      <path d="M18 7.6 27.5 13v10L18 28.4 8.5 23V13L18 7.6Z" stroke="#E4F1FF" strokeWidth="1.4" strokeLinejoin="round" opacity=".75"/>
      <path d="m12.8 18 3.3 3.3 7.4-7.4" stroke="white" strokeWidth="2.25" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
    <span>Resolve<span className="brand-dot">.</span></span>
  </span>;
}

export function Button({ children, className = "", variant = "secondary", ...props }: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger";
}) {
  return <button type="button" className={`button button-${variant} ${className}`} {...props}>{children}</button>;
}

export function Badge({ outcome, label }: { outcome: Outcome; label?: string }) {
  return <span className={`badge badge-${outcome}`}><span aria-hidden="true" />{label ?? outcomeLabels[outcome]}</span>;
}

export function Notice({ children, tone = "error" }: { children: ReactNode; tone?: "error" | "info" | "success" }) {
  const Icon = tone === "error" ? CircleAlert : tone === "success" ? CircleCheck : ShieldCheck;
  return <div className={`notice notice-${tone}`} role={tone === "error" ? "alert" : "status"}><Icon size={17} /><div>{children}</div></div>;
}

export function Modal({ title, description, onClose, children, busy = false }: {
  title: string; description?: string; onClose: () => void; children: ReactNode; busy?: boolean;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const node = dialog.current;
    node?.showModal();
    return () => node?.close();
  }, []);
  return <dialog className="modal" ref={dialog} aria-labelledby="modal-title" aria-describedby={description ? "modal-description" : undefined}
    onCancel={(event) => { event.preventDefault(); if (!busy) onClose(); }}
    onClick={(event) => { if (!busy && event.target === event.currentTarget) {
      const bounds = event.currentTarget.getBoundingClientRect();
      if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) onClose();
    } }}>
    <div className="modal-head"><div><h2 id="modal-title">{title}</h2>{description && <p id="modal-description">{description}</p>}</div>
      <Button variant="ghost" className="icon-button" aria-label="Close dialog" onClick={onClose} disabled={busy}><X size={19} /></Button></div>
    {children}
  </dialog>;
}

export function Empty({ title, detail, action }: { title: string; detail: string; action?: ReactNode }) {
  return <div className="empty-state"><span className="empty-icon"><FileText size={22} /></span><h3>{title}</h3><p>{detail}</p>{action}</div>;
}

export function GuideLink() {
  return <a className="text-link" href="http://127.0.0.1:8000/docs" target="_blank" rel="noreferrer">Open API docs <ArrowUpRight size={14} /></a>;
}

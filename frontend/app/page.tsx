import Link from "next/link";
import { ArrowDown, ArrowRight, ArrowUpRight, Check, CircleDollarSign, Clock3, FileCheck2, FileText, PackageCheck, ShieldCheck } from "lucide-react";
import { Brand } from "@/components/ui";

const milestones = [
  { title: "Request received", source: "Customer submitted", time: "10:04 AM", Icon: FileText },
  { title: "Return confirmed", source: "Merchant recorded", time: "10:18 AM", Icon: PackageCheck },
  { title: "Partial refund verified", source: "PayPal confirmed", time: "10:32 AM", Icon: ShieldCheck },
];
const steps = [
  { title: "Capture the issue", text: "Send a private order link. Buyers report the problem and attach photos, receipts, or return slips.", Icon: FileText },
  { title: "Agree on what’s next", text: "Record the remedy, assign the case, and set a due date. Keep requests, approvals, and evidence in one place.", Icon: Clock3 },
  { title: "Verify the outcome", text: "Check refund progress against PayPal records. Share the outcome and the next step with the buyer.", Icon: FileCheck2 },
];

export default function Home() {
  return <div className="resolve-site">
    <a className="skip-link" href="#main-content">Skip to content</a>
    <header className="site-header">
      <div className="site-wrap site-nav">
        <Link href="/" className="site-brand" aria-label="Resolve home"><Brand /></Link>
        <nav className="site-nav-links" aria-label="Main navigation">
          <a href="#workflow">How it works</a><Link href="/customer">Customer portal</Link>
        </nav>
        <Link href="/login" className="site-button site-button-quiet">Merchant sign in <ArrowUpRight size={16} /></Link>
      </div>
    </header>
    <main id="main-content">
      <section className="site-wrap site-hero">
        <div className="site-hero-copy">
          <p className="site-kicker"><span /> PAYMENT AFTERCARE</p>
          <h1>From payment issue <em>to verified resolution.</em></h1>
          <p className="site-lead">Give buyers a clear next step and give your team one place to prove what happened after checkout.</p>
          <div className="site-actions">
            <Link className="site-button site-button-primary" href="/demo">Explore the demo <ArrowRight size={18} /></Link>
            <Link className="site-button site-button-quiet" href="/customer">Track my case <ArrowUpRight size={16} /></Link>
          </div>
          <p className="site-hero-note"><ShieldCheck size={16} /> Demo uses sample records. No money moves.</p>
        </div>
        <div className="site-visual" aria-label="Example buyer timeline">
          <div className="site-orbit site-orbit-one" /><div className="site-orbit site-orbit-two" />
          <div className="site-preview-label"><span /> SAMPLE CASE <span className="site-preview-id">/ 4821</span></div>
          <article className="site-preview">
            <header className="site-preview-head">
              <span className="site-preview-icon"><PackageCheck size={23} /></span>
              <div><p>ORDER #4821</p><h2>Headphone return</h2></div>
              <span className="site-tag site-tag-positive"><Check size={12} /> Verified</span>
            </header>
            <ol className="site-events">{milestones.map(({ title, source, time, Icon }) => (
              <li key={title}><span className="site-event-icon"><Icon size={16} /></span>
                <div><strong>{title}</strong><span>{source}</span></div><time>{time}</time></li>
            ))}</ol>
            <footer className="site-preview-footer"><CircleDollarSign size={20} /><span><strong>$20.00</strong> verified refund</span><span>USD</span></footer>
          </article>
          <div className="site-visual-foot"><span>ORDER SUPPORT</span><span>EVIDENCE TIMELINE</span></div>
        </div>
      </section>
      <section id="workflow" className="site-workflow">
        <div className="site-wrap">
          <div className="site-section-head"><div><p className="site-kicker"><span /> THE WORKFLOW</p><h2>Clarity at every step.</h2></div>
            <a href="#access" className="site-scroll-link">Find your workspace <ArrowDown size={17} /></a></div>
          <div className="site-step-grid">{steps.map(({ title, text, Icon }, i) => (
            <article className="site-step" key={title}><div><span className="site-step-icon"><Icon size={21} /></span><span>0{i + 1}</span></div>
              <h3>{title}</h3><p>{text}</p></article>
          ))}</div>
        </div>
      </section>
      <section className="site-wrap site-access" id="access">
        <article className="site-role"><p className="site-kicker"><span /> FOR MERCHANTS</p><h2>Manage resolutions.</h2>
          <p>Review cases, verify evidence, and approve the exact refund amount when a refund is due.</p>
          <Link className="site-text-link" href="/login">Go to merchant sign in <ArrowRight size={17} /></Link></article>
        <article className="site-role"><p className="site-kicker"><span /> FOR BUYERS</p><h2>Know what happens next.</h2>
          <p>Open the link your merchant shared, or sign in by email to revisit the cases tied to your address.</p>
          <Link className="site-text-link" href="/customer/account">Open My cases <ArrowRight size={17} /></Link></article>
      </section>
    </main>
    <footer className="site-footer"><div className="site-wrap"><Link href="/" className="site-brand" aria-label="Resolve home"><Brand small /></Link>
      <span>Payment aftercare for merchants and buyers.</span><Link href="/demo">Try the demo <ArrowUpRight size={15} /></Link></div></footer>
  </div>;
}

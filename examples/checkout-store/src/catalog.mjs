export const catalog = [
  { id: "kettle", name: "Trail Kettle", kind: "HEAT", cents: 2800, tone: "clay", note: "A steady pour on a camp stove." },
  { id: "cup", name: "Camp Cup", kind: "SIP", cents: 1400, tone: "oat", note: "An everyday enamel cup for anywhere." },
  { id: "cone", name: "Pour-over Cone", kind: "BREW", cents: 1800, tone: "moss", note: "A compact dripper for a slow morning." },
  { id: "scale", name: "Pocket Scale", kind: "MEASURE", cents: 2400, tone: "mist", note: "Small enough to live in your brew kit." },
  { id: "tin", name: "Field Tin", kind: "CARRY", cents: 1200, tone: "sand", note: "Keep your beans together on the trail." },
  { id: "brush", name: "Brew Brush", kind: "CARE", cents: 800, tone: "rose", note: "Sweep away grounds before you pack." },
];

export const money = (cents) => (cents / 100).toFixed(2);

export class ShopError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

export function quote(items) {
  if (!Array.isArray(items) || !items.length || items.length > catalog.length) {
    throw new ShopError(400, "Add at least one product to the cart.");
  }
  const counts = new Map();
  for (const row of items) {
    if (!row || typeof row !== "object" || Object.keys(row).some(k => k !== "id" && k !== "quantity") ||
        counts.has(row.id) || !catalog.some(product => product.id === row.id) ||
        !Number.isInteger(row.quantity) || row.quantity < 1 || row.quantity > 10) {
      throw new ShopError(400, "Use one to ten of each catalog product.");
    }
    counts.set(row.id, row.quantity);
  }
  const lines = catalog.filter(product => counts.has(product.id)).map(({ id, name, cents }) =>
    ({ id, name, cents, quantity: counts.get(id) }));
  return { lines, total: lines.reduce((sum, item) => sum + item.cents * item.quantity, 0) };
}

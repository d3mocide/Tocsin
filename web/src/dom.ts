/** Minimal DOM builders. Every view constructs nodes through these rather
 * than assigning `innerHTML`, so text from an alert payload, a site name,
 * or an Icecast stream title can never be parsed as markup -- the old
 * spectrum site `<select>` built its options by string interpolation,
 * which was the one injection point in this app.
 *
 * Not a framework and not a step toward one: four functions covering
 * element/text/attribute, which is the whole surface the views need. */

type Child = Node | string | null | undefined | false;

export function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  options: { class?: string; text?: string; title?: string; attrs?: Record<string, string> } = {},
  ...children: Child[]
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (options.class) node.className = options.class;
  if (options.text !== undefined) node.textContent = options.text;
  if (options.title) node.title = options.title;
  for (const [name, value] of Object.entries(options.attrs ?? {})) {
    node.setAttribute(name, value);
  }
  for (const child of children) {
    if (child === null || child === undefined || child === false) continue;
    node.append(typeof child === "string" ? document.createTextNode(child) : child);
  }
  return node;
}

export function byId<T extends HTMLElement>(id: string): T {
  const node = document.getElementById(id);
  if (!node) throw new Error(`missing #${id}`);
  return node as T;
}

export function replaceChildren(container: HTMLElement, ...children: Child[]): void {
  container.replaceChildren();
  for (const child of children) {
    if (child === null || child === undefined || child === false) continue;
    container.append(typeof child === "string" ? document.createTextNode(child) : child);
  }
}

/** A labelled definition row, the shape most of the detail panels use. */
export function field(label: string, value: string | Node | null, options: { mono?: boolean } = {}): HTMLElement {
  const valueNode =
    typeof value === "string" || value === null
      ? el("dd", { class: options.mono ? "field-value mono" : "field-value", text: value ?? "—" })
      : el("dd", { class: options.mono ? "field-value mono" : "field-value" }, value);
  return el("div", { class: "field" }, el("dt", { class: "field-label", text: label }), valueNode);
}

export function badge(text: string, kind: string): HTMLElement {
  return el("span", { class: `badge badge-${kind}`, text });
}

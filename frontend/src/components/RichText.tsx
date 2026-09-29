import { Fragment, type ReactNode } from "react";

/**
 * A deliberately small Markdown renderer for model output.
 *
 * Handles only bold, italic, bullet and numbered lists, and simple pipe tables
 * (models reach for those when listing restaurants). Everything is built as
 * React elements from parsed text - no `dangerouslySetInnerHTML`, so a prompt
 * injection cannot smuggle markup into the page (FRONTEND_SPEC section 9).
 */

function inline(text: string, keyPrefix: string): ReactNode[] {
  const out: ReactNode[] = [];
  // **bold**, *italic*, `code`
  const pattern = /(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)/g;
  let last = 0;
  let match: RegExpExecArray | null;
  let i = 0;

  while ((match = pattern.exec(text)) !== null) {
    if (match.index > last) out.push(text.slice(last, match.index));
    const token = match[0];
    const key = `${keyPrefix}-i${i++}`;
    if (token.startsWith("**")) {
      out.push(<strong key={key}>{token.slice(2, -2)}</strong>);
    } else if (token.startsWith("`")) {
      out.push(
        <code key={key} className="rounded bg-canvas px-1 py-0.5 text-[13px]">
          {token.slice(1, -1)}
        </code>,
      );
    } else {
      out.push(<em key={key}>{token.slice(1, -1)}</em>);
    }
    last = match.index + token.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

/**
 * "Doodh Patti Chai – Rs 150" -> ["Doodh Patti Chai", "Rs 150"].
 *
 * The prompt asks for dishes in a table and the model often obliges, but not
 * reliably — it falls back to a dashed list, and a menu reads badly that way.
 * Rather than depend on the model getting it right, a list whose items are all
 * "dish — price" is rendered as the table it should have been. Deterministic,
 * and it costs nothing when the model does produce a table.
 *
 * Only the separator before a price is treated as a split point, so a dish with
 * a hyphen in its name ("Gluten-free Naan – Rs 150") stays intact.
 */
const DISH_AND_PRICE = /^(.+?)\s+[–—-]\s+([^\s–—-][^–—]*?[\d][\d,.]*)\s*$/;

function dishRow(item: string): [string, string] | null {
  const match = DISH_AND_PRICE.exec(item.trim());
  if (!match) return null;
  const [, dish, price] = match;
  // A price has to contain a digit and stay short; this is a menu line, not a
  // sentence that happens to contain a dash.
  if (!/\d/.test(price) || price.length > 24 || !dish.trim()) return null;
  return [dish.trim(), price.trim()];
}

function isTableRow(line: string): boolean {
  return line.trim().startsWith("|") && line.trim().endsWith("|");
}

function isDivider(line: string): boolean {
  return /^\|[\s:|-]+\|$/.test(line.trim());
}

function cells(line: string): string[] {
  return line
    .trim()
    .slice(1, -1)
    .split("|")
    .map((c) => c.trim());
}

/** Wide tables scroll inside their own box; the page never scrolls sideways. */
function Table({ header, rows }: { header: string[]; rows: string[][] }) {
  return (
    <div className="my-1 -mx-1 overflow-x-auto">
      <table className="w-full border-collapse text-[13.5px]">
        <thead>
          <tr>
            {header.map((h, n) => (
              <th
                key={n}
                className="border-b border-line px-2 py-1.5 text-left font-semibold"
              >
                {inline(h, `h${n}`)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, r) => (
            <tr key={r}>
              {row.map((c, n) => (
                <td
                  key={n}
                  className={`border-b border-line/60 px-2 py-1.5 align-top ${
                    n > 0 ? "tabular-nums whitespace-nowrap" : ""
                  }`}
                >
                  {inline(c, `c${r}-${n}`)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function RichText({ text }: { text: string }) {
  const lines = text.split("\n");
  const blocks: ReactNode[] = [];

  let i = 0;
  let key = 0;

  while (i < lines.length) {
    const line = lines[i];

    // Table
    if (isTableRow(line) && i + 1 < lines.length && isDivider(lines[i + 1])) {
      const header = cells(line);
      const rows: string[][] = [];
      i += 2;
      while (i < lines.length && isTableRow(lines[i])) {
        rows.push(cells(lines[i]));
        i += 1;
      }
      blocks.push(<Table key={`t${key++}`} header={header} rows={rows} />);
      continue;
    }

    // Lists
    const bullet = /^\s*[-*•]\s+(.*)$/.exec(line);
    const numbered = /^\s*\d+[.)]\s+(.*)$/.exec(line);
    if (bullet || numbered) {
      const ordered = Boolean(numbered);
      const items: string[] = [];
      while (i < lines.length) {
        const b = /^\s*[-*•]\s+(.*)$/.exec(lines[i]);
        const n = /^\s*\d+[.)]\s+(.*)$/.exec(lines[i]);
        if (!b && !n) break;
        items.push((b?.[1] ?? n?.[1] ?? "").trim());
        i += 1;
      }
      // A list of dishes is a menu; show it as one. Even a single dish, so a
      // course with one item does not sit as a stray bullet between tables.
      const dishes = items.map(dishRow);
      if (!ordered && items.length >= 1 && dishes.every(Boolean)) {
        blocks.push(
          <Table
            key={`t${key++}`}
            header={["Dish", "Price"]}
            rows={dishes as [string, string][]}
          />,
        );
        continue;
      }

      const ListTag = ordered ? "ol" : "ul";
      blocks.push(
        <ListTag
          key={`l${key++}`}
          className={`my-1 flex flex-col gap-1 pl-5 ${
            ordered ? "list-decimal" : "list-disc"
          }`}
        >
          {items.map((it, n) => (
            <li key={n}>{inline(it, `li${n}`)}</li>
          ))}
        </ListTag>,
      );
      continue;
    }

    // Paragraph: gather until a blank line or a block starts.
    const para: string[] = [];
    while (
      i < lines.length &&
      lines[i].trim() &&
      !isTableRow(lines[i]) &&
      !/^\s*([-*•]|\d+[.)])\s+/.test(lines[i])
    ) {
      para.push(lines[i]);
      i += 1;
    }
    if (para.length) {
      blocks.push(
        <p key={`p${key++}`} className="whitespace-pre-wrap">
          {para.map((l, n) => (
            <Fragment key={n}>
              {n > 0 && <br />}
              {inline(l, `p${key}-${n}`)}
            </Fragment>
          ))}
        </p>,
      );
      continue;
    }

    i += 1; // blank line
  }

  return <div className="flex flex-col gap-2">{blocks}</div>;
}

/** CSV helpers for the bulk student import (BP7d). No dependency — a minimal RFC-4180-ish
 *  tokenizer that handles quoted fields, "" escapes, and CRLF/LF. */

export interface CsvStudentRow {
  name: string;
  email: string;
}

/**
 * Parse a students CSV into `{name, email}` rows. Accepts an optional header row (cells
 * "name" and "email", any order/case) — otherwise column 0 = name, column 1 = email.
 * Extra columns are ignored; fully-blank lines are skipped.
 */
export function parseStudentCsv(text: string): CsvStudentRow[] {
  // Strip a leading UTF-8 BOM (U+FEFF) that Excel / Windows exports prepend — otherwise
  // the first header cell isn't "name", header detection fails, and the header row would
  // be imported as a student.
  const clean = text.charCodeAt(0) === 0xfeff ? text.slice(1) : text;
  const records = tokenize(clean);
  if (records.length === 0) return [];

  let nameIdx = 0;
  let emailIdx = 1;
  let start = 0;
  const header = records[0].map((c) => c.trim().toLowerCase());
  const hName = header.indexOf("name");
  const hEmail = header.indexOf("email");
  if (hName !== -1 && hEmail !== -1) {
    nameIdx = hName;
    emailIdx = hEmail;
    start = 1; // the first row is a header, not data
  }

  const rows: CsvStudentRow[] = [];
  for (let i = start; i < records.length; i++) {
    const cells = records[i];
    const name = (cells[nameIdx] ?? "").trim();
    const email = (cells[emailIdx] ?? "").trim();
    if (name === "" && email === "") continue; // skip blank lines
    rows.push({ name, email });
  }
  return rows;
}

/** A minimal RFC-4180 tokenizer → array of records (each a list of cell strings). */
function tokenize(text: string): string[][] {
  const records: string[][] = [];
  let row: string[] = [];
  let cell = "";
  let inQuotes = false;

  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (inQuotes) {
      if (ch === '"') {
        if (text[i + 1] === '"') {
          cell += '"'; // an escaped quote
          i++;
        } else {
          inQuotes = false;
        }
      } else {
        cell += ch;
      }
      continue;
    }
    if (ch === '"') {
      inQuotes = true;
    } else if (ch === ",") {
      row.push(cell);
      cell = "";
    } else if (ch === "\r") {
      // swallow CR (CRLF handled at the LF)
    } else if (ch === "\n") {
      row.push(cell);
      records.push(row);
      row = [];
      cell = "";
    } else {
      cell += ch;
    }
  }
  // Flush a trailing cell/row when the file doesn't end with a newline.
  if (cell !== "" || row.length > 0) {
    row.push(cell);
    records.push(row);
  }
  return records;
}

/** Build a CSV string for download (BP7d credentials export). Quotes cells that need it. */
export function toCsv(headers: string[], rows: string[][]): string {
  const escape = (v: string): string =>
    /[",\r\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v;
  const lines = [headers, ...rows].map((cells) => cells.map(escape).join(","));
  return lines.join("\r\n");
}

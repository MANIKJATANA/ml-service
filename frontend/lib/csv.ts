/** CSV helpers for the bulk student import (BP7d) + staff bulk invite (BP27b). No dependency — a
 *  minimal RFC-4180-ish tokenizer that handles quoted fields, "" escapes, and CRLF/LF. */

export interface CsvStudentRow {
  name: string;
  email: string;
  className?: string; // BP24: the optional "class" column (auto-create/assign on import)
}

/** A light client-side email shape check — the server always validates authoritatively; this
 *  only pre-flags obvious typos in a preview before submit. Shared by the student + staff
 *  bulk-import flaggers so they agree on what "invalid" means. */
export const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/**
 * Parse a students CSV into `{name, email, className?}` rows. Accepts an optional header row
 * (cells "name" and "email", any order/case) — otherwise column 0 = name, column 1 = email.
 * BP24: when a header row also has a "class" cell, that column is read into `className`
 * (auto-create/assign on import); without a header the class column is not inferred. Extra
 * columns are ignored; fully-blank lines are skipped.
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
  let classIdx = -1;
  let start = 0;
  const header = records[0].map((c) => c.trim().toLowerCase());
  const hName = header.indexOf("name");
  const hEmail = header.indexOf("email");
  if (hName !== -1 && hEmail !== -1) {
    nameIdx = hName;
    emailIdx = hEmail;
    classIdx = header.indexOf("class"); // BP24: optional 3rd column (header-detected only)
    start = 1; // the first row is a header, not data
  }

  const rows: CsvStudentRow[] = [];
  for (let i = start; i < records.length; i++) {
    const cells = records[i];
    const name = (cells[nameIdx] ?? "").trim();
    const email = (cells[emailIdx] ?? "").trim();
    if (name === "" && email === "") continue; // skip blank lines
    const className = classIdx !== -1 ? (cells[classIdx] ?? "").trim() : "";
    rows.push(className ? { name, email, className } : { name, email });
  }
  return rows;
}

/**
 * Parse a staff/teacher CSV into a list of emails (BP27b). Accepts an optional header row with an
 * "email" cell (any case) — otherwise the FIRST column is the email. Strips a leading UTF-8 BOM,
 * trims each cell, and skips blank cells. The server validates each email authoritatively (a
 * malformed one is a per-row `invalid`, not a rejected batch), so this only extracts candidates.
 */
export function parseStaffCsv(text: string): string[] {
  const clean = text.charCodeAt(0) === 0xfeff ? text.slice(1) : text;
  const records = tokenize(clean);
  if (records.length === 0) return [];

  let emailIdx = 0;
  let start = 0;
  const header = records[0].map((c) => c.trim().toLowerCase());
  const hEmail = header.indexOf("email");
  if (hEmail !== -1) {
    emailIdx = hEmail;
    start = 1; // the first row is a header, not data
  }

  const emails: string[] = [];
  for (let i = start; i < records.length; i++) {
    const email = (records[i][emailIdx] ?? "").trim();
    if (email !== "") emails.push(email);
  }
  return emails;
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

/** Trigger a client-side CSV download (BP7d/BP27b — the credentials + skipped-rows exports).
 *  Shared so every bulk flow saves the same way. */
export function saveCsv(filename: string, csv: string): void {
  const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

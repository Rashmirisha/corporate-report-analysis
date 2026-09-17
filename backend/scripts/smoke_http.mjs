// Manual HTTP smoke test for Stage 1.
// Run after the FastAPI server is up on port 3101.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import http from "node:http";
import { spawnSync } from "node:child_process";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const BACKEND_ROOT = path.resolve(__dirname, "..");

// Build tiny PDFs by calling the Python fixture helper.
function buildPdf(page1, page2) {
  const code = `
import sys
sys.path.insert(0, r"${BACKEND_ROOT}")
from app.tests._fixtures import build_minimal_pdf_two_pages
sys.stdout.buffer.write(build_minimal_pdf_two_pages(${JSON.stringify(page1)}, ${JSON.stringify(page2)}))
`;
  const r = spawnSync(
    path.join(BACKEND_ROOT, ".venv", "Scripts", "python.exe"),
    ["-c", code],
    { encoding: "buffer" }
  );
  if (r.status !== 0) throw new Error("pdf build failed: " + r.stderr.toString());
  return r.stdout;
}

function req(method, p, { form = null, json = null } = {}) {
  return new Promise((resolve, reject) => {
    const headers = {};
    let body;
    if (form) {
      const boundary = "----cra" + Math.random().toString(36).slice(2);
      headers["Content-Type"] = `multipart/form-data; boundary=${boundary}`;
      const parts = [];
      for (const [k, v] of Object.entries(form.fields || {})) {
        parts.push(Buffer.from(`--${boundary}\r\nContent-Disposition: form-data; name="${k}"\r\n\r\n${v}\r\n`));
      }
      if (form.file) {
        parts.push(Buffer.from(
          `--${boundary}\r\nContent-Disposition: form-data; name="${form.file.field}"; filename="${form.file.name}"\r\nContent-Type: application/pdf\r\n\r\n`
        ));
        parts.push(form.file.bytes);
        parts.push(Buffer.from("\r\n"));
      }
      parts.push(Buffer.from(`--${boundary}--\r\n`));
      body = Buffer.concat(parts);
      headers["Content-Length"] = body.length;
    } else if (json) {
      headers["Content-Type"] = "application/json";
      body = Buffer.from(JSON.stringify(json));
    }
    const r = http.request({ host: "127.0.0.1", port: 3101, method, path: p, headers }, (res) => {
      const chunks = [];
      res.on("data", (c) => chunks.push(c));
      res.on("end", () => {
        const text = Buffer.concat(chunks).toString("utf-8");
        resolve({ status: res.statusCode, body: text });
      });
    });
    r.on("error", reject);
    if (body) r.write(body);
    r.end();
  });
}

async function main() {
  console.log("→ health");
  const h = await req("GET", "/api/health");
  console.log(" ", h.status, h.body);

  const pdfA = buildPdf(
    "Acme Corp Annual Report FY24 - Revenue rose 12 percent to 1.2B.",
    "Risk Factors - Acme faces currency volatility."
  );
  const pdfB = buildPdf(
    "Globex Industries Annual Report FY24 - Revenue fell 4 percent.",
    "Risk Factors - Globex faces regulatory headwinds."
  );

  console.log("→ upload A");
  const upA = await req("POST", "/api/ingest/upload", {
    form: { fields: { company: "A" }, file: { field: "file", name: "Acme.pdf", bytes: pdfA } },
  });
  console.log(" ", upA.status, upA.body);

  console.log("→ upload B");
  const upB = await req("POST", "/api/ingest/upload", {
    form: { fields: { company: "B" }, file: { field: "file", name: "Globex.pdf", bytes: pdfB } },
  });
  console.log(" ", upB.status, upB.body);

  console.log("→ corpus");
  const c = await req("GET", "/api/corpus");
  const parsed = JSON.parse(c.body);
  console.log(" ", c.status, "ready =", parsed.ready);
  for (const k of ["A", "B"]) {
    const s = parsed.state_a && parsed.state_a.company === k ? parsed.state_a : parsed.state_b;
    if (!s) { console.log(`  ${k}: MISSING`); continue; }
    console.log(`  ${k}: pages=${s.source.page_count} chunks=${s.chunk_count} tables=${s.table_count} sample_chunk=${s.chunks[0]?.chunk_id}`);
  }
}

main().catch((e) => { console.error(e); process.exit(1); });

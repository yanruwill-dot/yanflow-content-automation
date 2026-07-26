import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

async function render(path = "/") {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);
  return worker.fetch(
    new Request(`http://localhost${path}`, { headers: { accept: "text/html" } }),
    { ASSETS: { fetch: async () => new Response("Not found", { status: 404 }) } },
    { waitUntil() {}, passThroughOnException() {} },
  );
}

test("server-renders the YanFlow production workbench", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);
  const html = await response.text();
  assert.match(html, /<title>焰流 YanFlow｜内容自动化中枢<\/title>/i);
  assert.match(html, /从选题到发布/);
  assert.match(html, /启动安全自动流程/);
  assert.match(html, /小红书发布账号/);
  assert.match(html, /公众号发布账号/);
  assert.match(html, /进度与结果/);
});

test("ships responsive product source without starter placeholders", async () => {
  const [page, css, layout] = await Promise.all([
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/globals.css", import.meta.url), "utf8"),
    readFile(new URL("../app/layout.tsx", import.meta.url), "utf8"),
  ]);
  assert.match(page, /"use client"/);
  assert.match(page, /function buildOutput/);
  assert.match(page, /localStorage/);
  assert.match(css, /@media \(max-width: 760px\)/);
  assert.match(css, /overflow-x:\s*clip/);
  assert.doesNotMatch(page + layout, /codex-preview|_sites-preview/);
});

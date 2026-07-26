import assert from "node:assert/strict";
import { readFile, readdir } from "node:fs/promises";
import test from "node:test";

test("builds a GitHub Pages entrypoint with repository-relative assets", async () => {
  const html = await readFile(new URL("../pages-dist/index.html", import.meta.url), "utf8");
  assert.match(html, /<title>焰流 YanFlow｜内容自动化中枢<\/title>/i);
  assert.match(html, /\/yanflow-content-automation\/assets\/index-/);
  assert.match(html, /\/yanflow-content-automation\/og\.png/);
  assert.match(html, /\/yanflow-content-automation\/favicon\.png/);
  assert.doesNotMatch(html, /chatgpt\.site|signin-with-chatgpt|_next/);
});

test("ships the complete static application and required public assets", async () => {
  const [page, css, files] = await Promise.all([
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/globals.css", import.meta.url), "utf8"),
    readdir(new URL("../pages-dist/", import.meta.url)),
  ]);
  assert.match(page, /"use client"/);
  assert.match(page, /function buildOutput/);
  assert.match(page, /localStorage/);
  assert.match(page, /启动安全自动流程/);
  assert.match(css, /@media \(max-width: 760px\)/);
  assert.match(css, /overflow-x:\s*clip/);
  assert.ok(files.includes("og.png"));
  assert.ok(files.includes("favicon.png"));
});

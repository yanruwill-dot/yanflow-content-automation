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
  const [page, css, files, sampleImages] = await Promise.all([
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/globals.css", import.meta.url), "utf8"),
    readdir(new URL("../pages-dist/", import.meta.url)),
    readdir(new URL("../pages-dist/sample-ai-tools-workflow/", import.meta.url)),
  ]);
  assert.match(page, /"use client"/);
  assert.match(page, /function buildOutput/);
  assert.match(page, /localStorage/);
  assert.match(page, /生成 5 个爆款候选/);
  assert.match(page, /Image2 九图/);
  assert.match(page, /登录新账号/);
  assert.match(page, /X-Yanflow-Token/);
  assert.match(page, /确认正式发布/);
  assert.match(page, /SAMPLE_IMAGE_URLS/);
  assert.match(page, /买再多AI工具也不提效/);
  assert.match(page, /xhsCopyPreview/);
  assert.match(page, /老板7天就能启动第一轮/);
  assert.match(page, /function isRestorableJob/);
  assert.match(page, /"images_ready", "preflight_passed", "submitted", "published", "partial_success"/);
  assert.match(page, /function publishGatePassed/);
  assert.match(page, /查看小红书公开内容/);
  assert.match(page, /disabled=\{running \|\| terminalPublish\}/);
  assert.match(page, /role="progressbar"/);
  assert.match(page, /aria-valuenow=\{progress\}/);
  assert.match(css, /@media \(max-width: 760px\)/);
  assert.match(css, /overflow-x:\s*clip/);
  assert.match(css, /\.imageCards/);
  assert.match(css, /\.publishReceipt/);
  assert.ok(files.includes("og.png"));
  assert.ok(files.includes("favicon.png"));
  assert.equal(sampleImages.filter((file) => file.endsWith(".png")).length, 9);
});

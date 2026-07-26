import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "焰流 YanFlow｜内容自动化中枢",
  description: "从自动选题、内容生成、贴图排版到发布预检，在一个工作台里完成。",
  openGraph: {
    title: "焰流 YanFlow｜内容自动化中枢",
    description: "一条线完成选题、生成、配图、排版和安全发布。",
    images: [{ url: "/og.png", width: 1536, height: 1024, alt: "焰流 YanFlow 内容自动化中枢" }],
  },
  twitter: {
    card: "summary_large_image",
    title: "焰流 YanFlow｜内容自动化中枢",
    description: "一条线完成选题、生成、配图、排版和安全发布。",
    images: ["/og.png"],
  },
  icons: {
    icon: "/favicon.png",
    shortcut: "/favicon.png",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}

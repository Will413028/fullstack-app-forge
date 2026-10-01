import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Forge — 把想法做成應用",
  description: "生成、修改與分享可以運行的全端應用。",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="zh-Hant"><body>{children}</body></html>;
}

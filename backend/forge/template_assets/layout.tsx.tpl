import type { ReactNode } from "react";
import "./globals.css";

export const metadata = {title: "Todo workspace", robots: {index: false, follow: false}};
export default function Layout({children}: {children: ReactNode}) {
  return <html lang="zh-Hant"><body>{children}</body></html>;
}

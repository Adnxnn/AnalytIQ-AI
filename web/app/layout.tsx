import type { Metadata } from "next";
import "./globals.css";
export const metadata:Metadata={title:"AnalytIQ AI | Verified Analytics",description:"Explainable data analytics with source-driven calculations."};
export default function RootLayout({children}:{children:React.ReactNode}){return <html lang="en"><body>{children}</body></html>}

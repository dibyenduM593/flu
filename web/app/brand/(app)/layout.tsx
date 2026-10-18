"use client";

import { Guarded } from "@/components/Guarded";

export default function Layout({ children }: { children: React.ReactNode }) {
  return <Guarded role="brand_member">{children}</Guarded>;
}

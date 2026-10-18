"use client";

import { Guarded } from "@/components/Guarded";

export default function Layout({ children }: { children: React.ReactNode }) {
  return <Guarded role="creator">{children}</Guarded>;
}

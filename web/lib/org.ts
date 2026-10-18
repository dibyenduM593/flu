"use client";

import { useSession } from "./session";

export function useOrg() {
  const { me } = useSession();
  return me?.orgs[0] ?? null;
}

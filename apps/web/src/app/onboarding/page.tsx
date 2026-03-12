"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

/**
 * Legacy /onboarding route — redirects to /setup.
 * Kept for backwards compatibility with existing links and tests.
 */
export default function OnboardingRedirect() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/setup");
  }, [router]);
  return null;
}

"use client";

import { useRouter } from "next/navigation";
import { CustomSiteSelect } from "./custom-site-select";

export function SiteFilterSelect({
  sites,
  current,
  basePath = "/articles/keywords",
}: {
  sites: { slug: string; name?: string }[];
  current: string;
  basePath?: string;
}) {
  const router = useRouter();

  return (
    <CustomSiteSelect
      sites={sites.map((s) => ({ slug: s.slug, name: s.name || s.slug }))}
      currentSite={current}
      onSelect={(newSlug) => {
        router.push(newSlug ? `${basePath}?site=${encodeURIComponent(newSlug)}` : basePath);
      }}
    />
  );
}

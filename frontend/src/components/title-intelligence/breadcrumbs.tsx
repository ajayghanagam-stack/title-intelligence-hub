"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ChevronRight } from "lucide-react";

const segmentLabels: Record<string, string> = {
  documents: "Documents",
  results: "Results",
};

export function Breadcrumbs({ packName }: { packName?: string }) {
  const pathname = usePathname();

  const crumbs: { label: string; href: string }[] = [
    { label: "Title Intelligence", href: "/apps/title-intelligence" },
  ];

  // Match /apps/title-intelligence/packs/{packId}[/segment]
  const match = pathname.match(
    /\/apps\/title-intelligence\/packs\/([^/]+)(\/([^/]+))?/
  );

  if (match) {
    const packId = match[1];
    crumbs.push({
      label: packName || "Pack",
      href: `/apps/title-intelligence/packs/${packId}`,
    });

    const segment = match[3];
    if (segment && segmentLabels[segment]) {
      crumbs.push({
        label: segmentLabels[segment],
        href: `/apps/title-intelligence/packs/${packId}/${segment}`,
      });
    }
  }

  return (
    <nav className="flex items-center gap-1.5 text-sm text-muted-foreground">
      {crumbs.map((crumb, i) => {
        const isLast = i === crumbs.length - 1;
        return (
          <span key={crumb.href} className="flex items-center gap-1.5">
            {i > 0 && <ChevronRight className="h-3.5 w-3.5" />}
            {isLast ? (
              <span className="font-medium text-foreground">{crumb.label}</span>
            ) : (
              <Link href={crumb.href} className="hover:text-foreground transition-colors">
                {crumb.label}
              </Link>
            )}
          </span>
        );
      })}
    </nav>
  );
}

"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ChevronRight } from "lucide-react";
import { useOrgSlug } from "@/hooks/use-org-slug";

const segmentLabels: Record<string, string> = {
  documents: "Documents",
  chain: "Chain of Title",
  flags: "Flags",
  package: "Package",
};

export function Breadcrumbs({ orderAddress }: { orderAddress?: string }) {
  const pathname = usePathname();
  const { orgPath } = useOrgSlug();

  const crumbs: { label: string; href: string }[] = [
    { label: "Title Search", href: orgPath("/apps/title-search") },
  ];

  // Match /apps/title-search/orders/{orderId}[/segment] (with optional /org/{slug} prefix)
  const match = pathname.match(
    /\/apps\/title-search\/orders\/([^/]+)(\/([^/]+))?/
  );

  if (match) {
    const orderId = match[1];
    crumbs.push({
      label: orderAddress || "Order",
      href: orgPath(`/apps/title-search/orders/${orderId}`),
    });

    const segment = match[3];
    if (segment && segmentLabels[segment]) {
      crumbs.push({
        label: segmentLabels[segment],
        href: orgPath(`/apps/title-search/orders/${orderId}/${segment}`),
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
              <span className="font-medium text-foreground">
                {crumb.label}
              </span>
            ) : (
              <Link
                href={crumb.href}
                className="hover:text-foreground transition-colors"
              >
                {crumb.label}
              </Link>
            )}
          </span>
        );
      })}
    </nav>
  );
}

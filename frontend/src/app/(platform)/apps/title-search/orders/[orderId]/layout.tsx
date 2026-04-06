"use client";

import Link from "next/link";
import { useParams, usePathname } from "next/navigation";
import { Breadcrumbs } from "@/components/title-search/breadcrumbs";
import { useOrgSlug } from "@/hooks/use-org-slug";

const TABS = [
  { href: "", label: "Overview" },
  { href: "/documents", label: "Documents" },
  { href: "/chain", label: "Chain of Title" },
  { href: "/flags", label: "Flags" },
  { href: "/package", label: "Package" },
  { href: "/results", label: "Results" },
];

export default function OrderDetailLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const params = useParams();
  const pathname = usePathname();
  const { orgPath } = useOrgSlug();
  const orderId = params.orderId as string;
  const basePath = orgPath(`/apps/title-search/orders/${orderId}`);

  return (
    <div className="space-y-6">
      <Breadcrumbs />

      <div className="flex gap-1 border-b">
        {TABS.map((tab) => {
          const href = `${basePath}${tab.href}`;
          const isActive =
            pathname === href || (tab.href === "" && pathname === basePath);
          return (
            <Link
              key={tab.href}
              href={href}
              className={`px-4 py-2.5 text-sm font-medium transition-colors border-b-2 -mb-px ${
                isActive
                  ? "border-primary text-primary"
                  : "border-transparent text-muted-foreground hover:text-foreground"
              }`}
            >
              {tab.label}
            </Link>
          );
        })}
      </div>

      {children}
    </div>
  );
}

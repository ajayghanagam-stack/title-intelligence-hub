"use client";

import { useParams } from "next/navigation";
import { Breadcrumbs } from "@/components/title-intelligence/breadcrumbs";
import { usePack } from "@/hooks/use-pack";

export default function PackDetailLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const params = useParams();
  const packId = params.packId as string;
  const { pack } = usePack(packId);

  return (
    <div className="space-y-4">
      <Breadcrumbs packName={pack?.name} />
      {children}
    </div>
  );
}

"use client";

import { useParams } from "next/navigation";

export default function MicroAppPage() {
  const params = useParams();
  const slug = params.slug as string;

  return (
    <div>
      <h2 className="text-2xl font-bold mb-4">
        {slug
          .split("-")
          .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
          .join(" ")}
      </h2>
      <p className="text-muted-foreground">
        This micro app is loading. Content will be rendered here.
      </p>
    </div>
  );
}

"use client";

import Link from "next/link";
import { FileSearch, Sparkles } from "lucide-react";
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

interface AppCardProps {
  name: string;
  slug: string;
  description: string | null;
  status?: "active" | "disabled" | "not_subscribed";
}

export function AppCard({ name, slug, description, status }: AppCardProps) {
  const isActive = status === "active";

  return (
    <Link href={isActive ? `/apps/${slug}` : "#"}>
      <Card
        className={`transition-all duration-200 hover:shadow-md ${
          isActive
            ? "border-primary/20 hover:border-primary/40"
            : "opacity-60"
        }`}
      >
        <CardHeader>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary/10">
                {slug === "title-intelligence" ? (
                  <FileSearch className="h-4.5 w-4.5 text-primary" />
                ) : (
                  <Sparkles className="h-4.5 w-4.5 text-primary" />
                )}
              </div>
              <CardTitle className="text-lg">{name}</CardTitle>
            </div>
            {status === "active" && (
              <Badge className="bg-success text-success-foreground border-0">
                Active
              </Badge>
            )}
            {status === "disabled" && (
              <Badge variant="secondary">Disabled</Badge>
            )}
            {status === "not_subscribed" && (
              <Badge variant="outline">Available</Badge>
            )}
          </div>
          <CardDescription className="mt-2">{description}</CardDescription>
        </CardHeader>
      </Card>
    </Link>
  );
}

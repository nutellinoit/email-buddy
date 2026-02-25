"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Button } from "@/components/ui/button";

const ranges = [
  { label: "24h", value: "24h" },
  { label: "7d", value: "7d" },
  { label: "30d", value: "30d" },
] as const;

export type TimeRange = (typeof ranges)[number]["value"];

export function TimeRangeSelector({ current }: { current: TimeRange }) {
  const router = useRouter();
  const searchParams = useSearchParams();

  const handleSelect = (range: TimeRange) => {
    const params = new URLSearchParams(searchParams.toString());
    params.set("range", range);
    router.push(`/?${params.toString()}`);
  };

  return (
    <div className="flex gap-1">
      {ranges.map((r) => (
        <Button
          key={r.value}
          variant={current === r.value ? "default" : "outline"}
          size="sm"
          onClick={() => handleSelect(r.value)}
        >
          {r.label}
        </Button>
      ))}
    </div>
  );
}

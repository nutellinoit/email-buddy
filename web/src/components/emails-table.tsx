"use client";

import { Badge } from "@/components/ui/badge";
import { DataTable, type Column } from "@/components/data-table";
import type { ProcessedEmail } from "@/lib/api";

function ConfidenceIndicator({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const color =
    value >= 0.85
      ? "bg-green-500"
      : value >= 0.7
        ? "bg-yellow-500"
        : "bg-red-500";
  return (
    <div className="flex items-center gap-2 justify-end">
      <div className="w-16 h-2 rounded-full bg-muted overflow-hidden">
        <div
          className={`h-full rounded-full ${color}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="font-mono text-xs w-10 text-right">
        {value.toFixed(2)}
      </span>
    </div>
  );
}

const columns: Column<ProcessedEmail>[] = [
  {
    header: "Subject",
    accessor: (r) => r.subject,
    cell: (r) => (
      <span className="font-medium truncate block max-w-[250px]">
        {r.subject || "(no subject)"}
      </span>
    ),
  },
  {
    header: "Sender",
    accessor: (r) => r.sender,
    cell: (r) => (
      <span className="truncate block max-w-[180px] text-muted-foreground">
        {r.sender}
      </span>
    ),
  },
  {
    header: "Date",
    accessor: (r) => r.date_received,
    cell: (r) => (
      <span className="whitespace-nowrap text-sm text-muted-foreground">
        {r.date_received
          ? new Date(r.date_received).toLocaleDateString()
          : "—"}
      </span>
    ),
  },
  {
    header: "Category",
    accessor: (r) => r.classification,
    cell: (r) => <Badge variant="outline">{r.classification}</Badge>,
  },
  {
    header: "Confidence",
    accessor: (r) => r.confidence,
    cell: (r) => <ConfidenceIndicator value={r.confidence} />,
    className: "text-right",
  },
  {
    header: "Reason",
    accessor: (r) => r.reason,
    cell: (r) => (
      <span className="truncate block max-w-[200px] text-xs text-muted-foreground">
        {r.reason}
      </span>
    ),
  },
];

export function EmailsTable({ data }: { data: ProcessedEmail[] }) {
  return (
    <DataTable
      data={data}
      columns={columns}
      keyAccessor={(r) => r.email_id}
      searchPlaceholder="Search subject, sender, reason..."
      pageSize={15}
    />
  );
}

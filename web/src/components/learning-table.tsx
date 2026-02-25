"use client";

import { DataTable, type Column } from "@/components/data-table";

interface RuleRow {
  index: number;
  text: string;
}

const columns: Column<RuleRow>[] = [
  {
    header: "#",
    accessor: (r) => r.index,
    className: "w-12",
  },
  {
    header: "Rule",
    accessor: (r) => r.text,
    cell: (r) => <span className="text-sm">{r.text}</span>,
  },
];

export function LearningTable({ rules }: { rules: string[] }) {
  const data: RuleRow[] = rules.map((text, i) => ({
    index: i + 1,
    text,
  }));

  return (
    <DataTable
      data={data}
      columns={columns}
      keyAccessor={(r) => String(r.index)}
      searchPlaceholder="Search rules..."
      pageSize={10}
    />
  );
}

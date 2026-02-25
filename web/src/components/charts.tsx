"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { TimelineBucket } from "@/lib/api";

const COLORS = [
  "var(--chart-1)",
  "var(--chart-2)",
  "var(--chart-3)",
  "var(--chart-4)",
  "var(--chart-5)",
];

interface ChartEntry {
  name: string;
  value: number;
}

export function CategoryPieChart({ data }: { data: ChartEntry[] }) {
  if (data.length === 0) return <p className="text-muted-foreground text-sm">No data</p>;
  return (
    <ResponsiveContainer width="100%" height={220}>
      <PieChart>
        <Pie
          data={data}
          dataKey="value"
          nameKey="name"
          cx="50%"
          cy="50%"
          outerRadius={80}
          label={({ name, value }) => `${name} (${value})`}
          labelLine={false}
        >
          {data.map((_, i) => (
            <Cell key={i} fill={COLORS[i % COLORS.length]} />
          ))}
        </Pie>
        <Tooltip />
      </PieChart>
    </ResponsiveContainer>
  );
}

export function TimelineChart({ data }: { data: TimelineBucket[] }) {
  if (data.length === 0)
    return <p className="text-muted-foreground text-sm">No data for this period</p>;

  const classificationKeys = Array.from(
    new Set(data.flatMap((d) => Object.keys(d).filter((k) => k !== "period")))
  );

  const normalized = data.map((d) => {
    const entry: Record<string, string | number> = { period: d.period };
    for (const key of classificationKeys) {
      entry[key] = (d[key] as number) ?? 0;
    }
    return entry;
  });

  return (
    <ResponsiveContainer width="100%" height={300}>
      <LineChart data={normalized}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
        <XAxis
          dataKey="period"
          tick={{ fontSize: 11 }}
          tickFormatter={(v: string) =>
            v.includes("T") ? v.split("T")[1] : v.slice(5)
          }
        />
        <YAxis tick={{ fontSize: 11 }} allowDecimals={false} />
        <Tooltip />
        <Legend />
        {classificationKeys.map((key, i) => (
          <Line
            key={key}
            type="monotone"
            dataKey={key}
            stroke={COLORS[i % COLORS.length]}
            strokeWidth={2}
            dot={false}
          />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}

export function ConfidenceBarChart({ data }: { data: ChartEntry[] }) {
  if (data.length === 0) return <p className="text-muted-foreground text-sm">No data</p>;
  return (
    <ResponsiveContainer width="100%" height={220}>
      <BarChart data={data}>
        <XAxis dataKey="name" tick={{ fontSize: 12 }} />
        <YAxis domain={[0, 1]} tick={{ fontSize: 12 }} />
        <Tooltip formatter={(v) => typeof v === "number" ? v.toFixed(3) : v} />
        <Bar dataKey="value" radius={[4, 4, 0, 0]}>
          {data.map((_, i) => (
            <Cell key={i} fill={COLORS[i % COLORS.length]} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

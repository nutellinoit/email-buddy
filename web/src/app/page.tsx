import { Suspense } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { CategoryPieChart, ConfidenceBarChart, TimelineChart } from "@/components/charts";
import { getStats, getStatsSince, getRecentEmails, getHealth, getTimeline } from "@/lib/api";
import { TimeRangeSelector, type TimeRange } from "@/components/time-range-selector";

export const dynamic = "force-dynamic";
export const revalidate = 30;

const RANGE_HOURS: Record<TimeRange, number> = {
  "24h": 24,
  "7d": 168,
  "30d": 720,
};

const RANGE_LABELS: Record<TimeRange, string> = {
  "24h": "Last 24 hours",
  "7d": "Last 7 days",
  "30d": "Last 30 days",
};

interface Props {
  searchParams: Promise<{ range?: string }>;
}

export default async function DashboardPage({ searchParams }: Props) {
  const params = await searchParams;
  const range = (["24h", "7d", "30d"].includes(params.range ?? "")
    ? params.range
    : "24h") as TimeRange;
  const hours = RANGE_HOURS[range];

  const [health, stats, periodStats, recentEmails, timeline] = await Promise.all([
    getHealth(),
    getStats(),
    getStatsSince(hours),
    getRecentEmails(hours, 10),
    getTimeline(hours),
  ]);

  const pieData = Object.entries(periodStats.by_classification).map(
    ([name, value]) => ({ name, value })
  );

  const confidenceData = Object.entries(periodStats.average_confidence).map(
    ([name, value]) => ({ name, value: Number(value) })
  );

  const topSenders = Object.entries(periodStats.top_senders);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-semibold">Dashboard</h2>
        <div className="flex items-center gap-3">
          <Suspense>
            <TimeRangeSelector current={range} />
          </Suspense>
          <div className="flex items-center gap-1.5" title={`System: ${health.status}`}>
            <span
              className={`inline-block h-2.5 w-2.5 rounded-full ${
                health.status === "ok" ? "bg-green-500" : "bg-red-500"
              }`}
            />
            <span className="text-xs text-muted-foreground hidden sm:inline">
              {health.status === "ok" ? "Online" : health.status}
            </span>
          </div>
        </div>
      </div>

      {/* Stats cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm text-muted-foreground">
              Total Processed
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-3xl font-bold">{stats.total_processed}</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm text-muted-foreground">
              {RANGE_LABELS[range]}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-3xl font-bold">{periodStats.total_processed}</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm text-muted-foreground">
              Learning ({range})
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-3xl font-bold">{periodStats.learning_entries}</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm text-muted-foreground">
              Categories
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-3xl font-bold">
              {Object.keys(periodStats.by_classification).length}
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Timeline chart */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">
            Classification Timeline ({RANGE_LABELS[range]})
          </CardTitle>
        </CardHeader>
        <CardContent>
          <TimelineChart data={timeline} />
        </CardContent>
      </Card>

      {/* Charts */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">Classification Distribution</CardTitle>
          </CardHeader>
          <CardContent>
            <CategoryPieChart data={pieData} />
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">Average Confidence</CardTitle>
          </CardHeader>
          <CardContent>
            <ConfidenceBarChart data={confidenceData} />
          </CardContent>
        </Card>
      </div>

      {/* Top senders and recent emails */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">Top Senders ({range})</CardTitle>
          </CardHeader>
          <CardContent>
            {topSenders.length === 0 ? (
              <p className="text-muted-foreground text-sm">No senders in period</p>
            ) : (
              <ul className="space-y-1 text-sm">
                {topSenders.map(([sender, count]) => (
                  <li key={sender} className="flex justify-between">
                    <span className="truncate mr-2">{sender}</span>
                    <span className="text-muted-foreground shrink-0">
                      {count}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-sm">Recent Emails ({range})</CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            {recentEmails.length === 0 ? (
              <p className="text-muted-foreground text-sm p-4">No recent emails</p>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Subject</TableHead>
                    <TableHead className="w-24">Category</TableHead>
                    <TableHead className="w-20 text-right">Conf.</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {recentEmails.map((email) => (
                    <TableRow key={email.email_id}>
                      <TableCell className="truncate max-w-[200px]">
                        {email.subject || "(no subject)"}
                      </TableCell>
                      <TableCell>
                        <Badge variant="outline">{email.classification}</Badge>
                      </TableCell>
                      <TableCell className="text-right font-mono text-xs">
                        {email.confidence.toFixed(2)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

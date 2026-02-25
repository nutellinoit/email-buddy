import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { CategoryPieChart } from "@/components/charts";
import { LearningTable } from "@/components/learning-table";
import { getLearningStats, getLearning } from "@/lib/api";

export const dynamic = "force-dynamic";
export const revalidate = 30;

export default async function LearningPage() {
  const [stats, rules] = await Promise.all([
    getLearningStats(),
    getLearning(50, 30),
  ]);

  const typeData = Object.entries(stats.by_learning_type).map(
    ([name, value]) => ({ name, value })
  );

  const topDomains = Object.entries(stats.top_learning_domains);

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-semibold">Learning</h2>

      {/* Stats cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm text-muted-foreground">
              Total Rules
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-3xl font-bold">
              {stats.total_learning_entries}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm text-muted-foreground">
              Last 7 days
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-3xl font-bold">{stats.recent_learning_7d}</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm text-muted-foreground">
              Top Domains
            </CardTitle>
          </CardHeader>
          <CardContent>
            {topDomains.length === 0 ? (
              <p className="text-muted-foreground text-sm">None</p>
            ) : (
              <ul className="space-y-1 text-sm">
                {topDomains.map(([domain, count]) => (
                  <li key={domain} className="flex justify-between">
                    <span className="truncate mr-2">{domain}</span>
                    <span className="text-muted-foreground">{count}</span>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Type breakdown chart */}
      {typeData.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">Learning Type Breakdown</CardTitle>
          </CardHeader>
          <CardContent>
            <CategoryPieChart data={typeData} />
          </CardContent>
        </Card>
      )}

      {/* Active rules with search and pagination */}
      <div>
        <h3 className="text-sm font-medium mb-3">Active Rules (last 30 days)</h3>
        <LearningTable rules={rules} />
      </div>
    </div>
  );
}

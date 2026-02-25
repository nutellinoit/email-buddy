import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { getSummaries } from "@/lib/api";

export const dynamic = "force-dynamic";
export const revalidate = 60;

export default async function SummariesPage() {
  const summaries = await getSummaries(10);

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-semibold">Daily Summaries</h2>

      {summaries.length === 0 ? (
        <p className="text-muted-foreground">
          No daily summaries generated yet.
        </p>
      ) : (
        <div className="space-y-4">
          {summaries.map((summary) => {
            let statsObj: Record<string, unknown> = {};
            try {
              statsObj = JSON.parse(summary.stats_json);
            } catch {
              /* ignore */
            }
            const byClassification =
              (statsObj.by_classification as Record<string, number>) ?? {};
            const topSenders =
              (statsObj.top_senders as Record<string, number>) ?? {};

            return (
              <Card key={summary.id ?? summary.generated_at}>
                <CardHeader>
                  <div className="flex items-center justify-between">
                    <CardTitle className="text-sm">
                      {new Date(summary.generated_at).toLocaleDateString(
                        undefined,
                        {
                          weekday: "long",
                          year: "numeric",
                          month: "long",
                          day: "numeric",
                        }
                      )}
                    </CardTitle>
                    <div className="flex gap-2">
                      <Badge variant="outline">
                        {summary.total_processed} emails
                      </Badge>
                      <Badge
                        variant={summary.delivered ? "default" : "destructive"}
                      >
                        {summary.delivered ? "Delivered" : "Not delivered"}
                      </Badge>
                    </div>
                  </div>
                </CardHeader>
                <CardContent className="space-y-3">
                  {/* Classification breakdown */}
                  {Object.keys(byClassification).length > 0 && (
                    <div className="flex gap-3 flex-wrap">
                      {Object.entries(byClassification).map(([cat, count]) => (
                        <span key={cat} className="text-sm">
                          <span className="text-muted-foreground">{cat}:</span>{" "}
                          <span className="font-medium">{count}</span>
                        </span>
                      ))}
                    </div>
                  )}

                  {/* Top senders */}
                  {Object.keys(topSenders).length > 0 && (
                    <>
                      <Separator />
                      <div>
                        <p className="text-xs text-muted-foreground mb-1">
                          Top senders
                        </p>
                        <div className="flex gap-3 flex-wrap text-sm">
                          {Object.entries(topSenders).map(([sender, count]) => (
                            <span key={sender}>
                              <span className="truncate">{sender}</span>{" "}
                              <span className="text-muted-foreground">
                                ({count})
                              </span>
                            </span>
                          ))}
                        </div>
                      </div>
                    </>
                  )}

                  {/* Narrative */}
                  {summary.narrative && (
                    <>
                      <Separator />
                      <div>
                        <p className="text-xs text-muted-foreground mb-1">
                          AI Narrative
                        </p>
                        <p className="text-sm whitespace-pre-wrap">
                          {summary.narrative}
                        </p>
                      </div>
                    </>
                  )}
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}

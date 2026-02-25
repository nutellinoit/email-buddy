import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { getHealth, getConfig } from "@/lib/api";

export const dynamic = "force-dynamic";
export const revalidate = 60;

function ConfigItem({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="flex justify-between sm:block">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="font-medium">{value}</dd>
    </div>
  );
}

export default async function StatusPage() {
  const [health, config] = await Promise.all([getHealth(), getConfig()]);

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-semibold">System Status</h2>

      {/* Health */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Health</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex items-center gap-3">
            <span
              className={`inline-block h-3 w-3 rounded-full ${
                health.status === "ok" ? "bg-green-500" : "bg-red-500"
              }`}
            />
            <span className="font-medium">
              {health.status === "ok" ? "System OK" : `Status: ${health.status}`}
            </span>
          </div>
          <div className="text-sm text-muted-foreground space-y-1">
            <p>Database: <code className="text-xs">{health.database}</code></p>
            <p>Database exists: {health.database_exists ? "Yes" : "No"}</p>
          </div>
        </CardContent>
      </Card>

      {/* General */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">General</CardTitle>
        </CardHeader>
        <CardContent>
          <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-2 text-sm">
            <ConfigItem label="LLM Model" value={config.llm_model} />
            <ConfigItem label="Process Interval" value={`${config.process_interval}s`} />
            <ConfigItem label="IDLE Enabled" value={config.idle_enabled ? "Yes" : "No"} />
            <ConfigItem label="Dry Run" value={config.dry_run ? "Yes" : "No"} />
          </dl>
        </CardContent>
      </Card>

      {/* Email */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Email</CardTitle>
        </CardHeader>
        <CardContent>
          <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-2 text-sm">
            <ConfigItem label="Email Limit" value={config.email_limit} />
            <ConfigItem label="Fetch Days" value={`${config.email_fetch_days} days`} />
            <ConfigItem label="Retention" value={`${config.email_retention_days} days`} />
          </dl>
        </CardContent>
      </Card>

      {/* Learning */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Learning</CardTitle>
        </CardHeader>
        <CardContent>
          <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-2 text-sm">
            <ConfigItem label="Enabled" value={config.learning_enabled ? "Yes" : "No"} />
            <ConfigItem label="Retention" value={`${config.learning_retention_days} days`} />
          </dl>
        </CardContent>
      </Card>

      {/* Daily Summary */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Daily Summary</CardTitle>
        </CardHeader>
        <CardContent>
          <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-2 text-sm">
            <ConfigItem label="Enabled" value={config.daily_summary_enabled ? "Yes" : "No"} />
            <ConfigItem label="Hour" value={`${config.daily_summary_hour}:00`} />
          </dl>
        </CardContent>
      </Card>

      {/* Categories */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Categories</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {config.categories.map((cat, i) => (
            <div key={cat.name}>
              {i > 0 && <Separator className="mb-3" />}
              <div className="flex items-center gap-2 mb-1">
                <span className="font-medium text-sm">{cat.name}</span>
                {cat.is_default && <Badge variant="secondary">default</Badge>}
              </div>
              <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-1 text-sm text-muted-foreground">
                <ConfigItem label="Folder" value={cat.folder || "(inbox)"} />
                <ConfigItem label="Threshold" value={cat.threshold.toFixed(2)} />
              </dl>
              {cat.description && (
                <p className="text-xs text-muted-foreground mt-1">{cat.description}</p>
              )}
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}

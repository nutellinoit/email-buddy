import { Badge } from "@/components/ui/badge";
import { EmailsTable } from "@/components/emails-table";
import { getEmails, getConfig } from "@/lib/api";

export const dynamic = "force-dynamic";
export const revalidate = 30;

interface Props {
  searchParams: Promise<{ classification?: string }>;
}

export default async function EmailsPage({ searchParams }: Props) {
  const params = await searchParams;
  const classification = params.classification || undefined;

  const [emails, config] = await Promise.all([
    getEmails(500, classification),
    getConfig(),
  ]);

  const categories = config.categories.map((c) => c.name);

  return (
    <div className="space-y-4">
      <h2 className="text-2xl font-semibold">Email History</h2>

      {/* Category filter badges */}
      <div className="flex gap-2 flex-wrap">
        <a href="/emails">
          <Badge variant={!classification ? "default" : "outline"}>All</Badge>
        </a>
        {categories.map((cat) => (
          <a key={cat} href={`/emails?classification=${cat}`}>
            <Badge variant={classification === cat ? "default" : "outline"}>
              {cat}
            </Badge>
          </a>
        ))}
      </div>

      <EmailsTable data={emails} />
    </div>
  );
}

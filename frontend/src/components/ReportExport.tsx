import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Download } from "lucide-react";

import { api, describeError } from "../services/api";
import type { ReportMeta } from "../types/api";
import { Button } from "./ui";

/** Generates a report from stored records on the backend, then downloads it. */
export function ReportExport({ kind, subjectId, label = "Export" }: { kind: ReportMeta["kind"]; subjectId: string; label?: string }) {
  const qc = useQueryClient();
  const exportReport = useMutation({
    mutationFn: async (format: "json" | "markdown") => {
      const report = await api.createReport(kind, subjectId);
      await api.downloadReport(report.id, format);
      return report;
    },
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["reports"] }),
  });
  return (
    <div className="flex items-center gap-2">
      <Button size="sm" icon={<Download className="h-3.5 w-3.5" />} loading={exportReport.isPending && exportReport.variables === "json"}
        disabled={exportReport.isPending} onClick={() => exportReport.mutate("json")}>
        {label} JSON
      </Button>
      <Button size="sm" icon={<Download className="h-3.5 w-3.5" />} loading={exportReport.isPending && exportReport.variables === "markdown"}
        disabled={exportReport.isPending} onClick={() => exportReport.mutate("markdown")}>
        {label} Markdown
      </Button>
      {exportReport.isError && <span role="alert" className="text-xs text-rose-700">{describeError(exportReport.error)}</span>}
      {exportReport.isSuccess && <span role="status" className="text-xs text-emerald-700">Saved {exportReport.data.id}</span>}
    </div>
  );
}

"use client";

import { useMemo, useState } from "react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

export interface Column<T> {
  header: string;
  accessor: (row: T) => string | number | null | undefined;
  cell?: (row: T) => React.ReactNode;
  className?: string;
}

interface DataTableProps<T> {
  data: T[];
  columns: Column<T>[];
  searchPlaceholder?: string;
  pageSize?: number;
  keyAccessor: (row: T) => string;
}

export function DataTable<T>({
  data,
  columns,
  searchPlaceholder = "Search...",
  pageSize = 10,
  keyAccessor,
}: DataTableProps<T>) {
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(0);

  const filtered = useMemo(() => {
    if (!search.trim()) return data;
    const q = search.toLowerCase();
    return data.filter((row) =>
      columns.some((col) => {
        const val = col.accessor(row);
        return val != null && String(val).toLowerCase().includes(q);
      })
    );
  }, [data, search, columns]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize));
  const safePage = Math.min(page, totalPages - 1);
  const start = safePage * pageSize;
  const paged = filtered.slice(start, start + pageSize);

  // Reset to first page when search changes
  const handleSearch = (value: string) => {
    setSearch(value);
    setPage(0);
  };

  return (
    <div className="space-y-3">
      {/* Search */}
      <Input
        placeholder={searchPlaceholder}
        value={search}
        onChange={(e) => handleSearch(e.target.value)}
        className="max-w-sm"
      />

      {/* Table */}
      <div className="rounded-md border overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              {columns.map((col) => (
                <TableHead key={col.header} className={col.className}>
                  {col.header}
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {paged.length === 0 ? (
              <TableRow>
                <TableCell
                  colSpan={columns.length}
                  className="text-center text-muted-foreground py-6"
                >
                  No results found.
                </TableCell>
              </TableRow>
            ) : (
              paged.map((row) => (
                <TableRow key={keyAccessor(row)}>
                  {columns.map((col) => (
                    <TableCell key={col.header} className={col.className}>
                      {col.cell ? col.cell(row) : String(col.accessor(row) ?? "—")}
                    </TableCell>
                  ))}
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      {/* Pagination */}
      <div className="flex items-center justify-between text-sm text-muted-foreground">
        <span>
          {filtered.length === 0
            ? "No results"
            : `${start + 1}–${Math.min(start + pageSize, filtered.length)} of ${filtered.length}`}
        </span>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={safePage === 0}
            onClick={() => setPage(safePage - 1)}
          >
            Previous
          </Button>
          <span>
            {safePage + 1} / {totalPages}
          </span>
          <Button
            variant="outline"
            size="sm"
            disabled={safePage >= totalPages - 1}
            onClick={() => setPage(safePage + 1)}
          >
            Next
          </Button>
        </div>
      </div>
    </div>
  );
}

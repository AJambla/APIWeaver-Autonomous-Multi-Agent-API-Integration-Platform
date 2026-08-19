import { cn } from "@/lib/cn";

export interface Column<T> {
  key: keyof T | string;
  header: string;
  render?: (row: T) => React.ReactNode;
  className?: string;
}

export function Table<T extends { id?: string | number }>({
  columns,
  rows,
  rowHref,
  emptyMessage = "No data yet.",
}: {
  columns: Array<Column<T>>;
  rows: T[];
  rowHref?: (row: T) => string;
  emptyMessage?: string;
}) {
  if (rows.length === 0) {
    return (
      <div className="rounded-lg border border-border bg-bg-secondary p-8 text-center text-sm text-text-secondary">
        {emptyMessage}
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className="w-full border-collapse text-sm">
        <thead className="bg-bg-tertiary text-left text-text-secondary">
          <tr>
            {columns.map((col) => (
              <th key={String(col.key)} className={cn("px-4 py-3 font-semibold", col.className)}>
                {col.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => {
            const href = rowHref?.(row);
            return (
              <tr
                key={row.id ?? i}
                className={cn(
                  "border-t border-border hover:bg-bg-secondary",
                  href && "cursor-pointer",
                )}
                onClick={href ? () => (window.location.href = href) : undefined}
              >
                {columns.map((col) => (
                  <td key={String(col.key)} className={cn("px-4 py-3", col.className)}>
                    {col.render ? col.render(row) : String(row[col.key as keyof T] ?? "")}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

import * as React from "react";

export function Table({
  className = "",
  ...props
}: React.HTMLAttributes<HTMLTableElement>) {
  return (
    <div className="relative w-full overflow-auto">
      <table
        className={`w-full caption-bottom text-xs text-left ${className}`}
        {...props}
      />
    </div>
  );
}

export function TableHeader({
  className = "",
  ...props
}: React.HTMLAttributes<HTMLTableSectionElement>) {
  return (
    <thead
      className={`border-b border-line bg-surface/40 text-[11px] uppercase tracking-wider font-semibold text-ink-faint ${className}`}
      {...props}
    />
  );
}

export function TableBody({
  className = "",
  ...props
}: React.HTMLAttributes<HTMLTableSectionElement>) {
  return (
    <tbody
      className={`divide-y divide-line/40 [&_tr:last-child]:border-0 ${className}`}
      {...props}
    />
  );
}

export function TableRow({
  className = "",
  ...props
}: React.HTMLAttributes<HTMLTableRowElement>) {
  return (
    <tr
      className={`transition-colors hover:bg-surface/50 data-[state=selected]:bg-surface ${className}`}
      {...props}
    />
  );
}

export function TableHead({
  className = "",
  ...props
}: React.ThHTMLAttributes<HTMLTableCellElement>) {
  return (
    <th
      className={`h-9 px-4 text-left align-middle font-medium text-ink-faint [&:has([role=checkbox])]:pr-0 ${className}`}
      {...props}
    />
  );
}

export function TableCell({
  className = "",
  ...props
}: React.TdHTMLAttributes<HTMLTableCellElement>) {
  return (
    <td
      className={`p-4 align-middle [&:has([role=checkbox])]:pr-0 ${className}`}
      {...props}
    />
  );
}
